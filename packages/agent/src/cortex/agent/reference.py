"""Reference agent — completes a task grounded *only* in the skills file (M6).

The done-when: given the skills file and a task (e.g. a $750 refund), the agent
picks the applicable cited process step and acts on it, so **every action is
traceable to a cited step**. The deterministic agent (CI default) reasons over
the step text; the `claude` variant (`CORTEX_AGENT=llm`, injectable client) is
the flag-gated flavor.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from pydantic import BaseModel

from cortex.agent.schema import Skill, SkillCitation, SkillsFile

_AMOUNT = re.compile(r"\$\s?(\d[\d,]*)")
_OVER = ("over", "above", "more than", "greater than", "exceed", "exceeding")
_UNDER = ("up to", "under", "below", "less than", "at most", "or less", "within")
_AGENT_MODEL = "claude-opus-4-8"


class AgentAction(BaseModel):
    skill: str
    decision: str  # the step's action the agent took
    actor: str | None = None
    citations: list[SkillCitation]  # provenance — never empty for an emitted action


class AgentResult(BaseModel):
    completed: bool
    action: AgentAction | None = None
    reason: str = ""

    @property
    def grounded(self) -> bool:
        """True iff the action (if any) carries at least one citation."""
        return self.action is None or bool(self.action.citations)


def _step_applies(action: str, amount: float) -> bool | None:
    """Does a threshold step apply to `amount`? None if the step has no threshold."""
    match = _AMOUNT.search(action)
    if match is None:
        return None
    threshold = float(match.group(1).replace(",", ""))
    low = action.lower()
    if any(cue in low for cue in _OVER):
        return amount > threshold
    if any(cue in low for cue in _UNDER):
        return amount <= threshold
    return None


def _find_skill(skills: SkillsFile, keyword: str) -> Skill | None:
    needle = keyword.lower()
    return next(
        (s for s in skills.skills if needle in s.name.lower() or needle in s.trigger.lower()),
        None,
    )


class Agent(Protocol):
    def run(self, skills: SkillsFile, task: dict[str, Any]) -> AgentResult: ...


class ReferenceAgent:
    """Deterministic agent: routes a threshold task to the applicable cited step."""

    def run(self, skills: SkillsFile, task: dict[str, Any]) -> AgentResult:
        if task.get("type") != "refund":
            return AgentResult(completed=False, reason=f"unsupported task: {task.get('type')!r}")
        amount = float(task["amount_usd"])
        skill = _find_skill(skills, "refund")
        if skill is None:
            return AgentResult(completed=False, reason="no refund skill in the skills file")
        for step in skill.steps:
            if _step_applies(step.action, amount) and step.citations:
                return AgentResult(
                    completed=True,
                    action=AgentAction(
                        skill=skill.name,
                        decision=step.action,
                        actor=step.actor,
                        citations=step.citations,
                    ),
                )
        return AgentResult(
            completed=False, reason=f"no cited step applies to ${amount:g} in {skill.name!r}"
        )


class LlmAgent:
    """claude consuming the skills file as grounding (the `llm` extra)."""

    def __init__(self, model: str = _AGENT_MODEL, client: Any | None = None) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - only without the extra
                raise RuntimeError("LlmAgent needs the 'llm' extra: uv sync --extra llm") from exc
            client = anthropic.Anthropic()
        self._client = client
        self._model = model

    def run(self, skills: SkillsFile, task: dict[str, Any]) -> AgentResult:
        skill = _find_skill(skills, str(task.get("type", "")))
        response = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=(
                "You are an agent grounded ONLY in the provided skill. Decide the "
                "action for the task and cite the chunk_id of the step you used. "
                'Reply as JSON: {"decision": str, "actor": str|null, "chunk_id": str}.'
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Task: {json.dumps(task)}\n\nSkill:\n"
                    f"{skill.model_dump_json() if skill else 'none'}",
                }
            ],
        )
        payload = json.loads(next(b.text for b in response.content if b.type == "text"))
        return AgentResult(
            completed=True,
            action=AgentAction(
                skill=skill.name if skill else "",
                decision=payload["decision"],
                actor=payload.get("actor"),
                citations=[SkillCitation(chunk_id=payload["chunk_id"])],
            ),
        )


def get_agent(mode: str | None = None) -> Agent:
    """Return the configured agent. CORTEX_AGENT=reference|llm (default reference)."""
    choice = (mode or os.environ.get("CORTEX_AGENT", "reference")).lower()
    if choice == "reference":
        return ReferenceAgent()
    if choice == "llm":
        return LlmAgent()
    raise ValueError(f"unknown agent: {choice!r}")
