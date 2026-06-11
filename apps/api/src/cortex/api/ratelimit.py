"""Per-tenant ingress rate limiting (docs/API.md, ARCHITECTURE.md §7).

Two buckets keyed by tenant: `read` (`/search`, `/processes`) and `heavy`
(`/ask`, LLM-cost). Over-limit returns `429` with `Retry-After`. Opt-in via
`cortex_ratelimit` so shared test/dev runs aren't throttled; the limiter map is
module-level and patchable in tests.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException

from cortex.api.config import get_settings
from cortex.api.deps import tenant_id
from cortex.storage import RateLimiter, build_limiter


def _build_limiters() -> dict[str, RateLimiter]:
    settings = get_settings()
    if not settings.cortex_ratelimit:
        return {}
    url = settings.redis_url or None
    return {
        "read": build_limiter(
            settings.ratelimit_read_capacity,
            settings.ratelimit_read_refill_per_second,
            redis_url=url,
            namespace="rl:read",
        ),
        "heavy": build_limiter(
            settings.ratelimit_heavy_capacity,
            settings.ratelimit_heavy_refill_per_second,
            redis_url=url,
            namespace="rl:heavy",
        ),
    }


# Module-level so tests can inject a tiny limiter without rebuilding the app.
LIMITERS: dict[str, RateLimiter] = _build_limiters()


def rate_limit(bucket: str) -> Callable[[uuid.UUID], Awaitable[None]]:
    """A FastAPI dependency enforcing the per-tenant `bucket` limit (no-op if off)."""

    async def _dependency(tenant: Annotated[uuid.UUID, Depends(tenant_id)]) -> None:
        limiter = LIMITERS.get(bucket)
        if limiter is None:
            return
        ok, retry_after = await limiter.allow(str(tenant))
        if not ok:
            # A no-refill bucket reports an infinite wait; cap the advertised value.
            retry = math.ceil(retry_after) if math.isfinite(retry_after) else 60
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(max(1, retry))},
            )

    return _dependency
