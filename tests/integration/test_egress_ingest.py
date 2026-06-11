"""Egress rate limiting in ingestion: a tight bucket throttles but completes (M4)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec
from cortex.knowledge import list_processes
from cortex.storage import get_sessionmaker
from cortex.workers.ingest import ingest_source

pytestmark = pytest.mark.integration


class _ThrottledConnector:
    """Four docs behind a tight per-source bucket (2 capacity, 20/s refill)."""

    kind = "sample"
    rate_limit = TokenBucketSpec(capacity=2, refill_per_second=20.0)

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        for i in range(4):
            yield RawItem(
                external_id=f"doc-{i}",
                payload={"kind": "doc", "content": f"Submit receipts for expense {i} to finance."},
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


async def test_egress_throttles_but_ingests_all(fresh_tenant: uuid.UUID) -> None:
    start = time.monotonic()
    stats = await ingest_source(_ThrottledConnector(), tenant_id=fresh_tenant)
    elapsed = time.monotonic() - start

    # All four artifacts are ingested (throttled, never dropped).
    assert stats.artifacts == 4
    # 4 items, 2 free then refill at 20/s -> at least ~2 token-waits (~0.1s).
    assert elapsed >= 0.05

    async with get_sessionmaker()() as session:
        procs = await list_processes(session, tenant_id=fresh_tenant)
    assert len(procs) == 4
