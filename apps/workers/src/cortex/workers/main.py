"""arq worker entrypoint. Run with `arq cortex.workers.main.WorkerSettings`.

Drains the ingest queue and runs the per-artifact pipeline (`run_pipeline`). The
freshness TTL sweep runs as a cron job. Redis is configured from `REDIS_URL`.
"""

from __future__ import annotations

from typing import ClassVar

from arq import cron

from cortex.workers.freshness_sweep import run_sweep
from cortex.workers.pipeline import run_pipeline
from cortex.workers.queue import QUEUE_NAME, redis_settings


async def _freshness_sweep(ctx: object) -> int:
    """Cron wrapper: expire knowledge past its TTL (docs/INGESTION.md §6)."""
    return await run_sweep()


class WorkerSettings:
    """arq worker configuration."""

    functions: ClassVar[list[object]] = [run_pipeline]
    cron_jobs: ClassVar[list[object]] = [cron(_freshness_sweep, hour={0, 6, 12, 18}, minute=0)]
    redis_settings = redis_settings()
    queue_name = QUEUE_NAME
    max_jobs = 10
    job_timeout = 300  # seconds; embedding + extraction over an artifact's chunks
