"""Qdrant vector store wrapper.

One `chunks` collection; tenant isolation is enforced by a **mandatory** tenant_id
payload filter on every search (docs/ARCHITECTURE.md §6, DATA_MODEL.md §4). Sharding
by tenant is an M4 concern; the payload filter is the v1 guard and is non-optional
here by construction — `search()` requires a tenant_id and always applies it.
"""

from __future__ import annotations

import os
import uuid
from functools import lru_cache

from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient, models

CHUNKS_COLLECTION = "chunks"
DEFAULT_URL = "http://localhost:6333"


class ChunkVector(BaseModel):
    """A chunk's vector plus the payload Qdrant stores alongside it."""

    vector_id: uuid.UUID
    vector: list[float]
    tenant_id: uuid.UUID
    source_kind: str
    artifact_id: uuid.UUID
    chunk_id: uuid.UUID
    kind: str
    created_at: int
    content_hash: str
    text: str
    freshness: str = "fresh"


class SearchHit(BaseModel):
    chunk_id: str
    score: float
    text: str
    source_kind: str
    artifact_id: str
    created_at: int


@lru_cache(maxsize=4)
def get_qdrant(url: str | None = None) -> AsyncQdrantClient:
    """Return a cached async Qdrant client."""
    return AsyncQdrantClient(url=url or os.environ.get("QDRANT_URL", DEFAULT_URL))


async def ensure_collection(client: AsyncQdrantClient, *, dim: int) -> None:
    """Create the chunks collection (cosine) if it does not already exist."""
    if not await client.collection_exists(CHUNKS_COLLECTION):
        await client.create_collection(
            collection_name=CHUNKS_COLLECTION,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )


async def upsert_chunks(client: AsyncQdrantClient, points: list[ChunkVector]) -> None:
    """Idempotently upsert chunk vectors (point id = vector_id)."""
    if not points:
        return
    await client.upsert(
        collection_name=CHUNKS_COLLECTION,
        points=[
            models.PointStruct(
                id=str(p.vector_id),
                vector=p.vector,
                payload={
                    "tenant_id": str(p.tenant_id),
                    "source_kind": p.source_kind,
                    "artifact_id": str(p.artifact_id),
                    "chunk_id": str(p.chunk_id),
                    "kind": p.kind,
                    "created_at": p.created_at,
                    "content_hash": p.content_hash,
                    "text": p.text,
                    "freshness": p.freshness,
                },
            )
            for p in points
        ],
    )


async def delete_artifact_points(
    client: AsyncQdrantClient, *, tenant_id: uuid.UUID, artifact_id: uuid.UUID
) -> None:
    """Remove all points for one artifact (used when its content changed)."""
    await client.delete(
        collection_name=CHUNKS_COLLECTION,
        points_selector=models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id", match=models.MatchValue(value=str(tenant_id))
                ),
                models.FieldCondition(
                    key="artifact_id", match=models.MatchValue(value=str(artifact_id))
                ),
            ]
        ),
    )


async def search(
    client: AsyncQdrantClient,
    *,
    tenant_id: uuid.UUID,
    vector: list[float],
    k: int = 10,
    source_kinds: list[str] | None = None,
) -> list[SearchHit]:
    """Vector search, ALWAYS filtered to `tenant_id`. No cross-tenant path exists."""
    must: list[models.Condition] = [
        models.FieldCondition(key="tenant_id", match=models.MatchValue(value=str(tenant_id)))
    ]
    if source_kinds:
        must.append(
            models.FieldCondition(key="source_kind", match=models.MatchAny(any=source_kinds))
        )
    response = await client.query_points(
        collection_name=CHUNKS_COLLECTION,
        query=vector,
        limit=k,
        query_filter=models.Filter(must=must),
        with_payload=True,
    )
    hits: list[SearchHit] = []
    for point in response.points:
        payload = point.payload or {}
        hits.append(
            SearchHit(
                chunk_id=str(payload.get("chunk_id", point.id)),
                score=point.score,
                text=str(payload.get("text", "")),
                source_kind=str(payload.get("source_kind", "")),
                artifact_id=str(payload.get("artifact_id", "")),
                created_at=int(payload.get("created_at", 0)),
            )
        )
    return hits
