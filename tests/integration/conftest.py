"""Integration-tier fixtures: live Postgres + Qdrant (compose on 5433/6333).

Tests are skipped (not failed) when infra is unreachable, so the fast unit loop
and machines without the stack stay green; CI brings the services up.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
from qdrant_client import models
from sqlalchemy import delete, text

from cortex.connectors import SampleConnector
from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec
from cortex.storage import (
    CHUNKS_COLLECTION,
    Source,
    get_engine,
    get_qdrant,
    get_sessionmaker,
)
from cortex.storage.models import Entity, EntityMention, Process, Relation
from cortex.workers.ingest import ingest_source

# A token no document in the sample corpus contains — used to prove tenant B's
# data never leaks into tenant A's results.
MARKER = "zzzuniqueb-quantum-otter-marker"


class _MarkerConnector:
    """One-document connector carrying MARKER, for the isolation test."""

    kind = "sample"
    rate_limit = TokenBucketSpec(capacity=10, refill_per_second=10.0)

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        yield RawItem(
            external_id="marker-1",
            payload={"kind": "doc", "content": f"Secret tenant-B doc {MARKER} about widgets."},
        )

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        return iter(()), cursor

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind=str(raw.payload["kind"]),
            content=str(raw.payload["content"]),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


@pytest.fixture(autouse=True)
async def _require_infra() -> AsyncIterator[None]:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("select 1"))
        await get_qdrant().get_collections()
    except Exception as exc:
        pytest.skip(f"integration infra unavailable: {exc}")
    yield


async def _cleanup(tenant_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        # M2 graph/process rows aren't under the sources cascade — purge them too.
        for model in (Relation, EntityMention, Process, Entity):
            await session.execute(delete(model).where(model.tenant_id == tenant_id))
        await session.execute(delete(Source).where(Source.tenant_id == tenant_id))
        await session.commit()
    await get_qdrant().delete(
        collection_name=CHUNKS_COLLECTION,
        points_selector=models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id", match=models.MatchValue(value=str(tenant_id))
                )
            ]
        ),
    )


@pytest.fixture
async def seeded_tenant() -> AsyncIterator[uuid.UUID]:
    """Ingest the sample corpus into a fresh tenant; tear it down afterwards."""
    tenant_id = uuid.uuid4()
    await ingest_source(SampleConnector(), tenant_id=tenant_id)
    yield tenant_id
    await _cleanup(tenant_id)


@pytest.fixture
async def fresh_tenant() -> AsyncIterator[uuid.UUID]:
    """An empty tenant id with teardown — the test ingests into it itself."""
    tenant_id = uuid.uuid4()
    yield tenant_id
    await _cleanup(tenant_id)


@pytest.fixture
async def isolated_tenants() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID, str]]:
    """Tenant A = sample corpus; tenant B = a single MARKER doc. Yields (a, b, marker)."""
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    await ingest_source(SampleConnector(), tenant_id=tenant_a)
    await ingest_source(_MarkerConnector(), tenant_id=tenant_b)
    yield tenant_a, tenant_b, MARKER
    await _cleanup(tenant_a)
    await _cleanup(tenant_b)
