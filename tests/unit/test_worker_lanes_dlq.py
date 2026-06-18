"""Priority lanes, backfill enqueue, and dead-letter handling (no infra)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from arq import Retry

from cortex.connectors import SampleConnector
from cortex.workers import deadletter, pipeline, queue


class _FakePool:
    """Records enqueue_job calls and backs a Redis list for DLQ tests."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []
        self.lists: dict[str, list[str]] = {}

    async def enqueue_job(self, name: str, *, _queue_name: str, **kwargs: Any) -> object:
        self.jobs.append((_queue_name, {"function": name, **kwargs}))
        return type("Job", (), {"job_id": f"job-{len(self.jobs)}"})()

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        return self.lists.get(key, [])[start : (None if end == -1 else end + 1)]

    async def lpop(self, key: str) -> str | None:
        items = self.lists.get(key, [])
        return items.pop(0) if items else None


async def test_enqueue_backfill_fans_out_to_backfill_lane() -> None:
    pool = _FakePool()
    tenant = uuid.uuid4()
    n = await queue.enqueue_backfill(SampleConnector(), tenant_id=tenant, pool=pool)

    assert n == len(pool.jobs) > 0
    assert {q for q, _ in pool.jobs} == {queue.QUEUE_BACKFILL}
    job = pool.jobs[0][1]
    assert job["function"] == "run_pipeline"
    assert job["tenant_id"] == str(tenant)
    assert job["source_kind"] == "sample"


async def test_enqueue_event_routes_to_realtime_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORTEX_WORKER_ASYNC", "true")
    pool = _FakePool()
    res = await queue.enqueue_ingest_event(
        tenant_id=uuid.uuid4(),
        source_kind="sample",
        external_id="x",
        kind="doc",
        content="hi",
        pool=pool,
    )
    assert res.status == "queued"
    assert pool.jobs[0][0] == queue.QUEUE_REALTIME


async def test_run_pipeline_retries_then_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(**_: Any) -> None:
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(pipeline, "ingest_event", _boom)
    args = {
        "tenant_id": str(uuid.uuid4()),
        "source_kind": "sample",
        "external_id": "x",
        "kind": "doc",
    }

    # Inline (ctx None): the failure is surfaced to the caller.
    with pytest.raises(RuntimeError):
        await pipeline.run_pipeline(None, content="c", **args)

    # Worker, not yet final attempt: raises arq.Retry so arq re-queues the job.
    with pytest.raises(Retry):
        await pipeline.run_pipeline({"job_try": 1, "redis": _FakePool()}, content="c", **args)

    # Worker, final attempt: records to the DLQ and completes.
    pool = _FakePool()
    result = await pipeline.run_pipeline(
        {"job_try": pipeline.MAX_TRIES, "redis": pool}, content="c", **args
    )
    assert result["dead_lettered"] is True
    assert len(pool.lists[deadletter.DEAD_LETTER_KEY]) == 1


async def test_dead_letter_list_and_requeue_roundtrip() -> None:
    pool = _FakePool()
    payload = {
        "tenant_id": str(uuid.uuid4()),
        "source_kind": "sample",
        "external_id": "x",
        "kind": "doc",
        "content": "c",
    }
    await deadletter.record_dead_letter(pool, payload=payload, error="boom")

    listed = await deadletter.list_dead_letters(pool)
    assert listed[0]["payload"] == payload and listed[0]["error"] == "boom"

    n = await deadletter.requeue_dead_letters(pool, queue=queue.QUEUE_REPROCESS)
    assert n == 1
    assert pool.jobs[0][0] == queue.QUEUE_REPROCESS
    assert pool.lists[deadletter.DEAD_LETTER_KEY] == []  # drained
