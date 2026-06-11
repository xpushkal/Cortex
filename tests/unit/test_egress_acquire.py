"""Egress acquire: block-until-token semantics + budget guard (M4)."""

from __future__ import annotations

import time

import pytest

from cortex.storage.ratelimit import InMemoryRateLimiter, acquire


async def test_acquire_returns_immediately_when_tokens_available() -> None:
    limiter = InMemoryRateLimiter(capacity=5, refill_per_second=0.0)
    waited = await acquire(limiter, "slack")
    assert waited == 0.0


async def test_acquire_waits_for_refill() -> None:
    limiter = InMemoryRateLimiter(capacity=1, refill_per_second=50.0)
    await acquire(limiter, "slack")  # spends the only token
    start = time.monotonic()
    waited = await acquire(limiter, "slack")  # must wait ~1/50s for a refill
    assert waited > 0
    assert time.monotonic() - start >= waited * 0.5


async def test_acquire_raises_when_budget_exceeded() -> None:
    limiter = InMemoryRateLimiter(capacity=1, refill_per_second=0.0)  # never refills
    await acquire(limiter, "slack")
    with pytest.raises(TimeoutError, match="egress rate-limit budget exceeded"):
        await acquire(limiter, "slack", max_wait=0.5)
