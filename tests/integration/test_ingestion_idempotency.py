"""Idempotent ingestion (docs/INGESTION.md §3): re-ingest unchanged = no-op."""

from __future__ import annotations

import uuid

import pytest

from cortex.connectors import SampleConnector
from cortex.workers.ingest import ingest_source

pytestmark = pytest.mark.integration


async def test_reingest_unchanged_hash_is_noop(fresh_tenant: uuid.UUID) -> None:
    first = await ingest_source(SampleConnector(), tenant_id=fresh_tenant)
    second = await ingest_source(SampleConnector(), tenant_id=fresh_tenant)

    assert first.artifacts > 0
    assert first.chunks > 0
    # Re-running ingests nothing new; every artifact is skipped on the hash match.
    assert second.artifacts == 0
    assert second.chunks == 0
    assert second.skipped == first.artifacts
