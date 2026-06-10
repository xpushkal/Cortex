"""Knowledge repository: graph + process persistence, idempotency, versioning (M2)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from cortex.knowledge import (
    Citation,
    Process,
    ProcessStep,
    RelationCandidate,
    ResolvedEntity,
    get_process_body,
    get_process_versions,
    list_processes,
    save_graph,
    save_process,
)
from cortex.storage import get_sessionmaker
from cortex.storage.models import (
    Artifact,
    Chunk,
    Entity,
    EntityMention,
    Relation,
    Source,
)
from cortex.storage.models import Process as ProcessRow

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant_with_chunks() -> AsyncIterator[tuple[uuid.UUID, str, str]]:
    """A tenant with two real chunks; yields (tenant_id, chunk_a_id, chunk_b_id)."""
    tenant_id = uuid.uuid4()
    sm = get_sessionmaker()
    async with sm() as session:
        source = Source(tenant_id=tenant_id, kind="sample")
        session.add(source)
        await session.flush()
        art = Artifact(
            tenant_id=tenant_id,
            source_id=source.id,
            external_id="doc-refund",
            content_hash="h",
            kind="doc",
            content="...",
        )
        session.add(art)
        await session.flush()
        chunks = []
        for i in range(2):
            c = Chunk(
                tenant_id=tenant_id,
                artifact_id=art.id,
                ordinal=i,
                text=f"c{i}",
                content_hash=f"h{i}",
            )
            session.add(c)
            await session.flush()
            chunks.append(str(c.id))
        await session.commit()
    yield tenant_id, chunks[0], chunks[1]
    async with sm() as session:
        for model in (Relation, EntityMention):
            await session.execute(delete(model).where(model.tenant_id == tenant_id))
        await session.execute(delete(Entity).where(Entity.tenant_id == tenant_id))
        await session.execute(delete(ProcessRow).where(ProcessRow.tenant_id == tenant_id))
        await session.execute(delete(Source).where(Source.tenant_id == tenant_id))
        await session.commit()


def _proc(actions: list[str], chunk_id: str) -> Process:
    return Process(
        name="Refund policy",
        trigger="A refund is requested",
        steps=[
            ProcessStep(ordinal=i + 1, action=a, citations=[Citation(chunk_id=chunk_id)])
            for i, a in enumerate(actions)
        ],
    )


async def test_save_graph_is_idempotent(tenant_with_chunks: tuple[uuid.UUID, str, str]) -> None:
    tenant_id, chunk_a, _ = tenant_with_chunks
    entities = [
        ResolvedEntity(
            name="finance team",
            type="team",
            aliases=["finance", "finance team"],
            chunk_ids=[chunk_a],
        )
    ]
    relations = [
        RelationCandidate(
            subject="finance team", predicate="owns", object="finance team", source_chunk_id=chunk_a
        )
    ]
    sm = get_sessionmaker()
    async with sm() as session:
        await save_graph(session, tenant_id=tenant_id, entities=entities, relations=relations)
        await session.commit()
    # Second run must not duplicate the entity or its mention.
    async with sm() as session:
        await save_graph(session, tenant_id=tenant_id, entities=entities, relations=relations)
        await session.commit()
    async with sm() as session:
        ents = (
            (await session.execute(select(Entity).where(Entity.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        mentions = (
            (
                await session.execute(
                    select(EntityMention).where(EntityMention.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(ents) == 1
        assert sorted(ents[0].aliases) == ["finance", "finance team"]
        assert len(mentions) == 1  # de-duplicated across the two runs


async def test_save_process_versioning_and_idempotency(
    tenant_with_chunks: tuple[uuid.UUID, str, str],
) -> None:
    tenant_id, chunk_a, _ = tenant_with_chunks
    sm = get_sessionmaker()
    async with sm() as session:
        pid = await save_process(
            session, tenant_id=tenant_id, process=_proc(["Verify order"], chunk_a)
        )
        await session.commit()

    # Re-saving the identical body is a no-op: still version 1, still active.
    async with sm() as session:
        await save_process(session, tenant_id=tenant_id, process=_proc(["Verify order"], chunk_a))
        await session.commit()
    async with sm() as session:
        summaries = await list_processes(session, tenant_id=tenant_id)
        assert len(summaries) == 1
        assert summaries[0].version == 1
        assert summaries[0].status == "active"

    # A changed body appends version 2 and flips status to draft (no overwrite).
    async with sm() as session:
        await save_process(
            session,
            tenant_id=tenant_id,
            process=_proc(["Verify order", "Route to finance"], chunk_a),
        )
        await session.commit()
    async with sm() as session:
        body = await get_process_body(session, tenant_id=tenant_id, process_id=pid)
        versions = await get_process_versions(session, tenant_id=tenant_id, process_id=pid)
        assert body is not None
        assert body["version"] == 2
        assert body["status"] == "draft"
        assert len(body["steps"]) == 2
        assert [v["version"] for v in versions] == [2, 1]


async def test_processes_are_tenant_scoped(
    tenant_with_chunks: tuple[uuid.UUID, str, str],
) -> None:
    tenant_id, chunk_a, _ = tenant_with_chunks
    sm = get_sessionmaker()
    async with sm() as session:
        await save_process(session, tenant_id=tenant_id, process=_proc(["Verify order"], chunk_a))
        await session.commit()
    other = uuid.uuid4()
    async with sm() as session:
        assert await list_processes(session, tenant_id=other) == []
