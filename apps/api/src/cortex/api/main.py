"""FastAPI application entrypoint.

Run locally with `just dev` (uvicorn --reload). Feature endpoints (/ask, /search,
/processes, /skills) land across M0-M6; only liveness/readiness exist today so the
serving skeleton is deployable and observable from day one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cortex.api.ask import router as ask_router
from cortex.api.config import get_settings
from cortex.api.ingest import router as ingest_router
from cortex.api.processes import router as processes_router
from cortex.api.search import router as search_router
from cortex.api.skills import router as skills_router
from cortex.obs import init_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open a shared arq pool when async ingestion is enabled; close on shutdown.

    Inline/test mode never touches Redis — the in-process test client must run
    without a Redis server.
    """
    app.state.arq_pool = None
    if get_settings().cortex_worker_async:
        from cortex.workers.queue import get_arq_pool

        app.state.arq_pool = await get_arq_pool()
    try:
        yield
    finally:
        if app.state.arq_pool is not None:
            await app.state.arq_pool.close()


app = FastAPI(title="Cortex", version="0.0.0", lifespan=lifespan)
app.include_router(search_router)
app.include_router(processes_router)
app.include_router(ask_router)
app.include_router(ingest_router)
app.include_router(skills_router)

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
