"""The enqueue seam shared by the API and the arq worker (docs/INGESTION.md §2).

Two backends, selected by `CORTEX_WORKER_ASYNC`:
  - async (production): push a `run_pipeline` job onto a Redis lane so the caller
    returns immediately and a worker drains it.
  - inline (tests/dev, the default): `await` the pipeline directly — no Redis is
    touched — so read-after-write holds for callers that query right after ingest.

Priority lanes (docs/INGESTION.md §4): `realtime` (webhook deltas) > `backfill`
(history pulls) > `reprocess` (DLQ replays). Each lane is its own arq queue; run a
worker per lane (`CORTEX_WORKER_QUEUE`) and give realtime the most concurrency so
large backfills never starve live updates.

`REDIS_URL` configures the pool (default `redis://localhost:6379/0`), matching the
`redis_url` setting the API already exposes.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from pydantic import BaseModel

from cortex.connectors.base import Connector, SourceConfig
from cortex.workers.pipeline import run_pipeline

QUEUE_REALTIME = "cortex:realtime"
QUEUE_BACKFILL = "cortex:backfill"
QUEUE_REPROCESS = "cortex:reprocess"
QUEUE_NAME = QUEUE_REALTIME  # default lane for the live/event path
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_TRUE = {"1", "true", "yes", "on"}


class EnqueueResult(BaseModel):
    job_id: str
    status: str  # queued (async) | completed (inline)


def worker_async_enabled() -> bool:
    """True when ingestion should be enqueued to arq rather than run inline."""
    return os.environ.get("CORTEX_WORKER_ASYNC", "").lower() in _TRUE


def redis_settings() -> RedisSettings:
    """arq Redis settings from `REDIS_URL` (shared by the pool and the worker)."""
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", _DEFAULT_REDIS_URL))


async def get_arq_pool() -> ArqRedis:
    """Open an arq connection pool. Caller owns its lifecycle (close on shutdown)."""
    return await create_pool(redis_settings())


async def enqueue_ingest_event(
    *,
    tenant_id: uuid.UUID | str,
    source_kind: str,
    external_id: str,
    kind: str,
    content: str,
    pool: ArqRedis | None = None,
    queue: str = QUEUE_REALTIME,
) -> EnqueueResult:
    """Enqueue (async) or run (inline) the per-artifact pipeline for one event.

    In async mode a shared `pool` is reused when provided; otherwise a short-lived
    pool is opened and closed. In inline mode the pipeline runs in-process.
    """
    payload: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "source_kind": source_kind,
        "external_id": external_id,
        "kind": kind,
        "content": content,
    }

    if worker_async_enabled():
        owns_pool = pool is None
        client = pool or await get_arq_pool()
        try:
            job = await client.enqueue_job("run_pipeline", _queue_name=queue, **payload)
            job_id = job.job_id if job is not None else f"dup:{uuid.uuid4()}"
            return EnqueueResult(job_id=job_id, status="queued")
        finally:
            if owns_pool:
                await client.close()

    await run_pipeline(None, **payload)
    return EnqueueResult(job_id=f"inline:{uuid.uuid4()}", status="completed")


async def enqueue_backfill(
    connector: Connector,
    *,
    tenant_id: uuid.UUID | str,
    pool: ArqRedis | None = None,
) -> int:
    """Fan a connector's backfill out as per-artifact jobs on the backfill lane.

    The async counterpart to the synchronous `ingest_source` CLI: it normalizes
    each raw item and enqueues one `run_pipeline` job, so history pulls drain
    through the worker without blocking. Returns the number of jobs enqueued.
    """
    cfg = SourceConfig(kind=connector.kind)
    owns_pool = pool is None
    client = pool or await get_arq_pool()
    count = 0
    try:
        for raw in connector.backfill(cfg):
            art = connector.normalize(raw)
            await client.enqueue_job(
                "run_pipeline",
                _queue_name=QUEUE_BACKFILL,
                tenant_id=str(tenant_id),
                source_kind=art.source_kind,
                external_id=art.external_id,
                kind=art.kind,
                content=art.content,
            )
            count += 1
    finally:
        if owns_pool:
            await client.close()
    return count
