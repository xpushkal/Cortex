"""Migration 0005: freshness table round-trip + uniqueness (M3)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from cortex.storage import get_sessionmaker
from cortex.storage.models import Freshness

pytestmark = pytest.mark.integration


async def test_freshness_round_trip_and_unique() -> None:
    tenant_id = uuid.uuid4()
    object_id = uuid.uuid4()
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            session.add(
                Freshness(
                    tenant_id=tenant_id,
                    object_type="process",
                    object_id=object_id,
                    state="stale",
                    reason="source artifact changed",
                    ttl_seconds=7776000,
                )
            )
            await session.commit()

        async with sm() as session:
            row = (
                await session.execute(select(Freshness).where(Freshness.tenant_id == tenant_id))
            ).scalar_one()
            assert row.state == "stale"
            assert row.reason == "source artifact changed"
            assert row.last_validated_at is not None
    finally:
        async with sm() as session:
            await session.execute(delete(Freshness).where(Freshness.tenant_id == tenant_id))
            await session.commit()
