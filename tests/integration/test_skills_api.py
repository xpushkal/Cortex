"""GET /v1/skills export (M6) — shape, schema validity, freshness, isolation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.agent import SkillsFile  # the external consumer's wire contract
from cortex.api.main import app

pytestmark = pytest.mark.integration

_REFUND = (
    "Refund handling policy for the billing team and customer support here now. "
    "Refunds up to $500 can be issued by a support agent. Refunds over $500 are "
    "routed to the finance team for approval."
)


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_skills_requires_tenant(api: AsyncClient) -> None:
    assert (await api.get("/v1/skills")).status_code == 400


async def test_skills_export_validates_against_schema(
    api: AsyncClient, seeded_tenant: uuid.UUID
) -> None:
    resp = await api.get("/v1/skills", headers={"X-Tenant": str(seeded_tenant)})
    assert resp.status_code == 200
    # The export validates against the schema an external agent codes against.
    skills_file = SkillsFile.model_validate(resp.json())
    assert skills_file.tenant == str(seeded_tenant)
    assert skills_file.skills
    # Every shipped skill is fresh + every step carries a citation (the guarantee).
    for skill in skills_file.skills:
        assert skill.freshness == "fresh"
        assert all(step.citations for step in skill.steps)
    manifest = skills_file.freshness_manifest
    assert manifest.fresh >= len(skills_file.skills)


async def test_changed_process_drops_from_default_export_until_requested(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    headers = {"X-Tenant": str(fresh_tenant)}
    body = {"source_kind": "notion", "external_id": "refund", "kind": "page"}
    await api.post("/v1/ingest/events", json={**body, "content": _REFUND}, headers=headers)

    default = SkillsFile.model_validate((await api.get("/v1/skills", headers=headers)).json())
    assert len(default.skills) == 1  # fresh + active

    # A source change makes the process stale (draft) -> excluded by default.
    changed = _REFUND.replace("finance team", "VP of Sales")
    await api.post("/v1/ingest/events", json={**body, "content": changed}, headers=headers)
    after = SkillsFile.model_validate((await api.get("/v1/skills", headers=headers)).json())
    assert after.skills == []
    assert after.freshness_manifest.stale == 1

    # ...but surfaced (labeled stale) when explicitly requested.
    with_stale = SkillsFile.model_validate(
        (await api.get("/v1/skills?include_stale=true", headers=headers)).json()
    )
    assert len(with_stale.skills) == 1
    assert with_stale.skills[0].freshness == "stale"


async def test_skills_tenant_isolated(api: AsyncClient, seeded_tenant: uuid.UUID) -> None:
    other = uuid.uuid4()
    resp = await api.get("/v1/skills", headers={"X-Tenant": str(other)})
    assert resp.status_code == 200
    assert resp.json()["skills"] == []
