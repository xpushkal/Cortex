# M1 Plan — Retrieval Quality

**Status:** Complete (2026-06-10) — Recall@10 0.952 / nDCG@10 0.908 on the held-out test split; blocking gate + regression canary green.
**Branch:** `M1`
**Roadmap gate (done-when):** Recall@10 ≥ 0.85 **and** nDCG@10 ≥ 0.70 on the
held-out golden set, and a deliberate quality regression fails CI.

M0 shipped a dense-only vertical slice (sample corpus → fixed chunks → hashing
embedder → Qdrant → `POST /v1/search`). M1 makes retrieval *good* and *measured*:
source-aware chunking with contextual blurbs, hybrid BM25 + dense retrieval with
RRF fusion and cross-encoder reranking, and an eval harness that turns the
existing advisory CI gate into a blocking regression gate.

---

## Scope (from ROADMAP.md §M1)

1. Source-aware chunking + contextual blurbs.
2. BM25 + dense + RRF fusion; cross-encoder rerank.
3. Eval harness: retrieval golden set + Recall@k / nDCG@k / MRR.
4. Wire the CI regression gate (advisory → blocking).

Out of scope: embedding fine-tuning (M5), generation metrics / LLM-judge
calibration (needed only once `/ask` exists in M2), Rust hot-path (stretch).

---

## Current state (what M1 builds on)

| Piece | State | File |
|---|---|---|
| Fixed-size chunker | Done (M0 baseline) | `packages/retrieval/src/cortex/retrieval/chunking.py` |
| `context_blurb` column | Exists, always NULL | `packages/storage/src/cortex/storage/models.py` (Chunk) |
| RRF fusion | **Implemented + unit-tested** | `packages/retrieval/src/cortex/retrieval/fusion.py` |
| Cross-encoder rerank | Stub (`NotImplementedError`) | `packages/retrieval/src/cortex/retrieval/rerank.py` |
| Recall@k / nDCG@k | Implemented; **MRR missing** | `packages/eval/src/cortex/eval/metrics.py` |
| Gate logic + thresholds | Implemented, advisory mode | `packages/eval/src/cortex/eval/gate.py` |
| BM25 / sparse search | Missing entirely | — |
| Golden set | Missing (gate has no real values) | — |
| `/v1/search` | Dense-only | `apps/api/src/cortex/api/search.py` |
| CI eval job | Runs `pytest -m eval`, `EVAL_GATE: advisory` | `.github/workflows/ci.yml`, `eval.yml` |

---

## Design decisions

### D1 — BM25 via Postgres full-text search
Per `docs/RETRIEVAL_AND_ML.md` §3 ("Postgres FTS or a dedicated index"), use
Postgres: a generated `tsvector` column on `chunks` with a GIN index, queried
with `websearch_to_tsquery` + `ts_rank_cd`, always tenant-filtered. No new
infrastructure, transactional with ingestion, good enough for exact-term/rare-
token recall (IDs, error codes, names). Caveat: `ts_rank_cd` is not literal
BM25 scoring — irrelevant here because RRF consumes *ranks*, not scores. Keep
the sparse retriever behind a small interface so a dedicated index (tantivy,
ParadeDB) can replace it later if eval demands.

### D2 — Contextual blurbs: template by default, LLM behind a flag
Blurbs are prepended before embedding (`blurb + "\n\n" + text`) and stored in
`chunks.context_blurb`. Two generators behind one interface:

