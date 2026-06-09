"""Shared FastAPI dependencies.

Tenant scoping: every knowledge endpoint resolves the tenant from the `X-Tenant`
header. A request without it is rejected — there is no un-scoped query path
(docs/ARCHITECTURE.md §6). M0 trusts the header; bearer-token auth binding the
token's tenant to X-Tenant (docs/API.md) lands with auth in a later milestone.
"""

from __future__ import annotations

import uuid

from fastapi import Header, HTTPException

from cortex.storage import resolve_tenant


def tenant_id(x_tenant: str | None = Header(default=None)) -> uuid.UUID:
    if not x_tenant:
        raise HTTPException(status_code=400, detail="X-Tenant header is required")
    return resolve_tenant(x_tenant)
