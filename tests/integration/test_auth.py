"""Bearer-token auth and tenant binding (docs/API.md).

Default mode trusts X-Tenant; with CORTEX_AUTH_REQUIRED the tenant is derived
from the per-tenant token and X-Tenant (if sent) must match.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from cortex.api.auth import mint_api_key
from cortex.api.main import app
from cortex.storage import ApiKey, get_sessionmaker

pytestmark = pytest.mark.integration

_PROCESSES = "/v1/processes"


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def tenant_with_key() -> AsyncIterator[tuple[uuid.UUID, str]]:
    tenant = uuid.uuid4()
    token = await mint_api_key(tenant, "test")
    yield tenant, token
    async with get_sessionmaker()() as session:
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant))
        await session.commit()


async def test_default_mode_trusts_x_tenant(api: AsyncClient) -> None:
    # Auth off (default): X-Tenant resolves the tenant; missing header is a 400.
    ok = await api.get(_PROCESSES, headers={"X-Tenant": str(uuid.uuid4())})
    assert ok.status_code == 200
    assert (await api.get(_PROCESSES)).status_code == 400


async def test_auth_required_rejects_missing_and_bad_tokens(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORTEX_AUTH_REQUIRED", "true")
    assert (await api.get(_PROCESSES)).status_code == 401
    bad = await api.get(_PROCESSES, headers={"Authorization": "Bearer ctx_nope"})
    assert bad.status_code == 401


async def test_auth_required_derives_tenant_from_token(
    api: AsyncClient, tenant_with_key: tuple[uuid.UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORTEX_AUTH_REQUIRED", "true")
    tenant, token = tenant_with_key
    auth = {"Authorization": f"Bearer {token}"}

    # Valid token, no X-Tenant: tenant comes from the token.
    assert (await api.get(_PROCESSES, headers=auth)).status_code == 200
    # Matching X-Tenant is accepted.
    match = await api.get(_PROCESSES, headers={**auth, "X-Tenant": str(tenant)})
    assert match.status_code == 200
    # Mismatched X-Tenant is rejected.
    mismatch = await api.get(_PROCESSES, headers={**auth, "X-Tenant": str(uuid.uuid4())})
    assert mismatch.status_code == 403
