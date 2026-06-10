"""POST /v1/ask — process-grounded grounded Q&A over a seeded tenant (M2)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_ask_requires_tenant(api: AsyncClient) -> None:
    assert (await api.post("/v1/ask", json={"q": "refunds?"})).status_code == 400


async def test_ask_grounds_in_process(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    resp = await api.post(
        "/v1/ask",
        json={"q": "how do we approve a refund over 500 dollars"},
        headers={"X-Tenant": str(seeded_tenant)},
    )
    assert resp.status_code == 200
    data = resp.json()
    # A relevant process exists -> the answer is grounded in it and it is listed.
    assert data["used_processes"]
    assert data["used_processes"][0].startswith("process:")
    # Every citation references a chunk; the answer is non-empty and grounded.
    assert data["citations"] and all(c["chunk_id"] for c in data["citations"])
    assert "finance" in data["answer"].lower()
    assert data["freshness"]["state"] == "fresh"


async def test_ask_falls_back_to_chunks(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    # A query sharing no terms with any process name -> no grounding process,
    # so the answer falls back to raw retrieved chunks (still cited).
    resp = await api.post(
        "/v1/ask",
        json={"q": "kubernetes pod restart crash loop backoff"},
        headers={"X-Tenant": str(seeded_tenant)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["used_processes"] == []
    assert data["citations"]  # chunk-grounded, never empty for a populated tenant
    assert all(c["chunk_id"] for c in data["citations"])


async def test_ask_is_tenant_isolated(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    other = uuid.uuid4()
    resp = await api.post(
        "/v1/ask", json={"q": "refund over 500"}, headers={"X-Tenant": str(other)}
    )
    assert resp.status_code == 200
    data = resp.json()
    # Empty tenant: no processes, no chunks -> empty grounding, no leak.
    assert data["used_processes"] == []
    assert data["citations"] == []
