# M4 Plan — Scale & Infra

**Status:** Active
**Branch:** `M4`
**Roadmap gate (done-when):** sustained 600 QPS on `/search` at p95 < 200 ms over
a 2M-chunk index; ingestion ≥ 500 docs/min/worker; **cross-tenant leakage test
green**.

M0–M3 built a correct, current, cited knowledge system. M4 proves it holds up
and locks down isolation: Postgres RLS + mandatory tenant filter, a blocking
cross-tenant leakage test, per-tenant/per-source rate limiting, a real
load-test harness, and the k8s + Terraform to run it.

---

## The honesty split (the central decision)

The done-when has two halves with very different verifiability in a hermetic
dev/CI environment — the same stance M2/M3 took:

- **Cross-tenant leakage → BLOCKING, CI-verified.** Defense-in-depth isolation
  (Postgres RLS enforced for a least-privilege role **+** the existing mandatory
  app-layer filter) with a dedicated leakage test that fails the build on any
  cross-tenant read. This is the half M4 can and does *prove*.
- **Throughput targets (600 QPS / p95 < 200 ms / 2M chunks / 500 docs/min) →
  DOCUMENTED, not CI-gated.** There is no 2M-chunk index or load cluster in
  CI/sandbox, so these numbers cannot be honestly asserted green here. M4 ships
  the **real measurement tooling** (a Locust harness that reports p50/p95/p99 +
  throughput) and the **infra to run at scale** (k8s HPA on CPU + queue depth,
  Terraform for managed Postgres/Qdrant/Redis/k8s), plus the scaling levers
  (stateless API, Qdrant shard-by-tenant, per-source egress limits). The harness
  is demonstrated with a local smoke run; the headline numbers are a target to
  reproduce against a real deployment, documented with methodology — never
  faked into a passing test.

---

## Scope (from ROADMAP.md §M4 / ARCHITECTURE.md §6–8)

1. Multi-tenancy: Postgres RLS, mandatory tenant filter, Qdrant shard-by-tenant.
2. Cross-tenant leakage test in CI (the blocking gate).
3. Ingress + egress rate limiting (per-tenant, per-source token buckets).
4. `scripts/load_test.py` (Locust) + autoscaling on CPU + queue depth.
5. Terraform + k8s manifests.

Out of scope: the Rust BM25/RRF hot-path (stretch), real cloud apply of
Terraform (no creds in sandbox; `validate`-level only), embedding fine-tune (M5).

---

## Current state (what M4 builds on)

| Piece | State | File |
|---|---|---|
| Mandatory tenant filter (Qdrant + BM25 + every repo query) | Done (M0–M3) | `packages/storage/.../qdrant.py`, `fts.py`, `repository.py` |
| Tenant isolation tests (search/bm25/processes/ask) | Done | `tests/integration/test_*` |
| `TokenBucketSpec` on connectors | Defined, unused | `packages/connectors/.../base.py` |
| Redis in compose + api/worker deps | Present, unused | `infra/docker-compose.yml` |
| `scripts/load_test.py` | Stub (`NotImplementedError`) | `scripts/load_test.py` |
| `infra/k8s`, `infra/terraform` | README placeholders | `infra/*/README.md` |
| Postgres RLS | Not enabled (app-layer filter only) | — |

---

## Design decisions

### D1 — RLS for a least-privilege role; superuser app stays filtered
Migration `0006` enables `ROW LEVEL SECURITY` + `FORCE` on every tenant table
with a policy `USING (tenant_id = current_setting('app.current_tenant', true)::uuid)`
— fail-closed (an unset GUC matches nothing). It also creates a **non-superuser
`cortex_app` role** with table grants. Postgres superusers *bypass* RLS, so the
existing app (connecting as `cortex`) is unaffected and the app-layer mandatory
filter remains the active guard; RLS is **defense-in-depth proven via the
restricted role**, which is what production runs as. A `tenant_session` helper
issues `SET LOCAL app.current_tenant` per transaction.

### D2 — Cross-tenant leakage test as the blocking gate
A dedicated test connects as `cortex_app` (RLS enforced), sets the GUC to tenant
A, and asserts that **even a query with no `WHERE tenant_id`** returns only A's
rows; switching the GUC flips results; an unset GUC returns nothing. Combined
with the existing filter-level isolation tests, this is the "cross-tenant
leakage test green" half of the done-when. It runs in the standard CI test job
(required), so a leak fails the build.

### D3 — Token bucket in Redis (atomic), in-memory for unit tests
A `TokenBucket` primitive in `cortex.storage.ratelimit`: Redis-backed with an
atomic Lua refill-and-consume (correct under concurrency), plus an in-memory
implementation for unit tests and key-free local runs. `allow(key, cost) ->
(ok, retry_after)`. Keyed by tenant (ingress) or source (egress).

### D4 — Ingress limiting: per-tenant, read vs heavy quotas
A FastAPI dependency consults the bucket per `(tenant, bucket-class)` —
`read` for `/search` & `/processes`, `heavy` for `/ask` (LLM-cost) — per
API.md's table. Over-limit → `429` + `Retry-After`. Buckets are per-tenant so
one tenant can't starve another. Disabled when no `REDIS_URL` (local dev) unless
the in-memory limiter is selected, so existing tests stay green.

