"""Change-driven re-ingest: dependents go stale + contradiction flagged (M3)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec
from cortex.knowledge import get_freshness_map, get_process_body, list_processes
from cortex.retrieval import HashingEmbedder
from cortex.storage import get_qdrant, get_sessionmaker, search
from cortex.storage.models import Process as ProcessRow
from cortex.workers.ingest import ingest_source

pytestmark = pytest.mark.integration

# Same first 12 words across versions so the process name (= artifact head) is
# stable; the approver changes deep in the body — a contradiction.
_HEAD = "Refund approvals policy for the billing team handling customer refund requests here."
_V1 = f"{_HEAD} Refunds over $500 are approved by the finance team."
_V2 = f"{_HEAD} Refunds over $500 are approved by the VP of Sales."


class _OneDoc:
    """A single-doc connector with mutable content (for the change test)."""

    kind = "sample"
    rate_limit = TokenBucketSpec(capacity=10, refill_per_second=10.0)

    def __init__(self, content: str) -> None:
        self._content = content

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        yield RawItem(external_id="doc-refund", payload={"kind": "doc", "content": self._content})

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        return iter(()), cursor

    def normalize(self, raw: RawItem) -> Artifact:
        from datetime import UTC, datetime

        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind=str(raw.payload["kind"]),
            content=str(raw.payload["content"]),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


async def test_source_change_marks_dependent_stale_and_flags_contradiction(
    fresh_tenant: uuid.UUID,
) -> None:
    # 1. Initial ingest: process is active + fresh, approver = finance team.
    await ingest_source(_OneDoc(_V1), tenant_id=fresh_tenant)
    sm = get_sessionmaker()
    async with sm() as session:
        procs = await list_processes(session, tenant_id=fresh_tenant)
        assert len(procs) == 1
        pid = uuid.UUID(procs[0].id)
        assert procs[0].status == "active"
        fresh = await get_freshness_map(
            session, tenant_id=fresh_tenant, object_type="process", object_ids=[pid]
        )
    assert fresh[str(pid)] == "fresh"

    # 2. The source artifact changes (different approver, same head).
    await ingest_source(_OneDoc(_V2), tenant_id=fresh_tenant)

    # 3. The change is immediately retrievable (the < 60s done-when, trivially).
    vector = HashingEmbedder().embed(["who approves a refund, VP of Sales"])[0]
    hits = await search(get_qdrant(), tenant_id=fresh_tenant, vector=vector, k=5)
    assert any("VP of Sales" in h.text for h in hits)
    assert all("finance team" not in h.text for h in hits)

    # 4. The dependent process is a new version, draft, stale, with the conflict recorded.
    async with sm() as session:
        proc_row = (
            await session.execute(select(ProcessRow).where(ProcessRow.id == pid))
        ).scalar_one()
        body = await get_process_body(session, tenant_id=fresh_tenant, process_id=pid)
        stale = await get_freshness_map(
            session, tenant_id=fresh_tenant, object_type="process", object_ids=[pid]
        )
    assert proc_row.current_version == 2
    assert proc_row.status == "draft"
    assert stale[str(pid)] == "stale"
    assert body is not None
    assert body.get("review", {}).get("needs_review") is True
    assert "actor" in body["review"]["reason"]
