"""POST /v1/search through the full hybrid path (M1) — ASGI-level, live stores."""

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


async def test_missing_tenant_header_is_rejected(api: AsyncClient) -> None:
    response = await api.post("/v1/search", json={"q": "refunds"})
    assert response.status_code == 400


async def test_hybrid_returns_relevant_chunks(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    response = await api.post(
        "/v1/search",
        json={"q": "how do we approve a refund over 500 dollars", "k": 5},
        headers={"X-Tenant": str(seeded_tenant)},
    )
    assert response.status_code == 200
    texts = [r["text"] for r in response.json()["results"]]
    assert any("Refund policy" in t or "Refund escalation" in t for t in texts)


async def test_hybrid_finds_exact_error_code(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    response = await api.post(
        "/v1/search",
        json={"q": "ERR-5022", "k": 5},
        headers={"X-Tenant": str(seeded_tenant)},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results and "ERR-5022" in results[0]["text"]


async def test_dense_mode_still_works(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    response = await api.post(
        "/v1/search",
        json={"q": "sev1 incident on-call escalation pagerduty", "k": 5, "mode": "dense"},
        headers={"X-Tenant": str(seeded_tenant)},
    )
    assert response.status_code == 200
    texts = [r["text"] for r in response.json()["results"]]
    assert any("On-call runbook" in t for t in texts)


async def test_api_is_tenant_isolated(
    api: AsyncClient, isolated_tenants: tuple[uuid.UUID, uuid.UUID, str]
) -> None:
    tenant_a, _tenant_b, marker = isolated_tenants
    response = await api.post(
        "/v1/search",
        json={"q": marker, "k": 10},
        headers={"X-Tenant": str(tenant_a)},
    )
    assert response.status_code == 200
    assert all(marker not in r["text"] for r in response.json()["results"])
