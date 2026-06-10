"""Hybrid retrieval orchestration (docs/RETRIEVAL_AND_ML.md §3).

    query -> dense (Qdrant, tenant-filtered)  \\
                                               -> RRF -> cross-encoder rerank -> top-k
    query -> sparse (Postgres FTS, tenant-filtered) /

Both retrievers over-fetch `fetch_n` candidates; RRF fuses the two rank lists
(no score calibration needed); the reranker orders the fused pool and returns
top-k. `mode="dense"` skips fusion/rerank for ablation and A/B in the eval
harness. Each stage emits an OTel span.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from qdrant_client import AsyncQdrantClient

from cortex.obs import get_tracer
from cortex.retrieval.embedding import Embedder
from cortex.retrieval.fusion import reciprocal_rank_fusion
from cortex.retrieval.rerank import Reranker
from cortex.storage import SearchHit, search_bm25
from cortex.storage import search as dense_search

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_FETCH_N = 50  # candidates per retriever before fusion/rerank

SearchMode = Literal["dense", "hybrid"]

_tracer = get_tracer(__name__)


async def hybrid_search(
    *,
    query: str,
    tenant_id: uuid.UUID,
    session: AsyncSession,
    qdrant: AsyncQdrantClient,
    embedder: Embedder,
    reranker: Reranker,
    k: int = 10,
    mode: SearchMode = "hybrid",
    source_kinds: list[str] | None = None,
    fetch_n: int = DEFAULT_FETCH_N,
) -> list[SearchHit]:
    """Tenant-filtered hybrid retrieval; returns top-k hits scored by RRF."""
    with _tracer.start_as_current_span("search.dense") as span:
        vector = embedder.embed([query])[0]
        dense_hits = await dense_search(
            qdrant, tenant_id=tenant_id, vector=vector, k=fetch_n, source_kinds=source_kinds
        )
        span.set_attribute("cortex.hits", len(dense_hits))
    if mode == "dense":
        return dense_hits[:k]

    with _tracer.start_as_current_span("search.bm25") as span:
        sparse_hits = await search_bm25(
            session, tenant_id=tenant_id, query=query, k=fetch_n, source_kinds=source_kinds
        )
        span.set_attribute("cortex.hits", len(sparse_hits))

    with _tracer.start_as_current_span("search.fuse"):
        fused = reciprocal_rank_fusion(
            [[h.chunk_id for h in dense_hits], [h.chunk_id for h in sparse_hits]]
        )
        # First occurrence wins; dense and sparse carry the same payload fields.
        by_id: dict[str, SearchHit] = {}
        for hit in [*dense_hits, *sparse_hits]:
            by_id.setdefault(hit.chunk_id, hit)
        rrf_score = dict(fused)
        candidates = [(cid, by_id[cid].text) for cid, _ in fused[:fetch_n]]

    with _tracer.start_as_current_span("search.rerank") as span:
        ordered = reranker.rerank(query, candidates, top_k=k)
        span.set_attribute("cortex.hits", len(ordered))

    return [by_id[cid].model_copy(update={"score": rrf_score[cid]}) for cid in ordered]
