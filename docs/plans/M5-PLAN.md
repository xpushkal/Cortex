# M5 Plan — ML Depth (Embedding Fine-Tune)

**Status:** Complete (2026-06-11) — synthetic queries + round-trip filter, hard-negative mining, A/B acceptance gate (≥0.05 R@10 / ≥0.03 nDCG@10), and the fine-tuned embedder swapped into serving behind CORTEX_EMBEDDER=finetuned. Pipeline + gate + swap CI-tested; the training run + headline deltas reproduced via scripts/train_embeddings.py (ml extra), not CI-gated.
**Branch:** `M5`
**Roadmap gate (done-when):** fine-tuned embeddings beat base `bge-small` by
**≥ 5% Recall@10 and ≥ 0.03 nDCG@10** on the held-out golden set, and the model
is **swapped into serving behind a flag**.

The from-first-principles ML proof: synthetic query generation + hard-negative
mining → contrastive fine-tune of BGE (`MultipleNegativesRankingLoss`) → A/B vs
base on the held-out set → ship only if it clears the bar, behind a flag.

---

## The honesty split (the central decision)

The done-when has two halves with different verifiability in a hermetic dev/CI
environment — the M2/M3/M4 stance:

- **Serving swap behind a flag → DELIVERED + CI-tested.** A `FineTunedEmbedder`
  selectable via `CORTEX_EMBEDDER=finetuned` (+ a model path) slots into the
  existing `Embedder` interface; the whole ingest/search path runs on it. This
  half is fully built and tested.
- **The ≥ 5% / ≥ 0.03 *result* → REPRODUCIBLE, not CI-gated.** A real contrastive
  fine-tune needs the heavy `ml` extra (sentence-transformers + torch), a model
  download, and compute — none of which exist in hermetic CI, and the training
  is non-deterministic. So M5 ships the **full pipeline** (synthetic queries,
  hard-negative mining, training-data assembly, the A/B comparison + acceptance
  gate, the serving swap) — all deterministic and unit/integration-tested — plus
  a **real, runnable `scripts/train_embeddings.py`** that runs mine → train →
  eval → report. The headline deltas are produced by running that script with
  the `ml` extra on real compute (documented with methodology), and the
  acceptance gate (`Δrecall@10 ≥ 0.05`, `Δndcg@10 ≥ 0.03`) is encoded in-repo and
  tested — never a faked pass.

---

## Scope (from ROADMAP.md §M5 / RETRIEVAL_AND_ML.md §2)

1. Synthetic query generation (round-trip filtered).
2. Hard-negative mining + training-data assembly.
3. Contrastive fine-tune of BGE (`MultipleNegativesRankingLoss`).
4. A/B vs base on the held-out golden set; acceptance gate; report deltas.
5. Swap the fine-tuned model into serving behind a flag.

Out of scope: learned fusion weights (stretch), the Rust hot-path (stretch),
ONNX/quantized serving (noted; the flag accepts any sentence-transformers path).

---

## Current state (what M5 builds on)

| Piece | State | File |
|---|---|---|
| `Embedder` interface; `HashingEmbedder` (default), `BGEEmbedder` (`ml`) | Done (M0) | `packages/retrieval/.../embedding.py` |
| Retrieval golden set (42 queries, dev/test split) | Done (M1) | `packages/eval/.../data/golden_retrieval.jsonl` |
| Retrieval eval harness (Recall@k / nDCG@k / MRR) | Done (M1) | `packages/eval/.../harness.py` |
| `scripts/train_embeddings.py` | Stub (`NotImplementedError`) | `scripts/train_embeddings.py` |
| `ml` extra (sentence-transformers, torch) | Declared | `packages/retrieval/pyproject.toml` |

---

## Design decisions

### D1 — Synthetic queries: deterministic template default, LLM behind a flag
`generate_synthetic_queries(chunks)` emits `(query, chunk_id)` pairs to augment
the golden `(query → relevant chunk)` set. The **template** generator
(deterministic: salient-term keyword query from the chunk) runs in CI; the
**LLM** generator (`claude`, the `llm` extra) writes natural questions. Both are
**round-trip filtered** — a synthetic query is kept only if retrieving over the
corpus with the base embedder returns its source chunk in the top-k (drops
ambiguous/leaky queries). The filter is the same `Embedder` interface, so it's
deterministic with `HashingEmbedder` in tests.

### D2 — Hard-negative mining over the base retriever
`mine_hard_negatives(queries, positives, corpus, embedder, *, k, cap_per_query)`
runs the base retriever per query and takes the highest-ranked chunks that are
**not** labeled relevant as hard negatives (capped). Pure over embeddings →
deterministic and tested with `HashingEmbedder`. `build_training_examples`
assembles `(anchor=query, positive=pos_text, negatives=[neg_texts])` triples in
the shape `MultipleNegativesRankingLoss` consumes, serialized to JSONL the
training script reads.

