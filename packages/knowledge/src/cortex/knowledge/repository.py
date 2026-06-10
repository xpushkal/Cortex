"""Persistence for the knowledge graph + process registry (docs/DATA_MODEL.md §3/§5).

Bridges the knowledge domain models to the storage ORM. Knowledge depends on
storage (domain over persistence); ORM rows are aliased `*Row` to avoid clashing
with the Pydantic domain models of the same name.

Write side (`save_graph`, `save_process`) is idempotent: re-ingesting an
unchanged corpus adds no duplicate entities and bumps no process version. Read
side (`list_processes`, `get_process_body`, `get_process_versions`) backs the
`/processes` API. All functions are tenant-scoped.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.knowledge.contradiction import detect_contradiction
from cortex.knowledge.freshness import (
    FRESH,
    PROCESS_TTL_SECONDS,
    STALE,
    revalidate_process,
    set_freshness,
)
from cortex.knowledge.models import Process, RelationCandidate, ResolvedEntity
from cortex.storage.models import Citation as CitationRow
from cortex.storage.models import Entity as EntityRow
from cortex.storage.models import EntityMention as EntityMentionRow
from cortex.storage.models import Process as ProcessRow
from cortex.storage.models import ProcessStep as ProcessStepRow
from cortex.storage.models import ProcessVersion as ProcessVersionRow
from cortex.storage.models import Relation as RelationRow


class ProcessSummary(BaseModel):
    id: str
    name: str
    version: int
    status: str
    confidence: float


# --- graph --------------------------------------------------------------------


async def save_graph(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    entities: list[ResolvedEntity],
    relations: list[RelationCandidate],
) -> dict[str, uuid.UUID]:
    """Upsert entities (alias-merged), mentions, and relations. Returns name->id.

    The returned map keys every alias (lowercased) to its entity id, for actor
    resolution in `save_process`. Idempotent: existing entities are reused and
    mentions/relations are de-duplicated.
    """
    name_to_id: dict[str, uuid.UUID] = {}
    for ent in entities:
        row = (
            await session.execute(
                sa.select(EntityRow).where(
                    EntityRow.tenant_id == tenant_id,
                    EntityRow.type == ent.type,
                    EntityRow.name == ent.name,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = EntityRow(
                tenant_id=tenant_id, type=ent.type, name=ent.name, aliases=sorted(set(ent.aliases))
            )
            session.add(row)
            await session.flush()
        else:
            merged = sorted(set(row.aliases) | set(ent.aliases))
            if merged != row.aliases:
                row.aliases = merged
        for alias in {ent.name, *ent.aliases}:
            name_to_id[alias.lower()] = row.id
        for chunk_id in ent.chunk_ids:
            await _ensure_mention(session, tenant_id, row.id, uuid.UUID(chunk_id), ent.confidence)

    for rel in relations:
        subject_id = name_to_id.get(rel.subject.lower())
        object_id = name_to_id.get(rel.object.lower())
        if subject_id is None or object_id is None:
            continue  # an endpoint never resolved to an entity; skip the edge
        await _ensure_relation(session, tenant_id, rel, subject_id, object_id)

    return name_to_id


async def _ensure_mention(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    entity_id: uuid.UUID,
    chunk_id: uuid.UUID,
    confidence: float,
) -> None:
    exists = (
        await session.execute(
            sa.select(EntityMentionRow.id).where(
                EntityMentionRow.tenant_id == tenant_id,
                EntityMentionRow.entity_id == entity_id,
                EntityMentionRow.chunk_id == chunk_id,
            )
        )
    ).first()
    if exists is None:
        session.add(
            EntityMentionRow(
                tenant_id=tenant_id, entity_id=entity_id, chunk_id=chunk_id, confidence=confidence
            )
        )


async def _ensure_relation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    rel: RelationCandidate,
    subject_id: uuid.UUID,
    object_id: uuid.UUID,
) -> None:
    source_chunk_id = uuid.UUID(rel.source_chunk_id)
    exists = (
        await session.execute(
            sa.select(RelationRow.id).where(
                RelationRow.tenant_id == tenant_id,
                RelationRow.subject_id == subject_id,
                RelationRow.predicate == rel.predicate,
                RelationRow.object_id == object_id,
                RelationRow.source_chunk_id == source_chunk_id,
            )
        )
    ).first()
    if exists is None:
        session.add(
            RelationRow(
                tenant_id=tenant_id,
                subject_id=subject_id,
                predicate=rel.predicate,
                object_id=object_id,
                confidence=rel.confidence,
                source_chunk_id=source_chunk_id,
            )
        )


# --- processes ----------------------------------------------------------------


async def save_process(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    process: Process,
    actor_resolver: dict[str, uuid.UUID] | None = None,
) -> uuid.UUID:
    """Persist a process version-aware. Identical body to the latest = no-op.

    A new process is created `active` + `fresh` at version 1. A changed body on
    an existing process appends a new version (status `draft`) rather than
    mutating (D6), runs contradiction detection (M3), records the diff on the
    new version when it conflicts, and marks the process `stale` — never served
    as current until reviewed.
    """
    actor_resolver = actor_resolver or {}
    body = process.model_dump()

    proc = (
        await session.execute(
            sa.select(ProcessRow).where(
                ProcessRow.tenant_id == tenant_id, ProcessRow.name == process.name
            )
        )
    ).scalar_one_or_none()

    if proc is None:
        proc = ProcessRow(
            tenant_id=tenant_id,
            name=process.name,
            trigger=process.trigger,
            current_version=1,
            status="active",
        )
        session.add(proc)
        await session.flush()
        await _write_version(
            session,
            tenant_id,
            proc,
            version=1,
            body=body,
            process=process,
            actor_resolver=actor_resolver,
        )
        await set_freshness(
            session,
            tenant_id=tenant_id,
            object_type="process",
            object_id=proc.id,
            state=FRESH,
            ttl_seconds=PROCESS_TTL_SECONDS,
        )
        return proc.id

    latest = (
        await session.execute(
            sa.select(ProcessVersionRow)
            .where(ProcessVersionRow.process_id == proc.id)
            .order_by(ProcessVersionRow.version.desc())
            .limit(1)
        )
    ).scalar_one()
    if _same_body(latest.body, body):
        return proc.id  # idempotent: unchanged extraction, no version churn

    report = detect_contradiction(latest.body, body)
    if report.contradictory:
        body = {**body, "review": {"needs_review": True, "reason": report.summary}}
    new_version = latest.version + 1
    proc.current_version = new_version
    proc.status = "draft"  # a changed process needs review before going active
    proc.trigger = process.trigger
    await _write_version(
        session,
        tenant_id,
        proc,
        version=new_version,
        body=body,
        process=process,
        actor_resolver=actor_resolver,
    )
    await set_freshness(
        session,
        tenant_id=tenant_id,
        object_type="process",
        object_id=proc.id,
        state=STALE,
        reason=f"contradiction: {report.summary}" if report.contradictory else "source changed",
    )
    return proc.id


def _same_body(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Compare the meaningful content of two process bodies (ignore version)."""
    return (a.get("trigger"), a.get("steps")) == (b.get("trigger"), b.get("steps"))


