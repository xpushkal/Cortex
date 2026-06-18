# API — Cortex

**Status:** Draft v1
**Base URL:** `/v1`
**Auth:** Bearer token (per tenant). Tenant also asserted via `X-Tenant` header.

All endpoints are tenant-scoped. A request whose token tenant ≠ `X-Tenant` is
rejected `403`. Retrieval is always tenant-filtered server-side; there is no way to
query across tenants.

Enforcement is gated by `CORTEX_AUTH_REQUIRED` (off in dev/tests, where the tenant
comes from `X-Tenant` directly; on in production, where a missing/invalid token is
`401`). Mint a key with `python -m cortex.api.auth mint --tenant <name> --name <label>`
— the raw token is shown once; only its SHA-256 is stored (`api_keys`). With
`CORTEX_RLS_ENFORCE`, request sessions run under the least-privilege `cortex_app`
role so Postgres RLS is the active guard; the tenant GUC is set either way.

---

## Conventions

- JSON request/response.
- Errors: `{ "error": { "code": "...", "message": "..." } }` with appropriate HTTP
  status.
- Every knowledge-bearing response includes `citations` and `freshness`.
- Rate limited (see bottom). `429` includes `Retry-After` seconds.

---

## `POST /v1/ask`
Grounded Q&A: hybrid retrieve → rerank → generate, with citations.

**Request**
```json
{
  "q": "How do we handle a refund over $500?",
  "filters": { "source_kind": ["slack", "notion"], "since": "2026-01-01" },
  "max_context": 8
}
```

**Response**
```json
{
  "answer": "Refunds over $500 are routed to finance for approval...",
  "citations": [
    { "chunk_id": "uuid-a", "source_kind": "notion", "artifact_id": "uuid", "quote": "..." }
  ],
  "freshness": { "state": "fresh", "oldest_source": "2026-05-30T..." },
  "used_processes": ["process:refund-over-500@v4"]
}
```
- If a relevant **process object** exists, the answer is grounded in it (and listed
  in `used_processes`); otherwise it falls back to raw chunk retrieval.
- `freshness.state` ∈ `fresh | partially_stale | stale`. Stale context is labeled,
  never hidden.

---

## `POST /v1/search`
Ranked retrieval, no generation. Lower latency; for agent tools that want raw hits.

**Request**
```json
{ "q": "incident escalation sev1", "k": 10, "filters": { "freshness": "fresh" } }
```

**Response**
```json
{
  "results": [
    { "chunk_id": "uuid", "score": 0.83, "source_kind": "notion",
      "text": "...", "artifact_id": "uuid", "created_at": "..." }
  ]
}
```

---

## `GET /v1/processes`
List process objects for the tenant.

Query params: `status` (`active|stale|draft|deprecated`), `q` (name search),
`limit`, `cursor`.

```json
{
  "processes": [
    { "id": "process:refund-over-500", "name": "Refund over $500",
      "version": 4, "status": "active", "confidence": 0.91,
      "freshness": "fresh", "updated_at": "..." }
  ],
  "next_cursor": null
}
```

## `GET /v1/processes/{id}`
Full current version (canonical process JSON, `DATA_MODEL.md` §5).

## `GET /v1/processes/{id}/versions`
Version history with diffs.

## `POST /v1/processes/{id}/review`
Human-in-loop: approve / reject / edit a draft or stale process.
```json
{ "action": "approve", "edits": { "steps": [ ... ] }, "reviewer": "user@co" }
```

---

## `GET /v1/skills`
Export the agent-consumable **skills file** for the tenant/scope. This is the
"executable skills file for AI" deliverable.

Query params: `scope` (e.g. `support`, `finance`), `include_stale` (default false),
`format` (`json` default).

**Response (abridged)**
```json
{
  "tenant": "demo",
  "scope": "support",
  "generated_at": "2026-06-09T...",
  "freshness_manifest": { "fresh": 18, "stale": 2, "expired": 0 },
  "skills": [
    {
      "name": "Refund over $500",
      "trigger": "Customer requests a refund exceeding $500 USD",
      "steps": [
        { "action": "Verify order and eligibility", "actor": "support_agent",
          "citations": ["chunk:uuid-a"] },
        { "action": "Route to finance if amount > $500", "actor": "support_agent",
          "decision": { "if": "amount_usd > 500" }, "citations": ["chunk:uuid-b"] }
      ],
      "freshness": "fresh",
      "version": 4
    }
  ]
}
```
- Only `active` + non-expired processes by default.
- Every step retains citations so the consuming agent can verify provenance.
- `freshness_manifest` tells the agent how current the skill set is.

---

## Source management

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/sources` | Connect a source (kind + config/scopes) |
| `GET` | `/v1/sources` | List sources + sync status |
| `POST` | `/v1/sources/{id}/sync` | Trigger backfill / re-sync |
| `DELETE` | `/v1/sources/{id}` | Disconnect + purge its knowledge |

---

## Rate limiting (ingress / serving)

Per-tenant Redis token buckets, separate quotas for cheap vs. LLM-backed ops:

| Bucket | Endpoints | Default |
|--------|-----------|---------|
| `read` | `/search`, `/processes*` | 60 req / 10 s |
| `heavy` | `/ask`, `/skills` | 10 req / 10 s (LLM cost) |
| `admin` | `/sources*` | 20 req / min |

- `429` response includes `Retry-After` and `X-RateLimit-Remaining`.
- Buckets are atomic (Lua) for correctness under concurrent pods.
- Quotas are per-tenant config; defaults above.
