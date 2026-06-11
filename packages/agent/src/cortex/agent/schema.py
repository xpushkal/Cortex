"""The skills-file wire contract (docs/API.md `/skills`, DATA_MODEL.md §6).

This is what an **external** agent codes against — pydantic only, no Cortex
internals. `GET /v1/skills` emits a payload that validates against `SkillsFile`;
the reference agent consumes it. Keeping the schema here (the consumer side)
decouples producer from consumer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillCitation(BaseModel):
    """Provenance for a step — the source chunk an action is grounded in."""

    chunk_id: str
    quote: str | None = None


class SkillStep(BaseModel):
    action: str
    actor: str | None = None
    decision: dict[str, Any] | None = None  # optional branch condition
    citations: list[SkillCitation] = Field(default_factory=list)


class Skill(BaseModel):
    """An agent-executable process: ordered, cited steps."""

    name: str
    trigger: str
    version: int
    freshness: str  # fresh | stale | expired
    steps: list[SkillStep]


class FreshnessManifest(BaseModel):
    fresh: int = 0
    stale: int = 0
    expired: int = 0


class SkillsFile(BaseModel):
    """The agent-consumable export for a tenant/scope."""

    tenant: str
    scope: str | None = None
    generated_at: str
    freshness_manifest: FreshnessManifest
    skills: list[Skill]
