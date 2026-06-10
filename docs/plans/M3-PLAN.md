# M3 Plan — Freshness Loop

**Status:** Active
**Branch:** `M3`
**Roadmap gate (done-when):** a change to a source artifact is retrievable in
< 60 s (webhook path) and dependent process objects are correctly marked
**stale**; **no stale data served unlabeled**.

M2 turned chunks into versioned, cited process objects. M3 keeps them current:
change-driven re-ingest, staleness marking + TTL expiry, contradiction
detection → new version + review flag, and freshness surfaced in serving so
nothing stale is ever served as current.

---

## Scope (from ROADMAP.md §M3 / INGESTION.md §5)

1. Incremental sync (webhook path) + idempotent re-ingest.
2. Staleness marking on source change; TTL sweep → expired.
3. Contradiction detection → new version + review flag.
4. Freshness surfaced in `/ask` (and `/processes`; `/skills` is M6 and will read
   the same table).

Out of scope: real source webhooks/credentials (M4 connectors), the full
review UI, autoscaling/backpressure (M4), DLQ. The change-driven path is
exercised through a generic ingest-event endpoint over the deterministic
sample corpus.

---

## Current state (what M3 builds on)

| Piece | State | File |
|---|---|---|
| Idempotent re-ingest (changed `content_hash` → re-pipeline that artifact) | Done (M0) | `apps/workers/.../ingest.py` |
| Process versioning (changed body → new draft version, no overwrite) | Done (M2) | `packages/knowledge/.../repository.py` |
| `process.status` (draft/active/stale/deprecated) | Exists; `stale` unused | `packages/storage/.../models.py` |
| Qdrant payload `freshness` field | Exists, always `"fresh"` | `packages/storage/.../qdrant.py` |
| `/ask` freshness | Stubbed `{"state": "fresh"}` | `apps/api/.../ask.py` |
| `freshness` table (DATA_MODEL.md §2) | Missing | — |
| Connector `poll()` + `Cursor` | Contract exists; sample is static | `packages/connectors/.../base.py` |

---

## Design decisions

### D1 — Freshness as a table, source of truth for serving
A `freshness` table (migration 0005; DATA_MODEL.md §2) holds one row per tracked
object: `(tenant_id, object_type ∈ {process,chunk,entity}, object_id, state ∈
{fresh,stale,expired}, reason, last_validated_at, ttl_seconds)`. M3 tracks
**process** freshness primarily (the done-when is about process objects); the
schema is generic for chunk/entity in later milestones. `process.status` stays
lifecycle (draft/active/deprecated); **freshness state is orthogonal** and lives
in this table — staleness is no longer overloaded onto `status`.

### D2 — Change-driven staleness (before re-extraction)
When an artifact's content changes, the ingest path — *before* deleting the old
chunks — finds every process citing those chunks (`process_steps → citations →
chunks → artifact`) and marks them `stale` in the freshness table with
`reason="source artifact <ext_id> changed"`. Re-extraction then runs (M2 wiring)
and writes a new process version. With per-artifact clustering a process's
dependency is its own artifact, so this is the demonstrable dependent-staleness
path; the join generalizes to cross-artifact processes unchanged.

### D3 — Contradiction detection → new version + review flag
On re-extraction, compare the new body to the active version (M2 already writes
a new version on any change). A **contradiction** is a step whose action matches
an existing step (lexical) but whose actor or decision differs — a changed
approver/threshold, not just added detail. A contradicting change records a
`review_reason` (the diff) on the new version and leaves it `draft` + `stale`
(never auto-served as current). A non-contradicting change still versions but is
eligible for auto-revalidation. The detector is a pure function in knowledge.

### D4 — TTL sweep → expired
A periodic job (`python -m cortex.workers.freshness_sweep`) sets any freshness
row whose `last_validated_at + ttl_seconds < now()` to `expired`. Expired
processes are filtered out of `/ask` grounding and labeled in `/processes`.
Per-type TTL defaults (process 90d) are written at row creation; the sweep is a
single tenant-agnostic UPDATE and is idempotent.

### D5 — Incremental sync via a generic ingest-event endpoint
Real source webhooks need M4 connectors/credentials. M3 ships the
**change-driven entry point**: `POST /v1/ingest/events` (X-Tenant) accepting a
changed artifact `{source_kind, external_id, kind, content}` → runs the
idempotent change pipeline (re-chunk/embed/extract + mark dependents stale) and
returns once the change is queryable. The webhook-path `< 60 s` latency is met
trivially (synchronous re-ingest is milliseconds); the test asserts a changed
artifact is retrievable immediately after the call.

