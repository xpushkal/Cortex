"""Token-bucket rate limiter — in-memory primitive (M4)."""

from __future__ import annotations

import asyncio

import pytest

from cortex.storage.ratelimit import InMemoryRateLimiter


async def test_allows_up_to_capacity_then_blocks() -> None:
    limiter = InMemoryRateLimiter(capacity=3, refill_per_second=0.0)
    results = [await limiter.allow("tenant-a") for _ in range(4)]
    assert [ok for ok, _ in results] == [True, True, True, False]
    _, retry = results[-1]
    assert retry == float("inf")  # no refill configured


async def test_buckets_are_per_key() -> None:
    limiter = InMemoryRateLimiter(capacity=1, refill_per_second=0.0)
    assert (await limiter.allow("a"))[0] is True
    assert (await limiter.allow("a"))[0] is False
    # A different key has its own bucket.
    assert (await limiter.allow("b"))[0] is True


async def test_refill_restores_tokens() -> None:
    limiter = InMemoryRateLimiter(capacity=1, refill_per_second=50.0)
    assert (await limiter.allow("a"))[0] is True
    blocked, retry = await limiter.allow("a")
    assert blocked is False
    assert 0 < retry <= 1.0
    await asyncio.sleep(retry + 0.02)
    assert (await limiter.allow("a"))[0] is True


@pytest.mark.parametrize("cost", [2, 3])
async def test_cost_greater_than_one(cost: int) -> None:
    limiter = InMemoryRateLimiter(capacity=3, refill_per_second=0.0)
    assert (await limiter.allow("a", cost=cost))[0] is True
    # Remaining tokens (3-cost) are fewer than another `cost`.
    assert (await limiter.allow("a", cost=cost))[0] is False
