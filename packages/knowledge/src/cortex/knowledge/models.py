"""Process object schema — the core unit of value (docs/DATA_MODEL.md §5).

The structural guard against hallucinated processes lives here: **every step
must carry at least one citation**. A step without a citation is rejected at
validation time. This invariant is enforced by Pydantic and covered by a unit
test (tests/unit/test_process_validation.py).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """A pointer from a knowledge artifact back to its exact source chunk."""

    chunk_id: str
    quote: str | None = None


class ProcessStep(BaseModel):
    """One imperative step in a process. Must be grounded by >=1 citation."""

    ordinal: int
    action: str
    actor: str | None = None
    decision: dict[str, Any] | None = None
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("citations")
    @classmethod
    def _require_citation(cls, v: list[Citation]) -> list[Citation]:
        if not v:
            raise ValueError("every process step must carry at least one citation")
        return v


class Process(BaseModel):
    """A validated, versioned, source-cited description of a recurring task."""

    name: str
    trigger: str
    actors: list[str] = Field(default_factory=list)
    steps: list[ProcessStep]
    version: int = 1

    @field_validator("steps")
    @classmethod
    def _require_steps(cls, v: list[ProcessStep]) -> list[ProcessStep]:
        if not v:
            raise ValueError("a process must have at least one step")
        return v
