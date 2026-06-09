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


def get_settings() -> Settings:
    """Construct settings. Wrap in lru_cache once hot paths read it frequently."""
    return Settings()
