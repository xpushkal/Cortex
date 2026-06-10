"""Freshness repository: set/get, dependent staleness, TTL sweep, revalidate (M3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy import delete

from cortex.knowledge import (
    EXPIRED,
    FRESH,
    STALE,
    Citation,
    Process,
    ProcessStep,
    get_freshness_map,
    mark_processes_stale_for_artifact,
    revalidate_process,
    save_process,
    set_freshness,
    ttl_sweep,
)
from cortex.storage import get_sessionmaker
from cortex.storage.models import Artifact, Chunk, Freshness, Source
from cortex.storage.models import Process as ProcessRow

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant_artifact() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID, str]]:
    """A tenant with one artifact + chunk; yields (tenant_id, artifact_id, chunk_id)."""
    tenant_id = uuid.uuid4()
    sm = get_sessionmaker()
    async with sm() as session:
        source = Source(tenant_id=tenant_id, kind="sample")
        session.add(source)
        await session.flush()
        art = Artifact(
            tenant_id=tenant_id,
            source_id=source.id,
            external_id="doc-1",
            content_hash="h",
            kind="doc",
            content="...",
        )
        session.add(art)
        await session.flush()
        chunk = Chunk(
            tenant_id=tenant_id, artifact_id=art.id, ordinal=0, text="body", content_hash="h0"
        )
        session.add(chunk)
        await session.flush()
        ids = (tenant_id, art.id, str(chunk.id))
        await session.commit()
    yield ids
    async with sm() as session:
        await session.execute(delete(Freshness).where(Freshness.tenant_id == tenant_id))
        await session.execute(delete(ProcessRow).where(ProcessRow.tenant_id == tenant_id))
        await session.execute(delete(Source).where(Source.tenant_id == tenant_id))
        await session.commit()


async def test_set_and_get_freshness(tenant_artifact: tuple[uuid.UUID, uuid.UUID, str]) -> None:
    tenant_id, _art, _chunk = tenant_artifact
    oid = uuid.uuid4()
    sm = get_sessionmaker()
    async with sm() as session:
        await set_freshness(
            session, tenant_id=tenant_id, object_type="process", object_id=oid, state=STALE
        )
        await session.commit()
    async with sm() as session:
        m = await get_freshness_map(
            session, tenant_id=tenant_id, object_type="process", object_ids=[oid]
        )
    assert m == {str(oid): STALE}


async def test_mark_dependent_process_stale(
    tenant_artifact: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    tenant_id, artifact_id, chunk_id = tenant_artifact
    sm = get_sessionmaker()
    async with sm() as session:
        pid = await save_process(
            session,
            tenant_id=tenant_id,
            process=Process(
                name="P",
                trigger="t",
                steps=[
                    ProcessStep(ordinal=1, action="do", citations=[Citation(chunk_id=chunk_id)])
                ],
            ),
        )
        await set_freshness(
            session, tenant_id=tenant_id, object_type="process", object_id=pid, state=FRESH
        )
        await session.commit()

    async with sm() as session:
        marked = await mark_processes_stale_for_artifact(
            session, tenant_id=tenant_id, artifact_id=artifact_id, reason="artifact changed"
        )
        await session.commit()
        assert pid in marked
    async with sm() as session:
        m = await get_freshness_map(
            session, tenant_id=tenant_id, object_type="process", object_ids=[pid]
        )
    assert m[str(pid)] == STALE


async def test_ttl_sweep_expires_overage_rows(
    tenant_artifact: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    tenant_id, _art, _chunk = tenant_artifact
    oid = uuid.uuid4()
    sm = get_sessionmaker()
    async with sm() as session:
        await set_freshness(
            session,
            tenant_id=tenant_id,
            object_type="process",
            object_id=oid,
            state=FRESH,
            ttl_seconds=10,
        )
        await session.commit()
    # Backdate last_validated_at well past the TTL (separate, committed step).
    async with sm() as session:
        await session.execute(
            sa.text(
                "UPDATE freshness SET last_validated_at = now() - interval '1 hour' "
                "WHERE tenant_id = :t AND object_id = :o"
            ),
            {"t": tenant_id, "o": oid},
        )
        await session.commit()
    async with sm() as session:
        swept = await ttl_sweep(session)
        await session.commit()
        assert swept >= 1
    async with sm() as session:
        m = await get_freshness_map(
            session, tenant_id=tenant_id, object_type="process", object_ids=[oid]
        )
    assert m[str(oid)] == EXPIRED


async def test_revalidate_returns_to_fresh(
    tenant_artifact: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    tenant_id, _art, _chunk = tenant_artifact
    oid = uuid.uuid4()
    sm = get_sessionmaker()
    async with sm() as session:
        await set_freshness(
            session, tenant_id=tenant_id, object_type="process", object_id=oid, state=STALE
        )
        await session.commit()
    async with sm() as session:
        await revalidate_process(session, tenant_id=tenant_id, process_id=oid)
        await session.commit()
    async with sm() as session:
        m = await get_freshness_map(
            session, tenant_id=tenant_id, object_type="process", object_ids=[oid]
        )
    assert m[str(oid)] == FRESH
