# Cortex ingestion worker image. Multi-stage uv build; non-root runtime.
# Built from the repo root: `docker build -f apps/workers/Dockerfile .`
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
RUN useradd --create-home --uid 10001 cortex
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER cortex
# WorkerSettings functions/queues are wired in M0.
CMD ["arq", "cortex.workers.main.WorkerSettings"]
