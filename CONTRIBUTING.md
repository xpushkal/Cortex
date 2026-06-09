# Contributing to Cortex

Thanks for working on Cortex. This is the short version; the full workflow lives
in [`docs/ENGINEERING-WORKFLOW.md`](docs/ENGINEERING-WORKFLOW.md) and the test
approach in [`docs/TEST-STRATEGY.md`](docs/TEST-STRATEGY.md).

## Setup

```bash
uv sync --all-extras
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
cp .env.example .env
just up && just migrate
```

## Making a change

1. Branch off `main`: `feat/…`, `fix/…`, `chore/…`, `docs/…`, `test/…`, `ci/…`.
2. Write the change **and its tests** (see the test tiers).
3. `just ci` must pass locally (ruff + mypy + tests).
4. Commit with a [Conventional Commit](https://www.conventionalcommits.org/)
   message (enforced by a git hook). Do not add co-authors who didn't write it.
5. Open a PR; fill in the Definition-of-Done checklist. Squash-merge when green.

## Ground rules baked into the product

- **Everything is cited.** No knowledge/process artifact ships without citations.
- **Tenant isolation is non-negotiable.** No retrieval path may run without a
  tenant filter; the cross-tenant leakage test must stay green.
- **Incremental by default.** Re-ingest/recompute only what changed.
- **Never serve stale knowledge as current.** Respect freshness state.

## Reporting bugs / proposing work

Use the issue templates. Tie work to a ROADMAP milestone and give a concrete
"done-when" where you can.
