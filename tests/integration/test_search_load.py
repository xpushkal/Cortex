"""In-process load smoke for /v1/search (docs/SCALE.md).

Not the throughput proof — that's `scripts/load_test.py` against a real
deployment. This is a runnable guardrail: fire many concurrent searches at the
ASGI app over the seeded corpus and assert zero errors and a generous p95 budget,
so a latency regression in the hot path is caught. Marked `load` only, so it stays
out of both the unit and the integration PR lanes; run it with `-m load`
(`just loadtest-smoke`). The integration conftest's infra guard still applies, so
it skips when Postgres/Qdrant are down.
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.api.main import app

pytestmark = pytest.mark.load

_REQUESTS = 200
_CONCURRENCY = 16
_P95_BUDGET_MS = 750.0  # generous; in-process over the small corpus is ~tens of ms


async def test_search_p95_under_budget(seeded_tenant: uuid.UUID) -> None:
    headers = {"X-Tenant": str(seeded_tenant)}
    payload = {"q": "refund approval over 500 finance", "k": 10}
    latencies: list[float] = []
    errors = 0

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=10.0) as client:
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def one() -> None:
            nonlocal errors
            async with sem:
                start = time.monotonic()
                resp = await client.post("/v1/search", json=payload, headers=headers)
                latencies.append((time.monotonic() - start) * 1000)
                if resp.status_code != 200:
                    errors += 1

        await asyncio.gather(*(one() for _ in range(_REQUESTS)))

    latencies.sort()
    p95 = latencies[int(0.95 * len(latencies))]
    assert errors == 0, f"{errors} non-200 responses under load"
    assert p95 < _P95_BUDGET_MS, f"p95 {p95:.1f}ms exceeded budget {_P95_BUDGET_MS}ms"
    print(
        f"\nin-process /v1/search x{_CONCURRENCY}: "
        f"p95={p95:.1f}ms mean={statistics.mean(latencies):.1f}ms"
    )
