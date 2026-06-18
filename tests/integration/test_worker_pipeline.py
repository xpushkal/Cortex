"""The arq worker seam: run_pipeline runs the pipeline; the API enqueues it.

Covers the thin async wrap (docs/INGESTION.md §2): run_pipeline wraps the tested
ingest_event, the inline backend preserves read-after-write, and async mode pushes
a job to the pool without touching the pipeline.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from cortex.api.main import app
from cortex.storage import Chunk, get_sessionmaker
from cortex.workers.pipeline import run_pipeline
from cortex.workers.queue import enqueue_ingest_event

pytestmark = pytest.mark.integration

_DOC = (
    "Refunds up to $500 can be issued by a support agent. Refunds over $500 are "
    "routed to the finance team for approval."
)


async def _chunk_count(tenant_id: uuid.UUID) -> int:
    async with get_sessionmaker()() as session:
        return (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.tenant_id == tenant_id)
            )
        ).scalar_one()


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_run_pipeline_ingests_one_artifact(fresh_tenant: uuid.UUID) -> None:
    stats = await run_pipeline(
        None,
        tenant_id=str(fresh_tenant),
        source_kind="sample",
        external_id="wp-1",
        kind="doc",
        content=_DOC,
    )
    assert stats["artifacts"] == 1
    assert stats["chunks"] > 0
    assert await _chunk_count(fresh_tenant) > 0


async def test_inline_enqueue_completes_and_is_queryable(fresh_tenant: uuid.UUID) -> None:
    # Async disabled (the default): the helper runs inline and the data lands now.
    result = await enqueue_ingest_event(
        tenant_id=fresh_tenant,
        source_kind="sample",
        external_id="wp-2",
        kind="doc",
        content=_DOC,
    )
    assert result.status == "completed"
    assert result.job_id.startswith("inline:")
    assert await _chunk_count(fresh_tenant) > 0


async def test_async_enqueue_pushes_job_without_running_pipeline(
    fresh_tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORTEX_WORKER_ASYNC", "true")
    calls: list[tuple[str, dict[str, object]]] = []

    class _FakePool:
        async def enqueue_job(self, name: str, *, _queue_name: str, **kwargs: object) -> object:
            calls.append((name, {"_queue_name": _queue_name, **kwargs}))
            return type("Job", (), {"job_id": "job-123"})()

    result = await enqueue_ingest_event(
        tenant_id=fresh_tenant,
        source_kind="sample",
        external_id="wp-3",
        kind="doc",
        content=_DOC,
        pool=_FakePool(),
    )

    assert result.status == "queued"
    assert result.job_id == "job-123"
    assert calls == [
        (
            "run_pipeline",
            {
                "_queue_name": "cortex:realtime",
                "tenant_id": str(fresh_tenant),
                "source_kind": "sample",
                "external_id": "wp-3",
                "kind": "doc",
                "content": _DOC,
            },
        )
    ]
    # Async mode must not have run the pipeline in-process.
    assert await _chunk_count(fresh_tenant) == 0


async def test_endpoint_returns_202_with_job_id(api: AsyncClient, fresh_tenant: uuid.UUID) -> None:
    resp = await api.post(
        "/v1/ingest/events",
        json={"source_kind": "sample", "external_id": "wp-4", "kind": "doc", "content": _DOC},
        headers={"X-Tenant": str(fresh_tenant)},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["status"] == "completed"  # inline default
    assert await _chunk_count(fresh_tenant) > 0
