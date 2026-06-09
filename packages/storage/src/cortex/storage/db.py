"""Async engine + session factory.

The DSN comes from the caller (or POSTGRES_DSN) so this package stays free of app
config. Engines are cached per-DSN since they own a connection pool.
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DSN = "postgresql+asyncpg://cortex:cortex@localhost:5433/cortex"


def _dsn(dsn: str | None) -> str:
    return dsn or os.environ.get("POSTGRES_DSN", DEFAULT_DSN)


@lru_cache(maxsize=8)
def get_engine(dsn: str | None = None) -> AsyncEngine:
    """Return a pooled async engine for the DSN (cached)."""
    return create_async_engine(_dsn(dsn), pool_pre_ping=True)


def get_sessionmaker(dsn: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the engine for the DSN."""
    return async_sessionmaker(get_engine(dsn), expire_on_commit=False)