### D5 — Egress limiting: per-source token bucket in ingestion
The worker consumes the connector's `rate_limit: TokenBucketSpec` before each
fetch batch, so a connector never exceeds a source's quota; backoff is the
existing requeue path. Demonstrated against the sample connector.

### D6 — Qdrant shard-by-tenant
`ensure_collection` sets `shard_number` and documents `tenant_id` as the shard
key; the **mandatory payload filter remains the isolation guarantee** (already
tested). Custom shard-key routing is noted for the production cluster; the
single-node dev Qdrant keeps the filter as the enforced boundary.

### D7 — Load harness measures, doesn't fake
`scripts/load_test.py` is a real Locust driver hitting `/search` (and `/ask`)
with per-tenant headers, reporting p50/p95/p99 + throughput. `just loadtest`
runs it. CI does **not** run it as a gate (no scale env); a short local smoke
run demonstrates it works and the README documents how to reproduce the 600 QPS
target against a real deployment.

### D8 — Infra as code, validate-level
k8s: separate API + worker `Deployment`s, `Service`, `HPA` (CPU + a documented
queue-depth custom metric), `ConfigMap`/`Secret`. Terraform: modules for managed
Postgres, Qdrant, Redis, and a k8s cluster. Validated with `kubectl --dry-run` /
`terraform validate` when the tools are present; otherwise shipped as
well-formed, reviewed manifests (no cloud apply in the sandbox).

---

## Workstreams & feature commits

Order: RLS → leakage gate → rate-limit primitive + ingress → egress → Qdrant
shard → load harness → k8s → terraform → docs. One commit per feature.

### 1. `feat(storage): Postgres RLS + least-privilege app role (migration 0006)`
- Migration enabling RLS/FORCE + policies on all tenant tables; `cortex_app`
  role + grants; `tenant_session` helper (`SET LOCAL app.current_tenant`).
  Drift-checked (RLS isn't ORM-modeled — migration only). Integration test that
  the policy SQL applies.

### 2. `test(security): cross-tenant leakage test under RLS (CI gate)`
- Connect as `cortex_app`; prove no-WHERE queries are tenant-scoped, GUC flips
  results, unset GUC → empty. Marked so CI surfaces it as the leakage gate.

### 3. `feat(api): Redis token-bucket rate limiter + per-tenant ingress limits`
- `cortex.storage.ratelimit` (Redis + in-memory); FastAPI dependency on
  `/search`, `/processes`, `/ask` with read/heavy quotas → `429` + `Retry-After`.
  Unit tests (in-memory) + integration (Redis); per-tenant isolation asserted.

### 4. `feat(workers): per-source egress rate limiting in ingestion`
- Worker consumes the connector token bucket before each fetch; over-budget
  waits/backs off. Test: a tight bucket throttles; refill lets it proceed.

### 5. `feat(storage): Qdrant shard-by-tenant`
- `shard_number` on `ensure_collection`; tenant shard-key documented; mandatory
  filter unchanged. Test: isolation still holds with sharding configured.

### 6. `perf(load): Locust load-test harness`
- Real `scripts/load_test.py` (Locust) + `just loadtest`; reports p50/p95/p99 +
  throughput; smoke-run locally. README documents the 600 QPS reproduction.

### 7. `infra(k8s): API/worker Deployments, Services, HPA, config`
- Manifests under `infra/k8s/`; HPA on CPU + queue-depth metric; probes from
  `/healthz` `/readyz`. `kubectl --dry-run` validated if available.

### 8. `infra(terraform): managed Postgres + Qdrant + Redis + k8s modules`
- HCL modules under `infra/terraform/`; `terraform validate` if available.

### 9. `docs: mark M4 complete`
- README, CHANGELOG, ROADMAP; record what's gated (leakage) vs targeted
  (throughput) honestly.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Superuser bypasses RLS → false sense of security | D1: enforce + test against the non-superuser `cortex_app` role prod uses; FORCE RLS; fail-closed policy. |
| Throughput numbers unverifiable in sandbox | The honesty split: leakage is the gate; throughput is a documented target with a real harness + a smoke run, never a faked pass. |
| Rate limiting breaks existing tests / local dev | D3/D4: limiter no-ops without `REDIS_URL`; in-memory limiter for tests; per-tenant keys. |
| Custom Qdrant shard keys flaky on single-node dev | D6: keep the mandatory filter as the enforced boundary; shard_number only; custom routing documented for prod. |
| Terraform/k8s can't apply without creds | D8: validate-level only; well-formed reviewed manifests; no cloud apply claimed. |

## Verification (milestone exit)

1. Migrations apply (`0006`); `cortex_app` role exists with RLS policies.
2. **Cross-tenant leakage test green** as the non-superuser role — no-WHERE
   queries are tenant-scoped, GUC flips results, unset GUC returns nothing — plus
   the existing filter-level isolation tests. (The done-when's verifiable half.)
3. Ingress limiter returns `429` + `Retry-After` past quota, per-tenant; egress
   bucket throttles a connector; both green.
4. `scripts/load_test.py` runs (smoke) and reports latency percentiles +
   throughput; README documents reproducing the 600 QPS target at scale.
5. k8s manifests + Terraform modules present and validate-level clean.
6. Full suite green with `EVAL_GATE=blocking`.
