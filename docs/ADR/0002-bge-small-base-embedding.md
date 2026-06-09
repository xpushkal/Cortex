# ADR-0002: `bge-small-en-v1.5` as the base embedding model

- **Status:** Accepted
- **Date:** 2026-06-09

## Context
Retrieval quality rides on the embedding model, but so do latency and cost. We
need a base model that (a) hits the retrieval SLOs with hybrid + rerank, (b) is
cheap enough to fine-tune contrastively (M5), and (c) serves within the p95
budget. The serving target is p95 `/search` < 200 ms over a large index.

## Decision
Use **`bge-small-en-v1.5` (384-d)** as the base embedding model. Embed
`context_blurb + text`. Keep the model behind an interface so a fine-tuned variant
can be swapped in behind a flag (M5), and so we can move up to `bge-base` if eval
justifies the latency cost.

## Consequences
- **Easier:** 384-d vectors keep the Qdrant index small and ANN fast; cheap to
  fine-tune and to run on CPU (ONNX/quantized) when no GPU is available.
- **Harder:** a small model leaves quality on the table vs. larger encoders;
  contextual blurbs + cross-encoder rerank are doing real work to compensate.
- **Revisit when:** the eval harness shows `bge-base` (or the fine-tune) clears
  the latency budget with a meaningful Recall@10/nDCG@10 lift.

## Alternatives considered
- **`bge-base`/larger:** higher ceiling, but bigger vectors and slower serving;
  adopt only if eval earns it.
- **Hosted embedding API:** removes serving ops but adds per-call cost, a network
  hop in the hot path, and blocks the from-scratch fine-tuning that is an explicit
  ML-depth goal (M5).
