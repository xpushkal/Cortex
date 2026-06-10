# Changelog

All notable changes to Cortex are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are
derived from [Conventional Commits](https://www.conventionalcommits.org/) on
`main` (see `docs/ENGINEERING-WORKFLOW.md`).

## [Unreleased]

### Added — M2 (knowledge structuring)
- Knowledge graph (migration `0004`): tenant-scoped `entities`,
  `entity_mentions` (provenance), and `relations` (subject/predicate/object with
  `source_chunk_id` + temporal validity), plus the process registry
  (`processes` -> `process_versions` -> `process_steps`, with `citations`).
- Entity + relation extraction with provenance: `HeuristicExtractor` (typed
  org-entity lexicon + relation-cue patterns) by default; `LlmExtractor`
  (`claude-opus-4-8` structured outputs) behind `CORTEX_EXTRACTOR=llm`.
- Entity resolution (alias merging): normalized-key + seed synonyms, conservative
  (never over-merges distinct roles); optional injectable similarity hook.
- Process extraction: cluster -> synthesize -> Pydantic citation invariant ->
  **faithfulness gate** (lexical entailment; drops steps the cited chunk doesn't
  support) -> emit only fully-cited, faithful processes. Version-aware persistence
  (new process active@v1; changed body -> new draft version, no silent overwrite).
- Extraction wired into ingestion (graph + cited processes per artifact, in the
  ingest transaction; idempotent on re-seed) and exposed via `GET /v1/processes`
  (+ detail + versions) and process-grounded `POST /v1/ask` (extractive default;
  `CORTEX_ASK=llm` for prose). Every answer carries citations + freshness.
- Process eval: 11-process golden set, step precision/recall, actor-resolution
  accuracy, and a **blocking `process_citation_validity` CI gate** (1.00 —
  every shipped step validly cited) with a dangling-citation canary. Advisory
  on the deterministic path: recall 0.89, precision 0.78, actor accuracy 0.88.

### Added — M1 (retrieval quality)
- Source-aware chunking registry: markdown heading sections (page/doc/pr),
  thread turn-windows (message), quoted-history stripping (email), with the M0
  fixed window as fallback; four new deterministic sample-corpus docs exercise
  each shape.
- Contextual blurbs embedded with each chunk (`blurb + text`): deterministic
  template by default, `claude-haiku-4-5` via the new `llm` extra behind
  `CORTEX_BLURB_MODE=llm`.
- BM25 sparse retrieval via Postgres FTS (migration `0003`: generated tsvector
  + GIN index) with the same mandatory tenant filter as the vector store.
- Hybrid retrieval: dense + BM25 → Reciprocal Rank Fusion → cross-encoder
  rerank (`bge-reranker-base` under the `ml` extra; passthrough default), with
  per-stage tracing. `POST /v1/search` is hybrid by default (`mode=dense` for
  ablation).
- Eval harness: 42-query hand-authored golden set (stable
  `(external_id, ordinal)` labels; held-out test split), Recall@k / nDCG@k /
  MRR, markdown + JSON reports with run-over-run deltas.
- **CI eval gate now blocking** — Recall@10 0.952 / nDCG@10 0.908 on the
  held-out split — plus a canary test proving a deliberately degraded
  retriever fails the gate.

### Added — M0 (skeleton vertical slice)
- `cortex-storage`: async SQLAlchemy models (Source/Artifact/Chunk, tenant-scoped),
  Alembic migration `0002`, and a Qdrant store with **mandatory tenant-filtered
  search**.
- `cortex-obs`: shared OpenTelemetry tracing; Tempo added to the stack so traces
  flow API/worker → collector → Tempo → Grafana.
- Sample connector (deterministic 12-doc corpus), fixed-size chunker, and a
  pluggable embedder (hashing default; `bge-small` behind the `ml` extra).
- Ingestion pipeline (`cortex.workers.ingest`): connector → hash → chunk → embed →
  Postgres + Qdrant, idempotent on `content_hash`. `just seed` runs it.
- `POST /v1/search`: dense, tenant-scoped retrieval (X-Tenant required).
- Integration tests: seed-query retrieval, **cross-tenant leakage guard**, and
  ingestion idempotency — all live against Postgres + Qdrant.

### Added — scaffolding
- Engineering scaffolding: uv workspace, repo skeleton (`apps/*`, `packages/*`),
  ruff + mypy + pytest tooling, pre-commit gates.
- Local infra via `infra/docker-compose.yml` (Postgres, Qdrant, Redis, OTel,
  Prometheus, Grafana) and Alembic migration skeleton.
- CI/CD: `ci`, `eval`, and `release` GitHub Actions workflows; the eval quality
  gate is wired in **advisory** mode pending a real golden set.
- Engineering docs: `CONTRIBUTING.md`, `SECURITY.md`,
  `docs/ENGINEERING-WORKFLOW.md`, `docs/TEST-STRATEGY.md`, and the first two ADRs.

[Unreleased]: https://github.com/xpushkal/Cortex/commits/main
