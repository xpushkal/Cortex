"""Shared FastAPI dependencies.

Tenant scoping: every knowledge endpoint resolves the tenant and runs its DB
session bound to that tenant. Two modes (docs/API.md, ARCHITECTURE.md §6):

  - Default (dev/tests): the tenant comes from the `X-Tenant` header.
  - `cortex_auth_required`: the tenant is derived from the per-tenant bearer
    token; if `X-Tenant` is also sent it must match (else 403).

Either way the session sets the `app.current_tenant` GUC the RLS policy reads;
with `cortex_rls_enforce` it additionally runs under the least-privilege
`cortex_app` role so RLS is the active guard, not just the app-layer filter.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.api.auth import resolve_token_tenant
from cortex.api.config import get_settings
from cortex.storage import app_role_dsn, get_sessionmaker, resolve_tenant, set_tenant


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token else None


async def tenant_id(
    x_tenant: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Resolve the request's tenant, enforcing bearer auth when configured."""
    if not get_settings().cortex_auth_required:
        if not x_tenant:
            raise HTTPException(status_code=400, detail="X-Tenant header is required")
        return resolve_tenant(x_tenant)

    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    tenant = await resolve_token_tenant(token)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked token")
    if x_tenant and resolve_tenant(x_tenant) != tenant:
        raise HTTPException(status_code=403, detail="X-Tenant does not match the token's tenant")
    return tenant


async def db_session(
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped async DB session: sets the RLS tenant GUC for the request.

    Runs under the least-privilege `cortex_app` role when `cortex_rls_enforce` is
    set, so RLS actively filters; otherwise the admin role (with the GUC still set).
    """
    dsn = app_role_dsn() if get_settings().cortex_rls_enforce else None
    async with get_sessionmaker(dsn)() as session:
        await set_tenant(session, tenant)
        yield session
