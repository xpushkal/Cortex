"""Periodic TTL sweep — expire knowledge past its TTL (docs/INGESTION.md §5).

A standalone job, run on a schedule (cron / arq beat): it flips every freshness
row whose `last_validated_at + ttl_seconds` is in the past to `expired`, so
stale-by-age knowledge stops being served as current. Idempotent.

CLI: `python -m cortex.workers.freshness_sweep`.
"""

from __future__ import annotations

import asyncio

from cortex.knowledge import ttl_sweep
from cortex.obs import get_tracer, init_tracing
from cortex.storage import get_sessionmaker

_tracer = get_tracer(__name__)


async def run_sweep(dsn: str | None = None) -> int:
    """Run one TTL sweep; returns the number of objects expired."""
    with _tracer.start_as_current_span("freshness.ttl_sweep") as span:
        async with get_sessionmaker(dsn)() as session:
            expired = await ttl_sweep(session)
            await session.commit()
        span.set_attribute("cortex.expired", expired)
    return expired


def main() -> None:
    init_tracing("cortex-workers")
    expired = asyncio.run(run_sweep())
    print(f"freshness sweep: expired {expired} objects")


if __name__ == "__main__":
    main()
