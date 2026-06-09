# Engineering Workflow — Cortex

How we build Cortex: environment, version control, the daily loop, and the gates
every change passes. Optimized for a **solo maintainer** shipping a real product —
automation-first, so the machine enforces the quality a second reviewer otherwise
would.

---

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 + all deps)
- Docker (local infra)
- [just](https://github.com/casey/just) (task runner — optional but recommended)
- `pre-commit` (installed as a dev dependency via uv)

## 2. First-time setup

```bash
uv sync --all-extras                     # create .venv, install everything
uv run pre-commit install \              # wire git hooks (pre-commit + commit-msg)
  --hook-type pre-commit --hook-type commit-msg
cp .env.example .env                     # fill in secrets locally (never commit .env)
just up                                  # start Postgres, Qdrant, Redis, OTel, Grafana
just migrate                             # alembic upgrade head
```

## 3. Daily loop

```bash
just dev          # run the API with autoreload (http://localhost:8000/healthz)
just test         # unit + integration with coverage
just lint         # ruff check + format check
just types        # mypy (strict)
just ci           # everything CI runs, locally — run before pushing
```

The task runner is the single source of truth for commands; CI calls the same
underlying tools (see `.github/workflows/ci.yml`).

## 4. Version control (trunk-based)

- **`main` is always releasable** and branch-protected: CI must be green and
  history must be linear. This applies even though the project is solo.
- **Short-lived branches** off `main`, named by Conventional-Commit type:
  `feat/…`, `fix/…`, `chore/…`, `docs/…`, `ci/…`, `test/…`, `refactor/…`.
- **Open a PR even when solo.** The PR is the gate: it runs CI, and the
  Definition of Done (§6) must hold before merge. **Squash-merge** so `main` stays
  one commit per change.
- **Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).**
  This is enforced by the `commitizen` commit-msg hook and feeds `CHANGELOG.md`
  and SemVer. Do **not** add co-authors that didn't write the change.

### Branch protection (configure once on GitHub)
- Require status checks: `lint + types`, `unit + integration`, `eval gate (advisory)`.
- Require linear history; disallow force-push to `main`.

## 5. Releases

- Tag `vX.Y.Z` on `main` → `release.yml` builds and pushes the API + worker images
  to GHCR.
- Additionally tag a milestone (`m0`, `m1`, …) when its ROADMAP **done-when** gate
  passes, so milestones are pinpointable in history.
- SemVer: pre-1.0 while M0–M6 are in flight; breaking API changes bump the minor.

## 6. Definition of Done

A change is done when all of the following hold:

- Conventional Commit title; `just ci` green (ruff + mypy + tests).
- Tests added/updated (unit; integration if it touches I/O).
- No secrets committed; `.env.example` updated if new config was added.
- Docs/CHANGELOG updated if behavior or interfaces changed.
- Tenant isolation preserved (no retrieval path without a tenant filter).
- Every new knowledge/process artifact carries citations.

## 7. Architectural decisions

Non-trivial or hard-to-reverse decisions are recorded as ADRs in `docs/ADR/`
(template + the first two are committed). Open questions from the PRD live there
once decided.

## 8. Secrets

Never commit secrets. `.env` is git-ignored; `.env.example` documents the required
variables. `gitleaks` runs in pre-commit and CI. See `SECURITY.md`.
