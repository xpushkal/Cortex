"""Cross-tenant leakage gate (M4; docs/ARCHITECTURE.md §6).

The done-when's verifiable half: under RLS, connecting as the least-privilege
`cortex_app` role, even a query with **no `WHERE tenant_id`** returns only the
current tenant's rows. The GUC switches the visible tenant; an unset GUC returns
nothing (fail-closed). This runs in the standard CI test job — a leak fails the
build. Complements the filter-level isolation tests (search/bm25/processes/ask).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import delete

from cortex.storage import app_role_dsn, get_sessionmaker, set_tenant
from cortex.storage.models import Artifact, Chunk, Source

pytestmark = pytest.mark.integration


async def _seed_chunk(session: sa.orm.Session, tenant_id: uuid.UUID, marker: str) -> None:
    source = Source(tenant_id=tenant_id, kind="sample")
    session.add(source)
    await session.flush()
    art = Artifact(
        tenant_id=tenant_id,
        source_id=source.id,
        external_id=f"doc-{marker}",
        content_hash="h",
        kind="doc",
        content=marker,
    )
    session.add(art)
    await session.flush()
    session.add(
        Chunk(tenant_id=tenant_id, artifact_id=art.id, ordinal=0, text=marker, content_hash="h0")
    )


async def test_rls_blocks_cross_tenant_reads() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    admin = get_sessionmaker()  # superuser cortex — seeds both tenants
    app = get_sessionmaker(app_role_dsn())  # least-privilege cortex_app — RLS enforced

    try:
        async with admin() as session:
            await _seed_chunk(session, tenant_a, "alpha")
            await _seed_chunk(session, tenant_b, "bravo")
            await session.commit()

        # As the restricted role, a query with NO tenant filter is RLS-scoped.
        async with app() as session:
            await set_tenant(session, tenant_a)
            seen = (await session.execute(sa.text("SELECT tenant_id FROM chunks"))).scalars().all()
            assert set(seen) == {tenant_a}, "tenant A saw foreign rows"

            await set_tenant(session, tenant_b)
            seen = (await session.execute(sa.text("SELECT tenant_id FROM chunks"))).scalars().all()
            assert set(seen) == {tenant_b}, "tenant B saw foreign rows"

        # A fresh session with the GUC unset is fail-closed: it sees nothing.
        async with app() as session:
            count = (await session.execute(sa.text("SELECT count(*) FROM chunks"))).scalar_one()
            assert count == 0, "RLS is not fail-closed when the tenant GUC is unset"
    finally:
        async with admin() as session:
            for t in (tenant_a, tenant_b):
                await session.execute(delete(Source).where(Source.tenant_id == t))
            await session.commit()
