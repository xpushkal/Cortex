"""FastAPI application entrypoint.

Run locally with `just dev` (uvicorn --reload). Feature endpoints (/ask, /search,
/processes, /skills) land across M0-M6; only liveness/readiness exist today so the
serving skeleton is deployable and observable from day one.
"""

from __future__ import annotations

from fastapi import FastAPI

from cortex.api.config import get_settings
from cortex.api.processes import router as processes_router
from cortex.api.search import router as search_router
from cortex.obs import init_tracing

app = FastAPI(title="Cortex", version="0.0.0")
app.include_router(search_router)
app.include_router(processes_router)

# Auto-instrument HTTP spans when a collector endpoint is configured (no-op otherwise).
if init_tracing("cortex-api"):
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Returns ok regardless of downstream dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """Readiness probe. M0+ will check Postgres/Qdrant/Redis connectivity here."""
    settings = get_settings()
    return {"status": "ready", "env": settings.cortex_env}
