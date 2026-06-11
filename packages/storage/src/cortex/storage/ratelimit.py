"""Token-bucket rate limiting (docs/ARCHITECTURE.md §7).

Two layers share this primitive: per-tenant **ingress** limits on the API and
per-source **egress** limits in ingestion. `allow(key)` returns
`(ok, retry_after_seconds)`; `key` is the tenant id (ingress) or source kind
(egress).

  - InMemoryRateLimiter: process-local; for unit tests and key-free local runs.
  - RedisRateLimiter: an atomic Lua refill-and-consume, correct under
    concurrency across replicas — the production limiter.

`build_limiter(...)` picks Redis when a URL is given, else in-memory.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Protocol


class RateLimiter(Protocol):
    async def allow(self, key: str, cost: int = 1) -> tuple[bool, float]:
        """Try to consume `cost` tokens for `key`. Returns (allowed, retry_after_s)."""
        ...


class InMemoryRateLimiter:
    """Process-local token bucket. Not shared across replicas — tests/dev only."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self._capacity = float(capacity)
        self._refill = refill_per_second
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

    async def allow(self, key: str, cost: int = 1) -> tuple[bool, float]:
        now = time.monotonic()
        tokens, last = self._state.get(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._refill)
        if tokens >= cost:
            self._state[key] = (tokens - cost, now)
            return True, 0.0
        self._state[key] = (tokens, now)
        retry = (cost - tokens) / self._refill if self._refill > 0 else float("inf")
        return False, retry


# Atomic refill-and-consume. KEYS[1]=bucket; ARGV=capacity, refill/s, now_s, cost.
_LUA = """
local d = redis.call('HMGET', KEYS[1], 't', 's')
local tokens = tonumber(d[1])
local ts = tonumber(d[2])
local cap = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
if tokens == nil then tokens = cap; ts = now end
tokens = math.min(cap, tokens + math.max(0, now - ts) * refill)
local allowed = 0
local retry = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry = (cost - tokens) / refill
end
redis.call('HMSET', KEYS[1], 't', tokens, 's', now)
local ttl
if refill > 0 then ttl = math.ceil((cap / refill) * 1000) + 1000 else ttl = 3600000 end
redis.call('PEXPIRE', KEYS[1], ttl)
return {allowed, tostring(retry)}
"""


class RedisRateLimiter:
    """Distributed token bucket via an atomic Lua script — the production limiter."""

    def __init__(
        self, redis: object, capacity: int, refill_per_second: float, namespace: str = "rl"
    ) -> None:
        self._redis = redis
        self._capacity = capacity
        self._refill = refill_per_second
        self._ns = namespace

    async def allow(self, key: str, cost: int = 1) -> tuple[bool, float]:
        allowed, retry = await self._redis.eval(  # type: ignore[attr-defined]
            _LUA,
            1,
            f"{self._ns}:{key}",
            self._capacity,
            self._refill,
            time.time(),
            cost,
        )
        return bool(int(allowed)), float(retry)


def build_limiter(
    capacity: int,
    refill_per_second: float,
    *,
    redis_url: str | None = None,
    namespace: str = "rl",
) -> RateLimiter:
    """Redis-backed limiter when `redis_url` is set, else in-memory."""
    if redis_url:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        return RedisRateLimiter(client, capacity, refill_per_second, namespace=namespace)
    return InMemoryRateLimiter(capacity, refill_per_second)


async def acquire(
    limiter: RateLimiter, key: str, *, cost: int = 1, max_wait: float = 30.0
) -> float:
    """Block (sleeping on the bucket's refill) until `cost` tokens are available.

    The egress path: a connector waits for its per-source quota rather than being
    rejected. Returns the seconds waited; raises `TimeoutError` if the wait would
    exceed `max_wait` (or the bucket can never refill), so a misconfigured bucket
    fails loudly instead of hanging.
    """
    waited = 0.0
    while True:
        ok, retry = await limiter.allow(key, cost)
        if ok:
            return waited
        if not math.isfinite(retry) or waited + retry > max_wait:
            raise TimeoutError(f"egress rate-limit budget exceeded for {key!r}")
        await asyncio.sleep(retry)
        waited += retry
