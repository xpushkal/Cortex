"""Reference agent grounded in the skills file (M6)."""

from __future__ import annotations

import pytest

from cortex.agent import ReferenceAgent, get_agent
from cortex.agent.reference import LlmAgent
from cortex.agent.schema import (
    FreshnessManifest,
    Skill,
    SkillCitation,
    SkillsFile,
    SkillStep,
)

# A skills file as /v1/skills would emit it: the refund process, cited.
REFUND_SKILL = Skill(
    name="Refund policy. Refunds up to $500 ...",
    trigger="A refund is requested",
    version=1,
    freshness="fresh",
    steps=[
        SkillStep(
            action="Refunds up to $500 can be issued directly by a support agent.",
            actor="support agent",
            citations=[SkillCitation(chunk_id="chunk-a")],
        ),
        SkillStep(
            action="Any refund over $500 must be routed to the finance team for approval.",
            actor="finance team",
            citations=[SkillCitation(chunk_id="chunk-b")],
        ),
    ],
)
SKILLS = SkillsFile(
    tenant="demo",
    generated_at="2026-06-11T00:00:00Z",
    freshness_manifest=FreshnessManifest(fresh=1),
    skills=[REFUND_SKILL],
)


def test_routes_750_refund_to_finance_with_citation() -> None:
    result = ReferenceAgent().run(SKILLS, {"type": "refund", "amount_usd": 750})
    assert result.completed
    assert result.action is not None
    assert "finance" in result.action.decision.lower()
    assert result.action.actor == "finance team"
    # The done-when: every action is traceable to a cited process step.
    assert result.grounded
    assert result.action.citations[0].chunk_id == "chunk-b"


def test_small_refund_auto_issues_via_support() -> None:
    result = ReferenceAgent().run(SKILLS, {"type": "refund", "amount_usd": 300})
    assert result.completed
    assert result.action is not None
    assert "support agent" in result.action.decision.lower()
    assert result.action.citations[0].chunk_id == "chunk-a"


def test_searches_across_multiple_matching_skills() -> None:
    # Regression (found running live): a refund *thread* skill with no threshold
    # step is ordered before the refund *policy*. The agent must keep looking
    # past it to the skill that actually has an applicable cited step.
    thread = Skill(
        name="alice: a customer is asking for a $750 refund on order 18233",
        trigger="refund",
        version=1,
        freshness="fresh",
        steps=[
            SkillStep(
                action="Once approved, support issues the refund from the admin panel.",
                citations=[SkillCitation(chunk_id="thread-1")],
            )
        ],
    )
    skills = SkillsFile(
        tenant="demo",
        generated_at="t",
        freshness_manifest=FreshnessManifest(fresh=2),
        skills=[thread, REFUND_SKILL],  # thread first, like the live collation order
    )
    result = ReferenceAgent().run(skills, {"type": "refund", "amount_usd": 750})
    assert result.completed
    assert result.action is not None
    assert "finance" in result.action.decision.lower()
    assert result.action.citations[0].chunk_id == "chunk-b"


def test_unsupported_task_not_completed() -> None:
    result = ReferenceAgent().run(SKILLS, {"type": "payroll"})
    assert not result.completed
    assert result.action is None


def test_agent_only_acts_on_cited_steps() -> None:
    # A skill whose applicable step has NO citation must not be acted on.
    uncited = SkillsFile(
        tenant="demo",
        generated_at="t",
        freshness_manifest=FreshnessManifest(),
        skills=[
            Skill(
                name="refund",
                trigger="refund",
                version=1,
                freshness="fresh",
                steps=[SkillStep(action="Refunds over $500 go to finance.", citations=[])],
            )
        ],
    )
    result = ReferenceAgent().run(uncited, {"type": "refund", "amount_usd": 750})
    assert not result.completed  # ungrounded step is refused


def test_factory_default_is_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_AGENT", raising=False)
    assert isinstance(get_agent(), ReferenceAgent)


# --- LLM agent with an injected fake client ------------------------------------


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _FakeMessages:
    def create(self, **kwargs: object) -> _Resp:
        return _Resp(
            '{"decision": "Route to finance", "actor": "finance team", "chunk_id": "chunk-b"}'
        )


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_llm_agent_parses_grounded_decision() -> None:
    result = LlmAgent(client=_FakeClient()).run(SKILLS, {"type": "refund", "amount_usd": 750})
    assert result.completed
    assert result.action is not None
    assert result.action.citations[0].chunk_id == "chunk-b"
    assert result.grounded