async def _write_version(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    proc: ProcessRow,
    *,
    version: int,
    body: dict[str, Any],
    process: Process,
    actor_resolver: dict[str, uuid.UUID],
) -> None:
    body = {**body, "version": version}
    pv = ProcessVersionRow(
        tenant_id=tenant_id, process_id=proc.id, version=version, body=body, created_by="extractor"
    )
    session.add(pv)
    await session.flush()
    for step in process.steps:
        actor_id = actor_resolver.get(step.actor.lower()) if step.actor else None
        step_row = ProcessStepRow(
            tenant_id=tenant_id,
            process_version_id=pv.id,
            ordinal=step.ordinal,
            action=step.action,
            actor_entity_id=actor_id,
            decision=step.decision,
        )
        session.add(step_row)
        await session.flush()
        for cite in step.citations:
            session.add(
                CitationRow(
                    tenant_id=tenant_id,
                    owner_type="process_step",
                    process_step_id=step_row.id,
                    chunk_id=uuid.UUID(cite.chunk_id),
                    quote=cite.quote,
                )
            )


async def review_process(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    process_id: uuid.UUID,
    action: str,
) -> bool:
    """Human review of a process (docs/API.md). approve -> active + fresh; reject
    -> deprecated. Returns False if the process doesn't exist for the tenant."""
    proc = (
        await session.execute(
            sa.select(ProcessRow).where(
                ProcessRow.tenant_id == tenant_id, ProcessRow.id == process_id
            )
        )
    ).scalar_one_or_none()
    if proc is None:
        return False
    if action == "approve":
        proc.status = "active"
        await revalidate_process(session, tenant_id=tenant_id, process_id=process_id)
    elif action == "reject":
        proc.status = "deprecated"
    else:
        raise ValueError(f"unknown review action: {action!r}")
    return True


