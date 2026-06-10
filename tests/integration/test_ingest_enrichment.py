"""Ingestion wires graph + process extraction (M2); idempotent on re-seed."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from cortex.connectors import SampleConnector
from cortex.knowledge import list_processes
from cortex.storage import get_sessionmaker
from cortex.storage.models import Entity, ProcessVersion
from cortex.storage.models import Process as ProcessRow
from cortex.workers.ingest import ingest_source

pytestmark = pytest.mark.integration


async def test_seed_populates_graph_and_cited_processes(fresh_tenant: uuid.UUID) -> None:
    await ingest_source(SampleConnector(), tenant_id=fresh_tenant)
    sm = get_sessionmaker()
    async with sm() as session:
        entities = (
            (await session.execute(select(Entity).where(Entity.tenant_id == fresh_tenant)))
            .scalars()
            .all()
        )
        processes = await list_processes(session, tenant_id=fresh_tenant)

    # The graph has typed org entities with provenance (e.g. finance team).
    assert any(e.name == "finance team" for e in entities)
    # Processes were extracted, active, and every step carries a citation.
    assert processes
    assert all(p.status == "active" for p in processes)
    async with sm() as session:
        from cortex.knowledge import get_process_body

        refund = next(p for p in processes if "refund" in p.name.lower())
        body = await get_process_body(
            session, tenant_id=fresh_tenant, process_id=uuid.UUID(refund.id)
        )
    assert body is not None
    assert body["steps"]
    assert all(step["citations"] for step in body["steps"])


async def test_reseed_is_idempotent(fresh_tenant: uuid.UUID) -> None:
    await ingest_source(SampleConnector(), tenant_id=fresh_tenant)
    sm = get_sessionmaker()
    async with sm() as session:
        entities_1 = (
            await session.execute(
                select(func.count()).select_from(Entity).where(Entity.tenant_id == fresh_tenant)
            )
        ).scalar_one()
        versions_1 = (
            await session.execute(
                select(func.count())
                .select_from(ProcessVersion)
                .where(ProcessVersion.tenant_id == fresh_tenant)
            )
        ).scalar_one()

    # Re-seeding the unchanged corpus: artifacts skip, no new entities or versions.
    stats = await ingest_source(SampleConnector(), tenant_id=fresh_tenant)
    assert stats.artifacts == 0
    assert stats.skipped > 0

    async with sm() as session:
        entities_2 = (
            await session.execute(
                select(func.count()).select_from(Entity).where(Entity.tenant_id == fresh_tenant)
            )
        ).scalar_one()
        versions_2 = (
            await session.execute(
                select(func.count())
                .select_from(ProcessRow)
                .where(ProcessRow.tenant_id == fresh_tenant)
            )
        ).scalar_one()
    assert entities_2 == entities_1
    # No version churn: still one version per process.
    async with sm() as session:
        version_rows = (
            await session.execute(
                select(func.count())
                .select_from(ProcessVersion)
                .where(ProcessVersion.tenant_id == fresh_tenant)
            )
        ).scalar_one()
    assert version_rows == versions_1
    assert versions_2 > 0
