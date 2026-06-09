"""The citation invariant — the structural guard against hallucinated processes.

docs/DATA_MODEL.md §5: every process step MUST carry >=1 citation, enforced at
validation time. This is the single most important correctness test in the repo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cortex.knowledge.models import Citation, Process, ProcessStep


def test_step_with_citation_is_valid() -> None:
    step = ProcessStep(ordinal=1, action="Verify order", citations=[Citation(chunk_id="c1")])
    assert step.citations[0].chunk_id == "c1"


def test_step_without_citation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one citation"):
        ProcessStep(ordinal=1, action="Approve refund", citations=[])


def test_process_requires_at_least_one_step() -> None:
    with pytest.raises(ValidationError, match="at least one step"):
        Process(name="Empty", trigger="never", steps=[])


def test_valid_process_round_trips() -> None:
    proc = Process(
        name="Refund over $500",
        trigger="Customer requests a refund exceeding $500 USD",
        actors=["support_agent", "finance_approver"],
        steps=[
            ProcessStep(ordinal=1, action="Verify eligibility", citations=[Citation(chunk_id="a")]),
            ProcessStep(
                ordinal=2,
                action="Route to finance if amount > $500",
                decision={"if": "amount_usd > 500"},
                citations=[Citation(chunk_id="b")],
            ),
        ],
        version=4,
    )
    assert proc.version == 4
    assert len(proc.steps) == 2
