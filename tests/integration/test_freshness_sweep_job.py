"""The TTL sweep job (M3): an over-age freshness row flips to expired."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import delete

from cortex.knowledge import get_freshness_map, set_freshness
from cortex.storage import get_sessionmaker
from cortex.storage.models import Freshness
from cortex.workers.freshness_sweep import run_sweep

pytestmark = pytest.mark.integration


async def test_run_sweep_expires_overage_row() -> None:
    tenant_id = uuid.uuid4()
    oid = uuid.uuid4()
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            await set_freshness(
                session,
                tenant_id=tenant_id,
                object_type="process",
                object_id=oid,
                state="fresh",
                ttl_seconds=10,
            )
            await session.commit()
        async with sm() as session:
            await session.execute(
                sa.text(
                    "UPDATE freshness SET last_validated_at = now() - interval '1 hour' "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
            await session.commit()

        expired = await run_sweep()
        assert expired >= 1

        async with sm() as session:
            states = await get_freshness_map(
                session, tenant_id=tenant_id, object_type="process", object_ids=[oid]
            )
        assert states[str(oid)] == "expired"
    finally:
        async with sm() as session:
            await session.execute(delete(Freshness).where(Freshness.tenant_id == tenant_id))
            await session.commit()
