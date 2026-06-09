# Test Strategy — Cortex

Testing maps onto the architecture: each ingestion-pipeline stage is a pure,
unit-testable function, and quality (retrieval/extraction) is a first-class,
regression-protected property — not an afterthought.

---

## 1. The four tiers

| Tier | Scope | Speed / where | Marker | Examples |
|---|---|---|---|---|
| **Unit** | pure functions, no I/O | fast, every PR | _(none)_ | source-aware chunkers, RRF fusion, Recall@k/nDCG@k, token-bucket logic, **process-step citation invariant** |
| **Integration** | real Postgres / Qdrant / Redis | every PR (service containers) | `integration` | ingest idempotency (`content_hash` no-op), `/search` tenant filter, connector contract tests vs recorded fixtures |
| **Eval (the gate)** | golden-set regression | PR + nightly | `eval` | Recall@10 ≥ 0.85, nDCG@10 ≥ 0.70, faithfulness ≥ 4.0, citation-validity ≥ 0.95 |
| **Load** | throughput / latency | nightly / manual, **not** PR-blocking | `load` | 600 QPS `/search` p95 < 200 ms over a 2M-chunk index (M4) |

Run subsets with markers: `uv run pytest -m "not integration and not eval and not load"`
for the fast loop; `just test` for unit + integration; `just eval` for the gate.

## 2. Required CI checks (block merge)

1. **lint + format** (ruff) and **types** (mypy strict).
2. **unit + integration** green; **coverage ≥ 70%** (raised over time).
3. **Cross-tenant leakage test** — seeds two tenants, asserts zero cross-tenant
   results. Non-negotiable per `ARCHITECTURE.md` §6; becomes blocking the moment
   multi-tenant retrieval exists.
4. **Eval gate** — see below.

## 3. The eval gate: advisory → blocking

The gate (`cortex.eval.gate`) reads `EVAL_GATE`:

- **`advisory`** (current default): compute and report metrics, never fail the
  build. Correct stance until a credible, human-labeled golden set exists —
  failing a build on synthetic-only data would be dishonest.
- **`blocking`**: any metric below its threshold fails CI.

Flip to `blocking` once the golden set below is real. Thresholds live in one place
(`THRESHOLDS` in `cortex.eval.gate`) and mirror PRD §8.

## 4. Golden-set policy

The gate is only as honest as its data. Therefore:

- **Held-out test split is never used in training** (embedding fine-tune, §M5).
  Track the train/test gap to catch overfit.
- **Provenance recorded** for every labeled query (who/what labeled it, source).
- **Synthetic queries are allowed but quarantined**: generated from chunks by an
  LLM, filtered by round-trip consistency, and stored separately from
  human-labeled queries so the two are never silently mixed.
- **Refresh cadence**: periodically refresh the golden set as the corpus evolves;
  a stale golden set silently rots the gate.
- Fixtures and the seed corpus live in `tests/fixtures/`.

## 5. Reporting

`packages/eval` emits a markdown + JSON report per run (metrics, deltas vs. last
run, per-source breakdown) and pushes headline metrics to Prometheus so Grafana
tracks quality over time. The nightly `eval.yml` workflow uploads the report as a
build artifact.

## 6. Writing tests

- Co-locate by tier under `tests/{unit,integration,eval}/`.
- Integration tests must clean up after themselves and assume the compose stack
  (or testcontainers) is available; mark them `integration` so the fast loop skips
  them.
- Prefer testing a pipeline stage as a pure function over end-to-end where
  possible — it's the design intent (`INGESTION.md` §2).
