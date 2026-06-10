"""Migration 0004: graph + process tables round-trip and cascade (M2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from cortex.storage import get_sessionmaker
from cortex.storage.models import (
    Citation,
    Entity,
    EntityMention,
    Process,
    ProcessStep,
    ProcessVersion,
    Relation,
)

pytestmark = pytest.mark.integration


async def _seed_chunk(session, tenant_id: uuid.UUID) -> uuid.UUID:
    """A minimal source->artifact->chunk so provenance FKs resolve."""
    from cortex.storage.models import Artifact, Chunk, Source

    source = Source(tenant_id=tenant_id, kind="sample")
    session.add(source)
    await session.flush()
    artifact = Artifact(
        tenant_id=tenant_id,
        source_id=source.id,
        external_id="doc-1",
        content_hash="sha256:x",
        kind="doc",
        content="body",
    )
    session.add(artifact)
    await session.flush()
    chunk = Chunk(
        tenant_id=tenant_id, artifact_id=artifact.id, ordinal=0, text="body", content_hash="h"
    )
    session.add(chunk)
    await session.flush()
    return chunk.id


async def test_graph_and_process_round_trip_and_cascade() -> None:
    tenant_id = uuid.uuid4()
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            chunk_id = await _seed_chunk(session, tenant_id)

            approver = Entity(tenant_id=tenant_id, type="team", name="finance")
            agent = Entity(tenant_id=tenant_id, type="role", name="support agent")
            session.add_all([approver, agent])
            await session.flush()

            session.add(
                EntityMention(
                    tenant_id=tenant_id, entity_id=approver.id, chunk_id=chunk_id, confidence=0.9
                )
            )
            session.add(
                Relation(
                    tenant_id=tenant_id,
                    subject_id=agent.id,
                    predicate="escalates_to",
                    object_id=approver.id,
                    source_chunk_id=chunk_id,
                )
            )

            proc = Process(tenant_id=tenant_id, name="Refund over $500", trigger="refund > 500")
            session.add(proc)
            await session.flush()
            version = ProcessVersion(
                tenant_id=tenant_id,
                process_id=proc.id,
                version=1,
                body={"name": "Refund over $500"},
            )
            session.add(version)
            await session.flush()
            step = ProcessStep(
                tenant_id=tenant_id,
                process_version_id=version.id,
                ordinal=1,
                action="Route to finance",
                actor_entity_id=agent.id,
            )
            session.add(step)
            await session.flush()
            session.add(
                Citation(
                    tenant_id=tenant_id,
                    owner_type="process_step",
                    process_step_id=step.id,
                    chunk_id=chunk_id,
                    quote="route to finance",
                )
            )
            await session.commit()

        # Deleting the process cascades to versions -> steps -> citations.
        async with sm() as session:
            proc_row = (
                await session.execute(select(Process).where(Process.tenant_id == tenant_id))
            ).scalar_one()
            await session.delete(proc_row)
            await session.commit()

        async with sm() as session:
            steps = (
                (
                    await session.execute(
                        select(ProcessStep).where(ProcessStep.tenant_id == tenant_id)
                    )
                )
                .scalars()
                .all()
            )
            cites = (
                (await session.execute(select(Citation).where(Citation.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
            # Entities survive (process delete doesn't touch them); steps/citations gone.
            assert steps == []
            assert cites == []
            entities = (
                (await session.execute(select(Entity).where(Entity.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
            assert len(entities) == 2
    finally:
        async with sm() as session:
            for model in (Relation, EntityMention, Citation, ProcessStep, ProcessVersion, Process):
                await session.execute(delete(model).where(model.tenant_id == tenant_id))
            await session.execute(delete(Entity).where(Entity.tenant_id == tenant_id))
            from cortex.storage.models import Source

            await session.execute(delete(Source).where(Source.tenant_id == tenant_id))
            await session.commit()
