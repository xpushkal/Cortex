# Changelog

All notable changes to Cortex are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are
derived from [Conventional Commits](https://www.conventionalcommits.org/) on
`main` (see `docs/ENGINEERING-WORKFLOW.md`).

## [Unreleased]

### Added
- Engineering scaffolding: uv workspace, repo skeleton (`apps/*`, `packages/*`),
  ruff + mypy + pytest tooling, pre-commit gates.
- Local infra via `infra/docker-compose.yml` (Postgres, Qdrant, Redis, OTel,
  Prometheus, Grafana) and Alembic migration skeleton.
- CI/CD: `ci`, `eval`, and `release` GitHub Actions workflows; the eval quality
  gate is wired in **advisory** mode pending a real golden set.
- Engineering docs: `CONTRIBUTING.md`, `SECURITY.md`,
  `docs/ENGINEERING-WORKFLOW.md`, `docs/TEST-STRATEGY.md`, and the first two ADRs.

[Unreleased]: https://github.com/xpushkal/Cortex/commits/main
