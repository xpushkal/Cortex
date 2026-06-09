# Changelog

All notable changes to Cortex are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are
derived from [Conventional Commits](https://www.conventionalcommits.org/) on
`main` (see `docs/ENGINEERING-WORKFLOW.md`).

## [Unreleased]

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
