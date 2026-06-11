"""Redis token-bucket limiter against live Redis (M4)."""

from __future__ import annotations

import os
import uuid

import pytest

from cortex.storage.ratelimit import build_limiter

pytestmark = pytest.mark.integration

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(autouse=True)
async def _require_redis() -> None:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(_REDIS_URL)
        await client.ping()
        await client.aclose()
    except Exception as exc:
        pytest.skip(f"redis unavailable: {exc}")


async def test_redis_limiter_blocks_after_capacity() -> None:
    limiter = build_limiter(3, 0.0, redis_url=_REDIS_URL, namespace=f"test:{uuid.uuid4()}")
    key = "tenant-a"
    oks = [(await limiter.allow(key))[0] for _ in range(4)]
    assert oks == [True, True, True, False]
    _, retry = await limiter.allow(key)
    assert retry > 0


async def test_redis_limiter_is_per_key() -> None:
    limiter = build_limiter(1, 0.0, redis_url=_REDIS_URL, namespace=f"test:{uuid.uuid4()}")
    assert (await limiter.allow("a"))[0] is True
    assert (await limiter.allow("a"))[0] is False
    assert (await limiter.allow("b"))[0] is True
