"""`POST /v1/ingest/events` — incremental-sync entry point (docs/INGESTION.md §5).

The webhook path: a source change delivers a changed artifact here; Cortex
re-ingests it idempotently (re-chunk/embed/extract) and marks dependent
processes stale, so the change is queryable within seconds. Real source
webhooks/credentials land with the M4 connectors; this endpoint exercises the
change-driven path over any source kind.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cortex.api.deps import tenant_id
from cortex.obs import get_tracer
from cortex.workers.ingest import ingest_event

router = APIRouter()
_tracer = get_tracer(__name__)


class IngestEventRequest(BaseModel):
    source_kind: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    kind: str = "doc"  # message | email | page | pr | issue | doc
    content: str = Field(min_length=1)


class IngestEventResponse(BaseModel):
    ingested: int
    skipped: int
    chunks: int


@router.post("/v1/ingest/events", response_model=IngestEventResponse)
async def ingest_event_endpoint(
    req: IngestEventRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
) -> IngestEventResponse:
    with _tracer.start_as_current_span("ingest.event") as span:
        span.set_attribute("cortex.tenant_id", str(tenant))
        span.set_attribute("cortex.source_kind", req.source_kind)
        stats = await ingest_event(
            tenant_id=tenant,
            source_kind=req.source_kind,
            external_id=req.external_id,
            kind=req.kind,
            content=req.content,
        )
    return IngestEventResponse(ingested=stats.artifacts, skipped=stats.skipped, chunks=stats.chunks)
