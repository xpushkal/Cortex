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
    ensure_collection,
    get_qdrant,
    search,
    upsert_chunks,
)

__all__ = [
    "CHUNKS_COLLECTION",
    "Artifact",
    "Base",
    "Chunk",
    "ChunkVector",
    "SearchHit",
    "Source",
    "ensure_collection",
    "get_engine",
    "get_qdrant",
    "get_sessionmaker",
    "search",
    "upsert_chunks",
]
