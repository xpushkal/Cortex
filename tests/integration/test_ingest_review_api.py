"""POST /v1/ingest/events and /v1/processes/{id}/review (M3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.api.main import app

pytestmark = pytest.mark.integration

_HEAD = "Vendor security policy for procurement of new tooling across the company here."
_DOC = (
    f"{_HEAD} New vendors over $10k require a security review and approval from "
    "the head of finance."
)


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_ingest_event_requires_tenant(api: AsyncClient) -> None:
    resp = await api.post(
        "/v1/ingest/events",
        json={"source_kind": "notion", "external_id": "x", "content": "hi"},
    )
    assert resp.status_code == 400


async def test_ingest_event_makes_change_retrievable(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    resp = await api.post(
        "/v1/ingest/events",
        json={
            "source_kind": "notion",
            "external_id": "vendor-doc",
            "kind": "page",
            "content": _DOC,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ingested"] == 1

    # Immediately queryable (the < 60s done-when path).
    search = await api.post(
        "/v1/search", json={"q": "vendor security review head of finance", "k": 5}, headers=headers
    )
    assert any("security review" in r["text"] for r in search.json()["results"])

    # Re-sending identical content is a no-op (idempotent).
    again = await api.post(
        "/v1/ingest/events",
        json={
            "source_kind": "notion",
            "external_id": "vendor-doc",
            "kind": "page",
            "content": _DOC,
        },
        headers=headers,
    )
    assert again.json()["ingested"] == 0
    assert again.json()["skipped"] == 1


async def test_review_approve_promotes_draft_to_active_fresh(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    # Ingest, then change → the process becomes draft + stale.
    await api.post(
        "/v1/ingest/events",
        json={
            "source_kind": "notion",
            "external_id": "vendor-doc",
            "kind": "page",
            "content": _DOC,
        },
        headers=headers,
    )
    changed = _DOC.replace("head of finance", "chief financial officer")
    await api.post(
        "/v1/ingest/events",
        json={
            "source_kind": "notion",
            "external_id": "vendor-doc",
            "kind": "page",
            "content": changed,
        },
        headers=headers,
    )
    listing = await api.get("/v1/processes", headers=headers)
    proc = listing.json()["processes"][0]
    assert proc["status"] == "draft"
    pid = proc["id"]

    # Approve → active again.
    review = await api.post(
        f"/v1/processes/{pid}/review", json={"action": "approve"}, headers=headers
    )
    assert review.status_code == 200
    after = await api.get("/v1/processes", headers=headers)
    assert after.json()["processes"][0]["status"] == "active"


async def test_review_unknown_process_404(api: AsyncClient, fresh_tenant: uuid.UUID) -> None:
    resp = await api.post(
        f"/v1/processes/{uuid.uuid4()}/review",
        json={"action": "approve"},
        headers={"X-Tenant": str(fresh_tenant)},
    )
    assert resp.status_code == 404
