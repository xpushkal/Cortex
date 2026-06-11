"""M6 done-when: an external agent grounded ONLY in the skills file routes a
$750 refund, with every action traceable to a cited process step.

End-to-end through the public surface: ingest → `GET /v1/skills` → validate
against the external `cortex-agent` schema → run the reference agent. No Cortex
internals touched by the agent — it sees only the skills file.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cortex.agent import ReferenceAgent, SkillsFile
from cortex.api.main import app

pytestmark = pytest.mark.eval

_REFUND_DOC = (
    "Refund handling policy for the billing and customer support teams here now. "
    "Refunds up to $500 can be issued directly by a support agent. "
    "Refunds over $500 are routed to the finance team for approval."
)


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _skills_file(api: AsyncClient, tenant: uuid.UUID) -> SkillsFile:
    await api.post(
        "/v1/ingest/events",
        json={
            "source_kind": "notion",
            "external_id": "refund",
            "kind": "page",
            "content": _REFUND_DOC,
        },
        headers={"X-Tenant": str(tenant)},
    )
    resp = await api.get("/v1/skills", headers={"X-Tenant": str(tenant)})
    assert resp.status_code == 200
    return SkillsFile.model_validate(resp.json())  # external wire contract


async def test_agent_routes_750_refund_grounded_in_cited_steps(
    api: AsyncClient, fresh_tenant: uuid.UUID
) -> None:
    skills = await _skills_file(api, fresh_tenant)

    # Given ONLY the skills file, the agent completes the scripted task.
    result = ReferenceAgent().run(skills, {"type": "refund", "amount_usd": 750})

    assert result.completed
    assert result.action is not None
    # Correctly routed to finance (not the support-agent auto-issue path).
    assert "finance" in result.action.decision.lower()
    # Every action is traceable to a cited process step.
    assert result.grounded
    cited = result.action.citations[0].chunk_id
    assert cited
    # The cited chunk is a real step in the skills file the agent was given.
    cited_chunks = {
        c.chunk_id for skill in skills.skills for step in skill.steps for c in step.citations
    }
    assert cited in cited_chunks


async def test_agent_auto_issues_small_refund(api: AsyncClient, fresh_tenant: uuid.UUID) -> None:
    skills = await _skills_file(api, fresh_tenant)
    result = ReferenceAgent().run(skills, {"type": "refund", "amount_usd": 300})
    assert result.completed
    assert result.action is not None
    # A $300 refund auto-issues via support — proving the agent reasons over the
    # cited threshold steps, not a hardcoded answer.
    assert "support agent" in result.action.decision.lower()
    assert result.grounded
