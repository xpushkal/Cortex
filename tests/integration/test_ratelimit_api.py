"""Per-tenant ingress rate limiting on the API (M4): 429 + Retry-After."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

import cortex.api.ratelimit as rl
from cortex.api.main import app
from cortex.storage.ratelimit import InMemoryRateLimiter

pytestmark = pytest.mark.integration


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def tiny_read_limiter() -> AsyncIterator[None]:
    """Inject a 2-token, no-refill read bucket; restore afterwards."""
    saved = dict(rl.LIMITERS)
    rl.LIMITERS["read"] = InMemoryRateLimiter(capacity=2, refill_per_second=0.0)
    yield
    rl.LIMITERS.clear()
    rl.LIMITERS.update(saved)


async def test_search_429s_past_quota(
    api: AsyncClient, fresh_tenant: uuid.UUID, tiny_read_limiter: None
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    body = {"q": "anything", "k": 3}
    assert (await api.post("/v1/search", json=body, headers=headers)).status_code == 200
    assert (await api.post("/v1/search", json=body, headers=headers)).status_code == 200
    blocked = await api.post("/v1/search", json=body, headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


async def test_limit_is_per_tenant(
    api: AsyncClient, fresh_tenant: uuid.UUID, tiny_read_limiter: None
) -> None:
    a = {"X-Tenant": str(fresh_tenant)}
    b = {"X-Tenant": str(uuid.uuid4())}
    body = {"q": "anything", "k": 3}
    # Exhaust tenant A.
    await api.post("/v1/search", json=body, headers=a)
    await api.post("/v1/search", json=body, headers=a)
    assert (await api.post("/v1/search", json=body, headers=a)).status_code == 429
    # Tenant B is unaffected — separate bucket.
    assert (await api.post("/v1/search", json=body, headers=b)).status_code == 200


async def test_limiting_off_by_default(api: AsyncClient, fresh_tenant: uuid.UUID) -> None:
    # No limiter injected (default config) -> no throttling.
    headers = {"X-Tenant": str(fresh_tenant)}
    for _ in range(5):
        assert (
            await api.post("/v1/search", json={"q": "x", "k": 1}, headers=headers)
        ).status_code == 200
