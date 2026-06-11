"""Contradiction detection between process versions (docs/RETRIEVAL_AND_ML.md §4.2).

When a changed source re-extracts a process, M2 already writes a new version
rather than overwriting. M3 asks a sharper question: does the new body
*contradict* the active one — a step that does the same thing but now names a
different actor or a different decision threshold (a changed approver, a changed
limit)? That is what needs human review, versus harmless added detail.

A step in the new body is matched to a step in the active body by lexical
coverage of its action; a matched pair whose `actor` or `decision` differs is a
conflict. Pure function — the caller (ingest) records the report and flags the
new version for review.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from cortex.knowledge.faithfulness import coverage

_MATCH_THRESHOLD = 0.6


class StepConflict(BaseModel):
    action: str
    field: str  # actor | decision
    old: Any
    new: Any


class ContradictionReport(BaseModel):
    contradictory: bool
    conflicts: list[StepConflict]
    summary: str


def _match(action: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    best, best_score = None, 0.0
    for cand in candidates:
        score = coverage(action, [cand["action"]])
        if score > best_score:
            best, best_score = cand, score
    return best if best_score >= _MATCH_THRESHOLD else None


def detect_contradiction(
    active_body: dict[str, Any], new_body: dict[str, Any]
) -> ContradictionReport:
    """Compare a new process body to the active one for conflicting steps."""
    active_steps = active_body.get("steps", [])
    conflicts: list[StepConflict] = []
    for step in new_body.get("steps", []):
        prior = _match(step["action"], active_steps)
        if prior is None:
            continue  # a genuinely new step is added detail, not a contradiction
        for field in ("actor", "decision"):
            old, new = prior.get(field), step.get(field)
            if old != new and (old is not None or new is not None):
                conflicts.append(StepConflict(action=step["action"], field=field, old=old, new=new))
    summary = (
        "; ".join(f"{c.field}: {c.old!r} -> {c.new!r}" for c in conflicts)
        if conflicts
        else "no contradiction"
    )
    return ContradictionReport(contradictory=bool(conflicts), conflicts=conflicts, summary=summary)
