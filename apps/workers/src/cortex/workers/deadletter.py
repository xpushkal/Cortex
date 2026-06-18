"""Dead-letter capture for ingestion jobs (docs/INGESTION.md §2).

A job that still fails after `MAX_TRIES` is pushed to a Redis list rather than
silently lost, so it can be inspected and replayed. Kept dependency-light (only
redis list ops + JSON) so `pipeline` can import it without an import cycle.

CLI: `python -m cortex.workers.deadletter list|requeue`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

DEAD_LETTER_KEY = "cortex:dead"


async def record_dead_letter(redis: Any, *, payload: dict[str, Any], error: str) -> None:
    """Append a permanently-failed job (its enqueue payload + error) to the DLQ."""
    item = json.dumps(
        {"payload": payload, "error": error, "failed_at": datetime.now(UTC).isoformat()}
    )
    await redis.rpush(DEAD_LETTER_KEY, item)


async def list_dead_letters(redis: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return up to `limit` dead-lettered jobs (oldest first), without removing them."""
    raw = await redis.lrange(DEAD_LETTER_KEY, 0, limit - 1)
    return [json.loads(x) for x in raw]


async def requeue_dead_letters(redis: Any, *, queue: str) -> int:
    """Pop every dead-lettered job and re-enqueue it onto `queue`. Returns the count."""
    count = 0
    while True:
        item = await redis.lpop(DEAD_LETTER_KEY)
        if item is None:
            break
        await redis.enqueue_job("run_pipeline", _queue_name=queue, **json.loads(item)["payload"])
        count += 1
    return count


def main() -> None:
    from cortex.workers.queue import QUEUE_REPROCESS, get_arq_pool

    parser = argparse.ArgumentParser(description="Inspect / replay the ingestion DLQ.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show dead-lettered jobs")
    sub.add_parser("requeue", help="re-enqueue all dead-lettered jobs onto the reprocess lane")
    args = parser.parse_args()

    async def _run() -> None:
        pool = await get_arq_pool()
        try:
            if args.cmd == "list":
                for d in await list_dead_letters(pool):
                    print(f"{d['failed_at']}  {d['error']}  {d['payload']}")
            elif args.cmd == "requeue":
                n = await requeue_dead_letters(pool, queue=QUEUE_REPROCESS)
                print(f"requeued {n} job(s) onto {QUEUE_REPROCESS}")
        finally:
            await pool.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
