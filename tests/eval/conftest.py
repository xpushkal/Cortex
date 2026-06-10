"""Eval-tier fixtures: like the integration tier, the harness needs live
Postgres + Qdrant and a seeded tenant; tests skip (not fail) without infra."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from qdrant_client import models
from sqlalchemy import delete, text

from cortex.connectors import SampleConnector
from cortex.storage import CHUNKS_COLLECTION, Source, get_engine, get_qdrant, get_sessionmaker
from cortex.storage.models import Entity, EntityMention, Freshness, Process, Relation
from cortex.workers.ingest import ingest_source


@pytest.fixture(autouse=True)
async def _require_infra() -> AsyncIterator[None]:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("select 1"))
        await get_qdrant().get_collections()
    except Exception as exc:
        pytest.skip(f"eval infra unavailable: {exc}")
    yield


async def _purge(tenant_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        for model in (Freshness, Relation, EntityMention, Process, Entity):
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
    tenant_id = uuid.uuid4()
    await ingest_source(SampleConnector(), tenant_id=tenant_id)
    yield tenant_id
    await _purge(tenant_id)


@pytest.fixture
async def fresh_tenant() -> AsyncIterator[uuid.UUID]:
    """An empty tenant the test populates itself; purged afterwards."""
    tenant_id = uuid.uuid4()
    yield tenant_id
    await _purge(tenant_id)