### D3 — A/B acceptance gate in eval
`ab_compare(base_metrics, finetuned_metrics) -> ABReport` computes per-metric
deltas and `passed = Δrecall@10 ≥ 0.05 AND Δndcg@10 ≥ 0.03` (the done-when bar;
"5%" read as +0.05 absolute Recall@10). Pure + unit-tested. The harness runs the
**held-out test split** for both base and fine-tuned and feeds this gate.

### D4 — Fine-tuned embedder behind a flag (the serving swap)
`FineTunedEmbedder(model_path)` loads a fine-tuned sentence-transformers model
(the `ml` extra), exposing the same `embed()`; selected via
`CORTEX_EMBEDDER=finetuned` + `CORTEX_EMBEDDER_MODEL=<path>`. `get_embedder`
gains the `finetuned` branch. Ingestion/search are unchanged — they already take
the configured embedder. Tested via the factory + an injected fake model (the
real load is `ml`-gated).

### D5 — `train_embeddings.py` is real and runnable
Orchestrates: load golden (dev split) → synthetic queries (round-trip filtered)
→ mine hard negatives → assemble training data → fine-tune base bge-small with
`MultipleNegativesRankingLoss` → eval base vs fine-tuned on the **test** split →
A/B gate → write `.embeddings-report/`. The data-prep, eval, and gate are
importable and tested; the `.fit()` call is `ml`-gated and isolated. The
script **refuses to ship** a model that fails the gate (exit non-zero), matching
"or it is not shipped."

---

## Workstreams & feature commits

Order: synthetic queries → mining + assembly → A/B gate → serving swap → train
script → docs. One commit per feature (repo convention, no co-author trailers).

### 1. `feat(retrieval): synthetic query generation (template default, LLM flag)`
- `finetune.py`: `QueryGenerator` protocol; `TemplateQueryGenerator` (salient
  keyword query); `LlmQueryGenerator` (`claude`, `llm` extra, injectable);
  `generate_synthetic_queries` + `filter_round_trip`. Unit tests (template +
  round-trip + injected LLM client).

### 2. `feat(retrieval): hard-negative mining + training-data assembly`
- `mine_hard_negatives` (base retriever, cap per query, excludes positives);
  `build_training_examples` → triples + JSONL (de)serialization. Unit tests with
  `HashingEmbedder` (deterministic ranks).

### 3. `feat(eval): A/B embedding comparison + acceptance gate`
- `ab_compare` / `ABReport` (deltas + `passed`); `emit_ab_report`. Unit tests
  for the threshold logic (pass/fail edges).

### 4. `feat(retrieval): fine-tuned embedder serving swap (flag)`
- `FineTunedEmbedder` + `get_embedder` `finetuned` branch (env `CORTEX_EMBEDDER`,
  `CORTEX_EMBEDDER_MODEL`). Unit tests (factory + fake model).

### 5. `feat(ml): train_embeddings.py — mine→train→eval→report`
- Real orchestration using the above; `.fit()` `ml`-gated; A/B gate decides ship.
  `just train-embeddings`. Importable helpers tested; full run documented.

### 6. `docs: mark M5 complete`
- README, CHANGELOG, ROADMAP resume bullet, plan status; honestly record the
  swap (delivered) vs the headline deltas (reproducible via the script).

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Real fine-tune can't run in hermetic CI | The honesty split: pipeline + gate + swap are built/tested; training is a runnable script, the result documented — never a faked pass. |
| Tiny synthetic corpus won't actually clear ≥5%/≥0.03 | The gate logic is correct and tested; the script reports the real delta and refuses to ship below the bar. Clearing it needs real data/compute (documented). |
| LLM query gen flaky/cost in CI | Template default; LLM behind `CORTEX_QUERYGEN=llm`, mocked in tests, never in CI. |
| Heavy `ml` deps on the hot path | Fine-tuned/BGE embedders lazy-import sentence-transformers; default stays `hashing`. |

## Verification (milestone exit)

1. Synthetic query generation + round-trip filter, hard-negative mining, and
   training-data assembly are deterministic and tested (HashingEmbedder).
2. A/B acceptance gate encodes ≥5% Recall@10 / ≥0.03 nDCG@10 and is unit-tested
   at the pass/fail edges.
3. `CORTEX_EMBEDDER=finetuned` swaps the model into serving behind a flag
   (tested); ingest/search unchanged.
4. `scripts/train_embeddings.py` runs the mine→train→eval→report pipeline and
   refuses to ship a model that fails the gate; full fine-tune reproduction
   documented (the headline deltas need the `ml` extra + compute, not CI).
5. Full suite green with `EVAL_GATE=blocking`.
