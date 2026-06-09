"""Cortex evaluation harness — the project's strongest reliability signal.

Golden datasets, retrieval/generation/extraction metrics, and a CI regression
gate. See docs/RETRIEVAL_AND_ML.md §5 and docs/TEST-STRATEGY.md.
"""

from cortex.eval.gate import THRESHOLDS, GateMode, GateResult, evaluate_gate

__all__ = ["THRESHOLDS", "GateMode", "GateResult", "evaluate_gate"]
