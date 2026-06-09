"""The CI eval regression gate (docs/RETRIEVAL_AND_ML.md §5.4).

Headline quality thresholds are defined here in one place. The gate runs in one
of two modes:

  - ADVISORY  — compute and report metrics, but never fail the build. This is the
                default until a credible, human-labeled golden set exists; shipping
                a blocking gate on synthetic-only data would be dishonest.
  - BLOCKING  — fail the build when any metric regresses below its threshold.

Flip via the EVAL_GATE env var (advisory|blocking). The comparison logic is real
and unit-testable now; the metric *values* get wired to the harness in M1.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel

# Headline thresholds (PRD §8 / RETRIEVAL_AND_ML.md §5.4). A metric below its
# threshold is a regression.
THRESHOLDS: dict[str, float] = {
    "recall_at_10": 0.85,
    "ndcg_at_10": 0.70,
    "faithfulness": 4.0,
    "process_citation_validity": 0.95,
}


class GateMode(enum.StrEnum):
    ADVISORY = "advisory"
    BLOCKING = "blocking"


class GateResult(BaseModel):
    mode: GateMode
    passed: bool
    failures: list[str]  # human-readable "metric X.XX < threshold Y.YY" lines


def evaluate_gate(metrics: dict[str, float], *, mode: GateMode) -> GateResult:
    """Compare measured metrics against THRESHOLDS.

    In ADVISORY mode the result always `passed=True` (failures are still listed
    for visibility). In BLOCKING mode `passed` is False if any threshold is missed.
    """
    failures = [
        f"{name} {metrics[name]:.4f} < threshold {threshold:.4f}"
        for name, threshold in THRESHOLDS.items()
        if name in metrics and metrics[name] < threshold
    ]
    passed = mode is GateMode.ADVISORY or not failures
    return GateResult(mode=mode, passed=passed, failures=failures)
