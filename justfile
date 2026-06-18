# Cortex task runner. Install just: https://github.com/casey/just
# Run `just` with no args to list recipes.

set dotenv-load := true

default:
    @just --list

# Install / sync all workspace deps into .venv (pinned by uv.lock).
sync:
    uv sync --all-extras

# Bring local infra up (Postgres, Qdrant, Redis, OTel, Prometheus, Grafana).
up:
    docker compose -f infra/docker-compose.yml up -d

# Tear infra down (keep volumes).
down:
    docker compose -f infra/docker-compose.yml down

# Tear infra down AND wipe volumes (fresh state).
nuke:
    docker compose -f infra/docker-compose.yml down -v

# Apply database migrations.
migrate:
    uv run alembic upgrade head

# Seed the deterministic sample corpus (M0+).
seed:
    uv run python -m cortex.workers.ingest --source sample --tenant demo

# Expire knowledge past its TTL (M3 freshness sweep; run on a schedule).
sweep:
    uv run python -m cortex.workers.freshness_sweep

# Load-test /search against a running API (M4). Override flags as needed.
loadtest *ARGS:
    uv run python scripts/load_test.py {{ARGS}}

# Fine-tune domain embeddings (M5; needs the `ml` extra: uv sync --extra ml).
train-embeddings *ARGS:
    uv run python scripts/train_embeddings.py {{ARGS}}

# Run the API with autoreload.
dev:
    uv run uvicorn cortex.api.main:app --reload --port 8000

# Run an arq worker on one priority lane (default realtime). Run one per lane.
# Needs Redis + CORTEX_WORKER_ASYNC=true on the API.
worker queue="cortex:realtime":
    CORTEX_WORKER_QUEUE={{queue}} uv run arq cortex.workers.main.WorkerSettings

# Inspect or replay the ingestion dead-letter queue (`just dlq list` | `just dlq requeue`).
dlq *ARGS:
    uv run python -m cortex.workers.deadletter {{ARGS}}

# Lint + format check.
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint + format.
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Static type check.
types:
    uv run mypy

# Unit + integration tests with coverage.
test:
    uv run pytest --cov --cov-report=term-missing

# Fast unit-only tests (no live services).
test-unit:
    uv run pytest -m "not integration and not eval and not load"

# Run the eval harness / quality gate.
eval:
    uv run pytest -m eval

# Dependency vulnerability audit.
audit:
    uv run pip-audit

# Everything CI runs, locally.
ci: lint types test
