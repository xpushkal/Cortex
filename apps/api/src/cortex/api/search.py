"""`POST /v1/search` — ranked retrieval, no generation (docs/API.md).

M0 is dense-only: embed the query, ANN search in Qdrant filtered to the caller's
tenant. Hybrid (BM25 + RRF) and reranking arrive in M1.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cortex.api.deps import tenant_id
from cortex.retrieval import get_embedder
from cortex.storage import SearchHit, get_qdrant
from cortex.storage import search as qdrant_search

router = APIRouter()


class SearchRequest(BaseModel):
    q: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)
    source_kinds: list[str] | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]


@router.post("/v1/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
) -> SearchResponse:
    vector = get_embedder().embed([req.q])[0]
    hits = await qdrant_search(
        get_qdrant(),
        tenant_id=tenant,
        vector=vector,
        k=req.k,
        source_kinds=req.source_kinds,
    )
    return SearchResponse(results=hits)
