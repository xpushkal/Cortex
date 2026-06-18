"""Application settings, loaded from the environment (see .env.example)."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    cortex_env: str = "local"
    log_level: str = "INFO"

    postgres_dsn: str = "postgresql+asyncpg://cortex:cortex@localhost:5433/cortex"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"

    eval_gate: Literal["advisory", "blocking"] = "advisory"

    llm_provider: str = "anthropic"

    # When true, POST /v1/ingest/events enqueues to the arq worker (non-blocking)
    # instead of ingesting inline. Off by default so tests/dev keep read-after-write.
    cortex_worker_async: bool = False

    # Auth: when true, endpoints require a per-tenant bearer token and the tenant
    # is derived from it (X-Tenant, if sent, must match). Off by default so dev/tests
    # keep using X-Tenant directly. Production sets cortex_auth_required=true.
    cortex_auth_required: bool = False

    # When true, request DB sessions run under the least-privilege cortex_app role
    # so Postgres RLS is the active guard (not just the app-layer filter). Off by
    # default; the tenant GUC is set on the session regardless.
    cortex_rls_enforce: bool = False

    # Per-tenant ingress rate limiting (docs/API.md). Opt-in so shared test/dev
    # runs aren't throttled; production sets cortex_ratelimit=true.
    cortex_ratelimit: bool = False
    # read bucket: /search, /processes — 60 req / 10 s.
    ratelimit_read_capacity: int = 60
    ratelimit_read_refill_per_second: float = 6.0
    # heavy bucket: /ask (LLM cost) — 10 req / 10 s.
    ratelimit_heavy_capacity: int = 10
    ratelimit_heavy_refill_per_second: float = 1.0


def get_settings() -> Settings:
    """Construct settings. Wrap in lru_cache once hot paths read it frequently."""
    return Settings()
