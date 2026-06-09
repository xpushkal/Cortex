"""Cortex persistence plane.

Async SQLAlchemy models + session for Postgres (relational/metadata, and later the
graph + process registry), and the Qdrant vector-store client. See
docs/DATA_MODEL.md and docs/ARCHITECTURE.md §4.
"""

from cortex.storage.db import get_engine, get_sessionmaker
from cortex.storage.models import Artifact, Base, Chunk, Source
from cortex.storage.qdrant import (
    CHUNKS_COLLECTION,
    ChunkVector,
    SearchHit,
    delete_artifact_points,
    ensure_collection,
    get_qdrant,
    search,
    upsert_chunks,
)
from cortex.storage.tenancy import resolve_tenant

__all__ = [
    "CHUNKS_COLLECTION",
    "Artifact",
    "Base",
    "Chunk",
    "ChunkVector",
    "SearchHit",
    "Source",
    "delete_artifact_points",
    "ensure_collection",
    "get_engine",
    "get_qdrant",
    "get_sessionmaker",
    "resolve_tenant",
    "search",
    "upsert_chunks",
]
