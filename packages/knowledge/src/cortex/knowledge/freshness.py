"""Freshness repository — the M3 freshness loop (docs/INGESTION.md §5).

Reads and writes the `freshness` table, the source of truth for whether a
tracked object is `fresh`, `stale` (a source it depends on changed), or
`expired` (past its TTL). M3 tracks processes; the API is generic over
object_type. All writes are tenant-scoped and idempotent (upsert on the
`(tenant_id, object_type, object_id)` unique key).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.storage.models import Chunk as ChunkRow
from cortex.storage.models import Citation as CitationRow
from cortex.storage.models import Freshness as FreshnessRow
from cortex.storage.models import ProcessStep as ProcessStepRow
from cortex.storage.models import ProcessVersion as ProcessVersionRow

PROCESS_TTL_SECONDS = 90 * 24 * 3600  # processes revalidate quarterly by default

FRESH = "fresh"
STALE = "stale"
EXPIRED = "expired"


async def set_freshness(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    object_type: str,
    object_id: uuid.UUID,
    state: str,
    reason: str | None = None,
    ttl_seconds: int | None = None,
) -> None:
    """Upsert an object's freshness. Transitioning to `fresh` revalidates (now)."""
    row = (
        await session.execute(
            sa.select(FreshnessRow).where(
                FreshnessRow.tenant_id == tenant_id,
                FreshnessRow.object_type == object_type,
                FreshnessRow.object_id == object_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            FreshnessRow(
                tenant_id=tenant_id,
                object_type=object_type,
                object_id=object_id,
                state=state,
                reason=reason,
                ttl_seconds=ttl_seconds,
            )
        )
        return
    row.state = state
    row.reason = reason
    if ttl_seconds is not None:
        row.ttl_seconds = ttl_seconds
    if state == FRESH:
        row.last_validated_at = sa.func.now()


async def get_freshness_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    object_type: str,
    object_ids: list[uuid.UUID],
) -> dict[str, str]:
    """Return {object_id(str): state} for the given ids (missing ids omitted)."""
    if not object_ids:
        return {}
    rows = (
        await session.execute(
            sa.select(FreshnessRow.object_id, FreshnessRow.state).where(
                FreshnessRow.tenant_id == tenant_id,
                FreshnessRow.object_type == object_type,
                FreshnessRow.object_id.in_(object_ids),
            )
        )
    ).all()
    return {str(object_id): state for object_id, state in rows}


async def mark_processes_stale_for_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    artifact_id: uuid.UUID,
    reason: str,
) -> list[uuid.UUID]:
    """Mark every process citing a chunk of `artifact_id` stale. Returns their ids.

    Must run BEFORE the artifact's old chunks are deleted (citations cascade).
    """
    process_ids = (
        (
            await session.execute(
                sa.select(ProcessVersionRow.process_id)
                .join(ProcessStepRow, ProcessStepRow.process_version_id == ProcessVersionRow.id)
                .join(CitationRow, CitationRow.process_step_id == ProcessStepRow.id)
                .join(ChunkRow, ChunkRow.id == CitationRow.chunk_id)
                .where(
                    ProcessVersionRow.tenant_id == tenant_id,
                    ChunkRow.artifact_id == artifact_id,
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    for pid in process_ids:
        await set_freshness(
            session,
            tenant_id=tenant_id,
            object_type="process",
            object_id=pid,
            state=STALE,
            reason=reason,
        )
    return list(process_ids)


async def revalidate_process(
    session: AsyncSession, *, tenant_id: uuid.UUID, process_id: uuid.UUID
) -> None:
    """Mark a process fresh again (e.g. after human review/approval)."""
    await set_freshness(
        session,
        tenant_id=tenant_id,
        object_type="process",
        object_id=process_id,
        state=FRESH,
        reason=None,
        ttl_seconds=PROCESS_TTL_SECONDS,
    )


async def ttl_sweep(session: AsyncSession) -> int:
    """Expire every freshness row past its TTL. Tenant-agnostic; returns the count."""
    result = await session.execute(
        sa.text(
            "UPDATE freshness SET state = 'expired', updated_at = now() "
            "WHERE state <> 'expired' AND ttl_seconds IS NOT NULL "
            "AND last_validated_at + (ttl_seconds * interval '1 second') < now()"
        )
    )
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult at runtime
