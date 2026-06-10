"""Freshness in serving: /processes labels state, /ask never serves expired (M3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.api.main import app
from cortex.knowledge import EXPIRED, list_processes, set_freshness
from cortex.storage import get_sessionmaker

pytestmark = pytest.mark.integration

_DOC = (
    "Incident response runbook for production outages across all services here now. "
    "For a Sev1 incident, page the on-call engineer and escalate to the engineering manager."
)


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_processes_labels_freshness(api: AsyncClient, fresh_tenant: uuid.UUID) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    await api.post(
        "/v1/ingest/events",
        json={"source_kind": "notion", "external_id": "inc", "kind": "page", "content": _DOC},
        headers=headers,
    )
    listing = await api.get("/v1/processes", headers=headers)
    proc = listing.json()["processes"][0]
    assert proc["freshness"] == "fresh"


async def test_ask_does_not_serve_expired_process(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    await api.post(
        "/v1/ingest/events",
        json={"source_kind": "notion", "external_id": "inc", "kind": "page", "content": _DOC},
        headers=headers,
    )
    query = {"q": "incident sev1 escalate on-call engineer", "max_context": 5}

    # While fresh, the answer grounds in the process and is labeled fresh.
    before = await api.post("/v1/ask", json=query, headers=headers)
    assert before.json()["used_processes"], "expected process grounding while fresh"
    assert before.json()["freshness"]["state"] == "fresh"

    # Expire the process directly (simulating the TTL sweep).
    pid = uuid.UUID(before.json()["used_processes"][0].split(":")[1].split("@")[0])
    async with get_sessionmaker()() as session:
        await set_freshness(
            session, tenant_id=fresh_tenant, object_type="process", object_id=pid, state=EXPIRED
        )
        await session.commit()

    # Now /ask must NOT serve it as current — it falls back to chunks.
    after = await api.post("/v1/ask", json=query, headers=headers)
    assert after.json()["used_processes"] == []
    assert after.json()["citations"]  # still answers, from chunks
    # And /processes labels it expired (never served unlabeled).
    async with get_sessionmaker()() as session:
        summaries = await list_processes(session, tenant_id=fresh_tenant)
    assert summaries[0].freshness == "expired"
