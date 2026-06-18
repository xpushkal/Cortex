"""arq worker entrypoint. Run with `arq cortex.workers.main.WorkerSettings`.

Drains one priority lane (`CORTEX_WORKER_QUEUE`, default realtime) and runs the
per-artifact pipeline (`run_pipeline`). Run one worker per lane — give realtime the
most concurrency so backfills never starve live updates. The freshness TTL sweep
runs as a cron job. Redis is configured from `REDIS_URL`.
"""

from __future__ import annotations

import os
from typing import ClassVar

from arq import cron

from cortex.workers.freshness_sweep import run_sweep
from cortex.workers.pipeline import MAX_TRIES, run_pipeline
from cortex.workers.queue import QUEUE_REALTIME, redis_settings


async def _freshness_sweep(ctx: object) -> int:
    """Cron wrapper: expire knowledge past its TTL (docs/INGESTION.md §6)."""
    return await run_sweep()


class WorkerSettings:
    """arq worker configuration."""

    functions: ClassVar[list[object]] = [run_pipeline]
    cron_jobs: ClassVar[list[object]] = [cron(_freshness_sweep, hour={0, 6, 12, 18}, minute=0)]
    redis_settings = redis_settings()
    # The lane this worker drains. Run one worker per lane (realtime/backfill/reprocess).
    queue_name = os.environ.get("CORTEX_WORKER_QUEUE", QUEUE_REALTIME)
    max_jobs = 10
    job_timeout = 300  # seconds; embedding + extraction over an artifact's chunks
    max_tries = MAX_TRIES  # aligns with run_pipeline's dead-letter threshold
    retry_jobs = True
