"""Source management — connect, list, sync, disconnect (docs/API.md).

A source is a `(tenant, kind)` connection with optional config. `sync` pulls the
connector's history (inline, or enqueued to the backfill lane when async is on);
`documents` pushes content directly (the file-upload path); `DELETE` disconnects
and purges the source's chunks/vectors. External OAuth connectors land as their
adapters do — the plane here is connector-agnostic.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.api.deps import db_session, tenant_id
from cortex.api.ratelimit import rate_limit
from cortex.connectors import SYNCABLE_KINDS, build_connector
from cortex.obs import get_tracer
from cortex.storage import Source, delete_source_points, get_qdrant
from cortex.workers.ingest import ingest_source
from cortex.workers.queue import enqueue_backfill, enqueue_ingest_event, worker_async_enabled

router = APIRouter()
_tracer = get_tracer(__name__)
_admin = Depends(rate_limit("admin"))


class CreateSourceRequest(BaseModel):
    kind: str = Field(min_length=1)  # sample | github | file | slack | ...
    config: dict[str, Any] = Field(default_factory=dict)


class SourceInfo(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    created_at: datetime


class SourceListResponse(BaseModel):
    sources: list[SourceInfo]


class UploadDocumentRequest(BaseModel):
    external_id: str = Field(min_length=1)
    kind: str = "doc"  # message | email | page | pr | issue | doc
    content: str = Field(min_length=1)


async def _get_source(session: AsyncSession, tenant: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = (
        await session.execute(
            select(Source).where(Source.tenant_id == tenant, Source.id == source_id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.post(
    "/v1/sources",
    response_model=SourceInfo,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def create_source(
    req: CreateSourceRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SourceInfo:
    # Idempotent on (tenant, kind): connecting an existing kind returns it.
    await session.execute(
        pg_insert(Source)
        .values(tenant_id=tenant, kind=req.kind, config=req.config)
        .on_conflict_do_nothing(index_elements=["tenant_id", "kind"])
    )
    await session.commit()
    source = (
        await session.execute(
            select(Source).where(Source.tenant_id == tenant, Source.kind == req.kind)
        )
    ).scalar_one()
    return SourceInfo(
        id=source.id, kind=source.kind, status=source.status, created_at=source.created_at
    )


@router.get("/v1/sources", response_model=SourceListResponse, dependencies=[_admin])
async def list_sources(
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SourceListResponse:
    rows = (
        (
            await session.execute(
                select(Source).where(Source.tenant_id == tenant).order_by(Source.created_at)
            )
        )
        .scalars()
        .all()
    )
    return SourceListResponse(
        sources=[
            SourceInfo(id=r.id, kind=r.kind, status=r.status, created_at=r.created_at) for r in rows
        ]
    )


@router.post("/v1/sources/{source_id}/sync", dependencies=[_admin])
async def sync_source(
    source_id: uuid.UUID,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    """Pull the source's history. Enqueued to the backfill lane when async is on,
    else ingested inline. Unsupported kinds (e.g. file) return 422."""
    source = await _get_source(session, tenant, source_id)
    if source.kind not in SYNCABLE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind {source.kind!r} has no backfill; push content via /documents",
        )
    try:
        # ValueError: missing/invalid config. RuntimeError: missing credential
        # (e.g. NOTION_TOKEN). Both are a 422 ("fix the source"), not a 500.
        connector = build_connector(source.kind, source.config)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with _tracer.start_as_current_span("sources.sync") as span:
        span.set_attribute("cortex.tenant_id", str(tenant))
        span.set_attribute("cortex.source_kind", source.kind)
        if worker_async_enabled():
            n = await enqueue_backfill(connector, tenant_id=tenant)
            return {"id": str(source_id), "status": "queued", "enqueued": n}
        stats = await ingest_source(connector, tenant_id=tenant)
        return {"id": str(source_id), "status": "done", **stats.model_dump()}


@router.post(
    "/v1/sources/{source_id}/documents", status_code=status.HTTP_202_ACCEPTED, dependencies=[_admin]
)
async def upload_document(
    source_id: uuid.UUID,
    req: UploadDocumentRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    """File-upload path: ingest one document under this source (no external API)."""
    source = await _get_source(session, tenant, source_id)
    result = await enqueue_ingest_event(
        tenant_id=tenant,
        source_kind=source.kind,
        external_id=req.external_id,
        kind=req.kind,
        content=req.content,
    )
    return {"id": str(source_id), "job_id": result.job_id, "status": result.status}


@router.delete("/v1/sources/{source_id}", dependencies=[_admin])
async def delete_source(
    source_id: uuid.UUID,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    """Disconnect a source and purge its knowledge (chunks/vectors). Derived graph
    objects are left to go stale and be re-derived — precise graph GC is future work."""
    source = await _get_source(session, tenant, source_id)
    await delete_source_points(get_qdrant(), tenant_id=tenant, source_kind=source.kind)
    await session.delete(source)  # cascades artifacts -> chunks -> mentions/citations
    await session.commit()
    return {"id": str(source_id), "kind": source.kind, "disconnected": True}
