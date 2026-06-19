"""Source management: connect, list, sync, upload, disconnect (docs/API.md)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from cortex.api.main import app
from cortex.storage import Source, get_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def tenant() -> AsyncIterator[uuid.UUID]:
    t = uuid.uuid4()
    yield t
    async with get_sessionmaker()() as session:
        await session.execute(delete(Source).where(Source.tenant_id == t))
        await session.commit()


async def test_connect_list_and_idempotent_create(api: AsyncClient, tenant: uuid.UUID) -> None:
    h = {"X-Tenant": str(tenant)}
    created = await api.post("/v1/sources", json={"kind": "sample"}, headers=h)
    assert created.status_code == 201
    sid = created.json()["id"]

    # Re-connecting the same kind is idempotent (one source per tenant+kind).
    again = await api.post("/v1/sources", json={"kind": "sample"}, headers=h)
    assert again.json()["id"] == sid

    listed = await api.get("/v1/sources", headers=h)
    assert [s["kind"] for s in listed.json()["sources"]] == ["sample"]


async def test_sync_ingests_and_search_finds_it(api: AsyncClient, tenant: uuid.UUID) -> None:
    h = {"X-Tenant": str(tenant)}
    sid = (await api.post("/v1/sources", json={"kind": "sample"}, headers=h)).json()["id"]

    synced = await api.post(f"/v1/sources/{sid}/sync", headers=h)
    assert synced.status_code == 200
    assert synced.json()["status"] == "done"
    assert synced.json()["chunks"] > 0

    hit = await api.post("/v1/search", json={"q": "refund over $500 finance", "k": 5}, headers=h)
    assert hit.json()["results"]


async def test_upload_document_then_disconnect_purges(api: AsyncClient, tenant: uuid.UUID) -> None:
    h = {"X-Tenant": str(tenant)}
    sid = (await api.post("/v1/sources", json={"kind": "file"}, headers=h)).json()["id"]

    up = await api.post(
        f"/v1/sources/{sid}/documents",
        json={
            "external_id": "handbook",
            "kind": "doc",
            "content": "Refund policy: finance signs off over $500.",
        },
        headers=h,
    )
    assert up.status_code == 202
    assert (await api.post("/v1/search", json={"q": "refund finance", "k": 5}, headers=h)).json()[
        "results"
    ]

    # Disconnect purges the source's vectors: search no longer returns its content.
    gone = await api.delete(f"/v1/sources/{sid}", headers=h)
    assert gone.status_code == 200 and gone.json()["disconnected"] is True
    after = await api.post("/v1/search", json={"q": "refund finance", "k": 5}, headers=h)
    assert after.json()["results"] == []


async def test_sync_unsupported_kind_is_422(api: AsyncClient, tenant: uuid.UUID) -> None:
    h = {"X-Tenant": str(tenant)}
    sid = (await api.post("/v1/sources", json={"kind": "file"}, headers=h)).json()["id"]
    assert (await api.post(f"/v1/sources/{sid}/sync", headers=h)).status_code == 422


async def test_sync_missing_credential_is_422_not_500(
    api: AsyncClient, tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A token-based connector with no credential must surface a clean 422, not a 500.
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    h = {"X-Tenant": str(tenant)}
    sid = (await api.post("/v1/sources", json={"kind": "notion"}, headers=h)).json()["id"]
    resp = await api.post(f"/v1/sources/{sid}/sync", headers=h)
    assert resp.status_code == 422
    assert "NOTION_TOKEN" in resp.json()["detail"]


async def test_unknown_source_is_404(api: AsyncClient, tenant: uuid.UUID) -> None:
    h = {"X-Tenant": str(tenant)}
    assert (await api.delete(f"/v1/sources/{uuid.uuid4()}", headers=h)).status_code == 404


async def test_sources_flow_under_rls_enforce(
    api: AsyncClient, tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: with RLS enforced, the request session runs under cortex_app and
    # the tenant GUC is transaction-local. create_source must flush+read-back within
    # the same transaction (not commit first) or RLS fail-closes -> 500.
    monkeypatch.setenv("CORTEX_RLS_ENFORCE", "true")
    h = {"X-Tenant": str(tenant)}
    created = await api.post("/v1/sources", json={"kind": "sample"}, headers=h)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    synced = await api.post(f"/v1/sources/{sid}/sync", headers=h)
    assert synced.status_code == 200 and synced.json()["chunks"] > 0
    assert (await api.post("/v1/search", json={"q": "refund finance", "k": 3}, headers=h)).json()[
        "results"
    ]
    assert (await api.get("/v1/sources", headers=h)).json()["sources"][0]["kind"] == "sample"
