"""M3 done-when verification (docs/ROADMAP.md §M3).

The freshness gate is behavioral, not a numeric threshold: (1) a source change
is retrievable immediately and re-versions the dependent process; (2) the
dependent process is marked stale; (3) no stale/expired process is ever served
as current unlabeled. Exercised end-to-end through the ASGI app.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.api.main import app
from cortex.knowledge import EXPIRED, get_freshness_map, list_processes, set_freshness
from cortex.storage import get_sessionmaker

pytestmark = pytest.mark.eval

_HEAD = "Refund handling policy for the billing team and customer support here now."
_V1 = f"{_HEAD} Refunds over $500 are approved by the finance team."
_V2 = f"{_HEAD} Refunds over $500 are approved by the VP of Sales."


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_change_retrievable_and_dependent_marked_stale(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    body = {"source_kind": "notion", "external_id": "refund", "kind": "page"}
    await api.post("/v1/ingest/events", json={**body, "content": _V1}, headers=headers)

    # The change arrives and is immediately retrievable (the < 60s gate).
    await api.post("/v1/ingest/events", json={**body, "content": _V2}, headers=headers)
    search = await api.post(
        "/v1/search", json={"q": "who approves a large refund VP of Sales", "k": 5}, headers=headers
    )
    assert any("VP of Sales" in r["text"] for r in search.json()["results"])

    # The dependent process re-versioned and is marked stale.
    async with get_sessionmaker()() as session:
        procs = await list_processes(session, tenant_id=fresh_tenant)
        assert len(procs) == 1
        assert procs[0].version == 2
        assert procs[0].freshness == "stale"


async def test_no_stale_or_expired_served_unlabeled(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    query = {"q": "how do we approve a refund over 500 dollars"}
    await api.post(
        "/v1/ingest/events",
        json={"source_kind": "notion", "external_id": "refund", "kind": "page", "content": _V1},
        headers=headers,
    )

    grounded = await api.post("/v1/ask", json=query, headers=headers)
    used = grounded.json()["used_processes"]
    assert used and grounded.json()["freshness"]["state"] == "fresh"
    pid = uuid.UUID(used[0].split(":")[1].split("@")[0])

    # Expire it (TTL path). It must then never be served as current.
    async with get_sessionmaker()() as session:
        await set_freshness(
            session, tenant_id=fresh_tenant, object_type="process", object_id=pid, state=EXPIRED
        )
        await session.commit()

    after = await api.post("/v1/ask", json=query, headers=headers)
    assert after.json()["used_processes"] == [], "an expired process must not be served as current"

    # The expiry is visible (labeled), not hidden.
    async with get_sessionmaker()() as session:
        states = await get_freshness_map(
            session, tenant_id=fresh_tenant, object_type="process", object_ids=[pid]
        )
    assert states[str(pid)] == EXPIRED
