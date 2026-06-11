"""Cortex reference agent — the YC-thesis close.

Consumes the skills file (`GET /v1/skills`) and completes a task grounded
entirely in cited process steps. See docs/ROADMAP.md §M6.
"""

from cortex.agent.reference import (
    Agent,
    AgentAction,
    AgentResult,
    LlmAgent,
    ReferenceAgent,
    get_agent,
)
from cortex.agent.schema import (
    FreshnessManifest,
    Skill,
    SkillCitation,
    SkillsFile,
    SkillStep,
)

__all__ = [
    "Agent",
    "AgentAction",
    "AgentResult",
    "FreshnessManifest",
    "LlmAgent",
    "ReferenceAgent",
    "Skill",
    "SkillCitation",
    "SkillStep",
    "SkillsFile",
    "get_agent",
]