### D6 — Serving guarantee: no stale served unlabeled
`/ask`: when grounding in a process, read its freshness; an **expired** process
is not used for grounding (falls back to chunks); a **stale** process still
grounds but the answer's `freshness.state` is `stale` (labeled, never hidden).
`/processes` returns each process's freshness state. The review endpoint
(`POST /v1/processes/{id}/review`, action `approve`) promotes a reviewed draft
to `active` and resets freshness to `fresh` — closing the loop.

---

## Workstreams & feature commits

Order: table → freshness repo → contradiction detector → wire staleness into
ingest → TTL sweep job → ingest-event + review endpoints → freshness in serving
→ eval → docs. One commit per feature (repo convention, no co-author trailers).

### 1. `feat(storage): freshness table (migration 0005) + ORM`
- `Freshness` ORM + migration; `(tenant_id, object_type, object_id)` unique;
  tenant index. Drift-checked against autogenerate. Integration round-trip test.

### 2. `feat(knowledge): freshness repository`
- `set_freshness` / `get_freshness_map` (object_id → state),
  `mark_processes_stale_for_artifact`, `ttl_sweep`, `revalidate_process`
  (→ fresh). Tenant-scoped, idempotent. Integration tests.

### 3. `feat(knowledge): contradiction detection`
- `detect_contradiction(active_body, new_body) -> ContradictionReport` (pure):
  matched-action steps with differing actor/decision. Unit tests.

### 4. `feat(workers): change-driven re-ingest marks dependents stale`
- In `ingest_source`, the changed-artifact branch marks dependent processes
  stale (D2) before dropping old chunks; on re-extraction, a contradicting body
  records the review reason and stays draft+stale (D3). New processes register a
  `fresh` freshness row. Integration test: change an artifact → its process is
  stale + a new version exists.

### 5. `feat(workers): TTL sweep job`
- `freshness_sweep` function + `python -m cortex.workers.freshness_sweep` CLI
  (D4). Integration test: a row past its TTL flips to `expired`; idempotent.

### 6. `feat(api): ingest-event webhook + process review endpoint`
- `POST /v1/ingest/events` (D5) and `POST /v1/processes/{id}/review`
  (approve → active + fresh). Integration tests incl. tenant isolation.

### 7. `feat(api): surface freshness in /ask and /processes`
- `/ask` reads process freshness: expired → not grounded (chunk fallback);
  stale → grounded but `freshness.state="stale"`; else `fresh`. `/processes`
  carries freshness state. The "no stale served unlabeled" guarantee.
  Integration tests.

### 8. `feat(eval): freshness verification`
- Eval-marked tests proving the done-when: (a) a changed artifact is
  retrievable immediately; (b) the dependent process is marked stale; (c) an
  expired process is never served as current and is labeled; (d) a stale
  process is labeled `stale` in `/ask`.

### 9. `docs: mark M3 complete`
- README, CHANGELOG, ROADMAP, plan status.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Old citations cascade-deleted on artifact change before staleness is computed | D2 marks dependents stale **before** the delete; the new version carries fresh citations. |
| Per-artifact clustering makes "dependents" trivial | Honest for this corpus; the `steps→citations→chunks→artifact` join is the real dependency query and generalizes to cross-artifact processes unchanged. |
| Freshness state vs `process.status` overlap | D1: freshness table is the single source of truth for fresh/stale/expired; `status` stays lifecycle-only. |
| Real webhooks absent | D5: generic ingest-event endpoint exercises the change path; real connectors are M4. Latency gate met trivially (synchronous). |
| Chunk-level TTL not tabled | M3 tracks process freshness (the done-when's subject); chunk/entity rows use the same schema in later milestones. |

## Verification (milestone exit)

1. `POST /v1/ingest/events` with changed content → the new content is returned by
   `/v1/search` immediately (< 60 s) and a new process version exists.
2. The dependent process is `stale` in the freshness table and labeled `stale`
   in `/ask` / `/processes`.
3. TTL sweep flips an over-age process to `expired`; `/ask` no longer grounds in
   it (chunk fallback) and `/processes` labels it `expired`.
4. `POST /v1/processes/{id}/review` (approve) returns it to `active` + `fresh`.
5. No stale/expired process is ever served as current unlabeled (eval test).
6. Cross-tenant isolation holds on the new endpoints and freshness queries.
