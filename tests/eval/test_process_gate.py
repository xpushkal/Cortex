"""The process-extraction gate (M2; docs/RETRIEVAL_AND_ML.md §5.4).

Scores the seeded tenant's persisted processes. `process_citation_validity` is
BLOCKING (the "100% of shipped steps carry valid citations" guarantee);
precision/recall are advisory and only reported. A canary proves a process with
a dangling citation fails the blocking gate.
"""

from __future__ import annotations

import os
import uuid

import pytest

from cortex.eval import GateMode, citation_validity, evaluate_gate, run_process_eval
from cortex.storage import get_sessionmaker

pytestmark = pytest.mark.eval


async def test_process_citation_validity_gate(seeded_tenant: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        report = await run_process_eval(session, tenant_id=seeded_tenant)
    metrics = report.metrics

    mode = GateMode(os.environ.get("EVAL_GATE", "advisory"))
    result = evaluate_gate(
        {"process_citation_validity": metrics["process_citation_validity"]}, mode=mode
    )
    advisory = {k: round(v, 3) for k, v in metrics.items()}
    assert result.passed, f"citation gate failed in {mode}: {result.failures} ({advisory})"

    # The structural guarantee: every shipped step is validly cited.
    assert metrics["process_citation_validity"] == 1.0
    # Advisory quality bar (reported, not blocking): recall over the golden set.
    assert metrics["process_recall"] >= 0.70


def test_dangling_citation_fails_blocking_gate() -> None:
    """A deliberately bad-cited process must be rejected by the blocking gate."""
    processes = [
        {
            "name": "Tampered",
            "steps": [
                {
                    "action": "Route the refund to the finance team for approval",
                    "citations": [{"chunk_id": "real"}],
                },
                {
                    "action": "Wire the funds to an offshore account",
                    "citations": [{"chunk_id": "ghost"}],  # not a real chunk
                },
            ],
        }
    ]
    validity = citation_validity(
        processes,
        {"real"},
        {"real": "Any refund over $500 is routed to the finance team for approval."},
    )
    assert validity < 0.95
    result = evaluate_gate({"process_citation_validity": validity}, mode=GateMode.BLOCKING)
    assert not result.passed
    assert any("process_citation_validity" in f for f in result.failures)
