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
from cortex.eval.process_harness import (
    ProcessEvalReport,
    load_process_golden,
    run_process_eval,
)
from cortex.eval.process_metrics import (
    actor_resolution_accuracy,
    citation_validity,
    step_precision_recall,
)

__all__ = [
    "THRESHOLDS",
    "EvalReport",
    "GateMode",
    "GateResult",
    "GoldenExample",
    "ProcessEvalReport",
    "actor_resolution_accuracy",
    "citation_validity",
    "emit_report",
    "evaluate_gate",
    "load_golden",
    "load_process_golden",
    "resolve_labels",
    "run_process_eval",
    "run_retrieval_eval",
    "step_precision_recall",
]