- **Template (default):** deterministic blurb from metadata — source kind,
  artifact kind/external_id, position ("Part 2 of 5 of doc X from the sample
  connector"). Zero cost, no network, CI-safe.
- **LLM (env-gated, `CORTEX_BLURB_MODE=llm`):** Claude `claude-haiku-4-5`
  ($1/$5 per MTok; 50% less via the Batches API for offline backfills) with a
  short prompt situating the chunk in its artifact. Recomputed only when the
  chunk `content_hash` changes (column already supports this).

Eval will report template vs LLM blurbs so the lift is measured, not assumed.

### D3 — Source-aware chunking as a registry
`chunk(text, source_kind=...)` keeps its signature (callers don't change) but
dispatches to per-kind strategies per `docs/RETRIEVAL_AND_ML.md` §1:

- `doc`/`page`/`file`: heading-delimited markdown sections, recursive split of
  oversized sections (paragraphs → word-window fallback).
- `message` (Slack-like): thread / sliding window of turns.
- `email`: strip quoted history, then paragraph split.
- default: existing fixed word-window (unchanged behavior for unknown kinds).

The sample corpus (12 docs) must exercise at least the markdown and message
paths; extend `packages/connectors/src/cortex/connectors/sample.py` with
thread-shaped and email-shaped docs if it doesn't.

### D4 — Cross-encoder rerank behind the `ml` extra
Mirror the embedder pattern (`embedding.py`): default is a no-op passthrough
(identity over the fused order); `BAAI/bge-reranker-base` via
`sentence-transformers` `CrossEncoder` when the `ml` extra is installed and
`CORTEX_RERANKER=bge` is set. Lazy model load, batched scoring over the top-N
fused candidates (N=50 default) → top-k.

### D5 — Golden set labels must be stable across re-ingest
Chunk UUIDs are generated at ingest, so golden labels reference
`(artifact_external_id, chunk_ordinal)` and are resolved to live chunk ids at
eval time via Postgres. Consequence for ordering: **the chunking changes land
before the golden set is authored**, otherwise every label breaks when chunk
boundaries move. Golden set lives at `packages/eval/data/golden_retrieval.jsonl`
(query, relevant `[external_id, ordinal]` pairs, split: `dev` | `test`); the
`test` split is held out — never used for tuning, only for the headline number.

### D6 — Gate goes blocking only for retrieval metrics
`gate.py` already compares against `THRESHOLDS`. The eval runner feeds it real
`recall_at_10` / `ndcg_at_10`; faithfulness and citation-validity stay absent
from the metrics dict (the gate only checks metrics present) until M2. CI flips
`EVAL_GATE: blocking` in `ci.yml`'s eval job. The "deliberate regression fails
CI" criterion is proven by a pytest canary: run the harness with fusion+rerank
disabled (dense-only, degraded config) and assert the gate **fails** in
blocking mode — this keeps the proof in-repo and permanent.

---

## Workstreams & feature commits

Order matters: chunking → blurbs → re-seed → golden set → hybrid → rerank →
API → harness → gate. One commit per feature (repo convention, no co-author
trailers).

### 1. `feat(retrieval): source-aware chunking registry`
- `chunking.py`: strategy registry keyed by `source_kind` (D3); markdown
  heading splitter; thread/turn windower; email quote-stripper; fixed-window
  fallback. Pure functions, no I/O.
- `packages/connectors/.../sample.py`: ensure corpus covers markdown + thread +
  email shapes (extend the 12 docs if needed; keep deterministic).
- Tests: `tests/unit/test_chunking.py` extended per strategy (boundaries,
  oversize recursion, empty/degenerate input).

### 2. `feat(retrieval): contextual blurbs (template default, LLM behind flag)`
- New `packages/retrieval/src/cortex/retrieval/blurb.py`: `BlurbGenerator`
  protocol; `TemplateBlurb` (default); `LlmBlurb` using the `anthropic` SDK
  (`claude-haiku-4-5`), gated by `CORTEX_BLURB_MODE` env var, dependency under
  a new optional extra (e.g. `llm`).
- `apps/workers/src/cortex/workers/pipeline.py`: generate blurb per chunk,
  store in `context_blurb`, embed `blurb + text`; skip regeneration when
  `content_hash` unchanged (idempotency preserved).
- Tests: unit test template output; LLM path mocked.

### 3. `feat(storage): Postgres FTS index + tenant-filtered BM25 search`
- Migration `0003`: generated `tsvector` column on `chunks` (from
  `coalesce(context_blurb,'') || ' ' || text`), GIN index.
- `packages/storage/src/cortex/storage/`: `search_bm25(session, tenant_id,
  query, k, source_kinds)` returning ranked chunk ids (`websearch_to_tsquery`,
  `ts_rank_cd`, mandatory tenant filter — same posture as `qdrant.py`).
- Tests: integration test in `tests/integration/` — exact-token query (an ID
  string) found by BM25, tenant isolation asserted.

### 4. `feat(retrieval): hybrid retriever — dense + BM25 + RRF + rerank`
- New `packages/retrieval/src/cortex/retrieval/hybrid.py`: orchestrates dense
  (Qdrant) + sparse (Postgres) candidate lists → `reciprocal_rank_fusion` →
  reranker → top-k, with per-stage OTel spans (`search.dense`, `search.bm25`,
  `search.fuse`, `search.rerank`).
- `rerank.py`: replace stub per D4 (passthrough default, `bge-reranker-base`
  under `ml` extra).
- Tests: unit (fusion of disjoint/overlapping lists already covered; add
  rerank passthrough + mocked cross-encoder ordering).

### 5. `feat(api): hybrid /v1/search`
- `search.py`: route through the hybrid retriever; add optional
  `mode: "dense" | "hybrid"` request field (default `hybrid`) so eval can
  ablate; response shape unchanged.
- Tests: extend `tests/integration/test_search_e2e.py` — hybrid returns
  relevant chunks for seed queries; tenant isolation re-asserted through the
  new path; an exact-ID query that dense-only misses is found in hybrid mode.

### 6. `feat(eval): golden set + retrieval eval harness`
- `packages/eval/data/golden_retrieval.jsonl`: ≥ 40 labeled queries over the
  seed corpus (dev/test split per D5), hand-authored.
- `metrics.py`: add `mrr(ranked, relevant)`.
- New `packages/eval/src/cortex/eval/harness.py`: load golden set → resolve
  labels to chunk ids → run search (per mode) → compute Recall@{5,10,20},
  nDCG@{5,10,20}, MRR → emit `.eval-reports/report.{md,json}` with deltas vs
  previous run and per-source breakdown; feed headline metrics to
  `evaluate_gate`.
- `tests/eval/test_retrieval_gate.py`: replace placeholder with a real
  `-m eval` test that runs the harness against the live stack and asserts the
  gate result.

### 7. `ci(eval): flip the regression gate to blocking`
- `ci.yml` eval job: `EVAL_GATE: blocking`; keep nightly `eval.yml` advisory
  full-run + report artifact.
- Canary test (D6): degraded config (dense-only, no rerank) must produce
  `passed=False` in blocking mode — the in-repo proof that a deliberate
  regression fails CI.
- Tune thresholds honestly: if 0.85/0.70 isn't met, fix retrieval (blurbs,
  chunking, rerank N) — do not lower thresholds; they're the milestone gate.

### 8. `docs: mark M1 complete`
- README milestone table, CHANGELOG entry, note measured Recall@10 / nDCG@10
  in ROADMAP resume-bullet brackets.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hashing embedder (default, non-ML CI) too weak to hit 0.85/0.70 | Gate metrics are computed in CI with the deterministic stack; if the hashing embedder can't reach the bar even with hybrid+blurbs, run the gate against the `ml` extra (`bge-small`) in CI — that's the production config the threshold describes. Decide based on the first harness run. |
| Golden labels drift when chunking changes again | D5 stable keys + chunking lands first; re-author labels only on deliberate chunking changes. |
| Cross-encoder latency | Rerank only top-N=50 fused candidates; lazy load; passthrough default keeps non-ml environments fast. |
| LLM blurb cost/flakiness in CI | Template default; LLM path never runs in CI (env-gated, mocked in tests). |
| `ts_rank_cd` ≠ true BM25 | RRF uses ranks, not scores; sparse retriever behind an interface if a real BM25 index is ever needed. |

## Verification (milestone exit)

1. `just seed` re-ingests the corpus with source-aware chunks + blurbs.
2. Eval harness on the **test split**: Recall@10 ≥ 0.85, nDCG@10 ≥ 0.70.
3. CI green with `EVAL_GATE: blocking`; canary proves degraded config fails.
4. `POST /v1/search` (hybrid) returns relevant chunks for the 10 seed queries;
   exact-ID query demonstrates the BM25 win; traces show all four stages.
5. Cross-tenant leakage tests pass through both dense and BM25 paths.
