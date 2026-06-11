"""Async engine + session factory.

The DSN comes from the caller (or POSTGRES_DSN) so this package stays free of app
config. Engines are cached per-DSN since they own a connection pool.
"""

from __future__ import annotations

import os
import uuid
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DSN = "postgresql+asyncpg://cortex:cortex@localhost:5433/cortex"
# The least-privilege role RLS is enforced for (migration 0006).
APP_ROLE = "cortex_app"


def _dsn(dsn: str | None) -> str:
    return dsn or os.environ.get("POSTGRES_DSN", DEFAULT_DSN)


@lru_cache(maxsize=8)
def get_engine(dsn: str | None = None) -> AsyncEngine:
    """Return a pooled async engine for the DSN (cached)."""
    return create_async_engine(_dsn(dsn), pool_pre_ping=True)


def get_sessionmaker(dsn: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the engine for the DSN."""
    return async_sessionmaker(get_engine(dsn), expire_on_commit=False)


def app_role_dsn(dsn: str | None = None) -> str:
    """Derive the least-privilege `cortex_app` DSN from the admin DSN.

    Production runs the app under this role so Postgres RLS (which superusers
    bypass) is actually enforced. Swaps the userinfo `cortex:cortex` for
    `cortex_app:cortex_app`; other DSNs should set CORTEX_APP_DSN explicitly.
    """
    env = os.environ.get("CORTEX_APP_DSN")
    if env:
        return env
    return _dsn(dsn).replace("//cortex:cortex@", f"//{APP_ROLE}:{APP_ROLE}@")


async def set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set the per-transaction `app.current_tenant` GUC the RLS policy reads."""
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(tenant_id)},
    )