async def list_processes(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: str | None = None,
    q: str | None = None,
) -> list[ProcessSummary]:
    stmt = sa.select(ProcessRow).where(ProcessRow.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ProcessRow.status == status)
    if q:
        stmt = stmt.where(ProcessRow.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(ProcessRow.name)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        ProcessSummary(
            id=str(r.id),
            name=r.name,
            version=r.current_version,
            status=r.status,
            confidence=r.confidence,
        )
        for r in rows
    ]


async def get_process_body(
    session: AsyncSession, *, tenant_id: uuid.UUID, process_id: uuid.UUID
) -> dict[str, Any] | None:
    """Return the canonical body of a process's current version, or None."""
    proc = (
        await session.execute(
            sa.select(ProcessRow).where(
                ProcessRow.tenant_id == tenant_id, ProcessRow.id == process_id
            )
        )
    ).scalar_one_or_none()
    if proc is None:
        return None
    version = (
        await session.execute(
            sa.select(ProcessVersionRow).where(
                ProcessVersionRow.process_id == proc.id,
                ProcessVersionRow.version == proc.current_version,
            )
        )
    ).scalar_one()
    return {**version.body, "id": str(proc.id), "status": proc.status}


_WORD = re.compile(r"[a-z0-9$]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if len(t) > 2}


async def match_process(
    session: AsyncSession, *, tenant_id: uuid.UUID, query: str
) -> dict[str, Any] | None:
    """Return the active process whose name+trigger best overlaps the query, or None.

    A lightweight lexical match: the active process sharing the most salient
    tokens with the query grounds `/ask`. None when nothing overlaps (the
    endpoint then falls back to raw chunk retrieval).
    """
    rows = (
        await session.execute(
            sa.select(ProcessRow, ProcessVersionRow)
            .join(
                ProcessVersionRow,
                (ProcessVersionRow.process_id == ProcessRow.id)
                & (ProcessVersionRow.version == ProcessRow.current_version),
            )
            .where(ProcessRow.tenant_id == tenant_id, ProcessRow.status == "active")
        )
    ).all()
    q_tokens = _tokens(query)
    best: tuple[ProcessRow, ProcessVersionRow] | None = None
    best_score = 0
    for proc, version in rows:
        score = len(q_tokens & _tokens(f"{proc.name} {proc.trigger}"))
        if score > best_score:
            best_score, best = score, (proc, version)
    if best is None:
        return None
    proc, version = best
    return {**version.body, "id": str(proc.id), "status": proc.status}


async def get_process_versions(
    session: AsyncSession, *, tenant_id: uuid.UUID, process_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                sa.select(ProcessVersionRow)
                .where(
                    ProcessVersionRow.tenant_id == tenant_id,
                    ProcessVersionRow.process_id == process_id,
                )
                .order_by(ProcessVersionRow.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [{"version": r.version, "created_by": r.created_by, "body": r.body} for r in rows]
