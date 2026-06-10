"""Cortex evaluation harness — the project's strongest reliability signal.

Golden datasets, retrieval/generation/extraction metrics, and a CI regression
gate. See docs/RETRIEVAL_AND_ML.md §5 and docs/TEST-STRATEGY.md.
"""

from cortex.eval.gate import THRESHOLDS, GateMode, GateResult, evaluate_gate
from cortex.eval.harness import (
    EvalReport,
    GoldenExample,
    emit_report,
    load_golden,
    resolve_labels,
    run_retrieval_eval,
)

__all__ = [
    "THRESHOLDS",
    "EvalReport",
    "GateMode",
    "GateResult",
    "GoldenExample",
    "emit_report",
    "evaluate_gate",
    "load_golden",
    "resolve_labels",
    "run_retrieval_eval",
]
