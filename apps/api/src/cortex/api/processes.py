"""`/v1/processes` — list and inspect process objects (docs/API.md).

Tenant-scoped reads over the process registry: a summary list (with status/name
filters), the full canonical body of a process's current version, and its
version history. Write paths (review/approve) land with the freshness loop (M3).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.api.deps import db_session, tenant_id
from cortex.api.ratelimit import rate_limit
from cortex.knowledge import (
    ProcessSummary,
    get_process_body,
    get_process_versions,
    list_processes,
    review_process,
)

router = APIRouter()


class ReviewRequest(BaseModel):
    action: str  # approve | reject
    reviewer: str | None = None


class ProcessListResponse(BaseModel):
    processes: list[ProcessSummary]
    next_cursor: str | None = None


@router.get(
    "/v1/processes",
    response_model=ProcessListResponse,
    dependencies=[Depends(rate_limit("read"))],
)
async def list_processes_endpoint(
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
    status: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> ProcessListResponse:
    processes = await list_processes(session, tenant_id=tenant, status=status, q=q)
    return ProcessListResponse(processes=processes)


@router.get("/v1/processes/{process_id}")
async def get_process_endpoint(
    process_id: uuid.UUID,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    body = await get_process_body(session, tenant_id=tenant, process_id=process_id)
    if body is None:
        raise HTTPException(status_code=404, detail="process not found")
    return body


@router.get("/v1/processes/{process_id}/versions")
async def get_process_versions_endpoint(
    process_id: uuid.UUID,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    versions = await get_process_versions(session, tenant_id=tenant, process_id=process_id)
    if not versions:
        raise HTTPException(status_code=404, detail="process not found")
    return {"versions": versions}


@router.post("/v1/processes/{process_id}/review")
async def review_process_endpoint(
    process_id: uuid.UUID,
    req: ReviewRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    """Human review: `approve` promotes a draft to active + fresh; `reject`
    deprecates it (docs/API.md). Closes the M3 staleness loop."""
    if req.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be approve or reject")
    ok = await review_process(session, tenant_id=tenant, process_id=process_id, action=req.action)
    if not ok:
        raise HTTPException(status_code=404, detail="process not found")
    await session.commit()
    return {"id": str(process_id), "action": req.action}
