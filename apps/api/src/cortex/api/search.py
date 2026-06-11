"""`POST /v1/search` — ranked retrieval, no generation (docs/API.md).

M1: hybrid by default — dense (Qdrant) + BM25 (Postgres FTS) fused with RRF,
then cross-encoder rerank (docs/RETRIEVAL_AND_ML.md §3). `mode=dense` keeps the
M0 path for ablation/A-B; both are tenant-filtered by construction.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.api.deps import db_session, tenant_id
from cortex.api.ratelimit import rate_limit
from cortex.obs import get_tracer
from cortex.retrieval import SearchMode, get_embedder, get_reranker, hybrid_search
from cortex.storage import SearchHit, get_qdrant

router = APIRouter()
_tracer = get_tracer(__name__)


class SearchRequest(BaseModel):
    q: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)
    mode: SearchMode = "hybrid"
    source_kinds: list[str] | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]


@router.post(
    "/v1/search", response_model=SearchResponse, dependencies=[Depends(rate_limit("read"))]
)
async def search(
    req: SearchRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SearchResponse:
    with _tracer.start_as_current_span("search.retrieve") as span:
        span.set_attribute("cortex.tenant_id", str(tenant))
        span.set_attribute("cortex.k", req.k)
        span.set_attribute("cortex.mode", req.mode)
        hits = await hybrid_search(
            query=req.q,
            tenant_id=tenant,
            session=session,
            qdrant=get_qdrant(),
            embedder=get_embedder(),
            reranker=get_reranker(),
            k=req.k,
            mode=req.mode,
            source_kinds=req.source_kinds,
        )
        span.set_attribute("cortex.hits", len(hits))
    return SearchResponse(results=hits)
