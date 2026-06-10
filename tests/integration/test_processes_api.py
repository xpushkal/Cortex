"""GET /v1/processes endpoints over a seeded tenant (M2)."""

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


async def test_list_processes_requires_tenant(api: AsyncClient) -> None:
    assert (await api.get("/v1/processes")).status_code == 400


async def test_list_and_fetch_process(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    headers = {"X-Tenant": str(seeded_tenant)}
    listing = await api.get("/v1/processes", headers=headers)
    assert listing.status_code == 200
    processes = listing.json()["processes"]
    assert processes and all(p["status"] == "active" for p in processes)

    pid = processes[0]["id"]
    detail = await api.get(f"/v1/processes/{pid}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["steps"]
    assert all(step["citations"] for step in body["steps"])  # the M2 guarantee

    versions = await api.get(f"/v1/processes/{pid}/versions", headers=headers)
    assert versions.status_code == 200
    assert versions.json()["versions"][0]["version"] == 1


async def test_status_filter(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    headers = {"X-Tenant": str(seeded_tenant)}
    drafts = await api.get("/v1/processes", params={"status": "draft"}, headers=headers)
    assert drafts.status_code == 200
    assert drafts.json()["processes"] == []  # first extraction is active, none draft


async def test_unknown_process_is_404(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    resp = await api.get(f"/v1/processes/{uuid.uuid4()}", headers={"X-Tenant": str(seeded_tenant)})
    assert resp.status_code == 404


async def test_processes_tenant_isolated(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    # A different tenant sees none of this tenant's processes.
    other = uuid.uuid4()
    resp = await api.get("/v1/processes", headers={"X-Tenant": str(other)})
    assert resp.status_code == 200
    assert resp.json()["processes"] == []
