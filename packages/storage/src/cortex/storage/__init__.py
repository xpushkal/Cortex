"""Cortex persistence plane.

Async SQLAlchemy models + session for Postgres (relational/metadata, and later the
graph + process registry), and the Qdrant vector-store client. See
docs/DATA_MODEL.md and docs/ARCHITECTURE.md §4.
"""

from cortex.storage.db import APP_ROLE, app_role_dsn, get_engine, get_sessionmaker, set_tenant
from cortex.storage.fts import search_bm25
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
from cortex.storage.ratelimit import (
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
    build_limiter,
)
from cortex.storage.tenancy import resolve_tenant

__all__ = [
    "APP_ROLE",
    "CHUNKS_COLLECTION",
    "Artifact",
    "Base",
    "Chunk",
    "ChunkVector",
    "InMemoryRateLimiter",
    "RateLimiter",
    "RedisRateLimiter",
    "SearchHit",
    "Source",
    "app_role_dsn",
    "build_limiter",
    "delete_artifact_points",
    "ensure_collection",
    "get_engine",
    "get_qdrant",
    "get_sessionmaker",
    "resolve_tenant",
    "search",
    "search_bm25",
    "set_tenant",
    "upsert_chunks",
]
