# Cortex serving plane image. Multi-stage uv build; non-root runtime.
# Built from the repo root: `docker build -f apps/api/Dockerfile .`
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
COPY . .
# Install the locked, production (no-dev) dependency set into /app/.venv.
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
RUN useradd --create-home --uid 10001 cortex
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER cortex
EXPOSE 8000
CMD ["uvicorn", "cortex.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
