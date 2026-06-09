"""FastAPI application entrypoint.

Run locally with `just dev` (uvicorn --reload). Feature endpoints (/ask, /search,
/processes, /skills) land across M0-M6; only liveness/readiness exist today so the
serving skeleton is deployable and observable from day one.
"""

from __future__ import annotations

from fastapi import FastAPI

from cortex.api.config import get_settings
from cortex.api.search import router as search_router

app = FastAPI(title="Cortex", version="0.0.0")
app.include_router(search_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Returns ok regardless of downstream dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """Readiness probe. M0+ will check Postgres/Qdrant/Redis connectivity here."""
    settings = get_settings()
    return {"status": "ready", "env": settings.cortex_env}
