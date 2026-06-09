"""The eval regression gate's advisory/blocking behavior (docs/RETRIEVAL_AND_ML.md §5.4)."""

from __future__ import annotations

from cortex.eval.gate import THRESHOLDS, GateMode, evaluate_gate

PASSING = {
    "recall_at_10": 0.90,
    "ndcg_at_10": 0.75,
    "faithfulness": 4.3,
    "process_citation_validity": 0.99,
}
REGRESSED = {**PASSING, "recall_at_10": 0.80}  # below 0.85 threshold


def test_passing_metrics_pass_in_blocking_mode() -> None:
    result = evaluate_gate(PASSING, mode=GateMode.BLOCKING)
    assert result.passed
    assert result.failures == []


def test_regression_fails_in_blocking_mode() -> None:
    result = evaluate_gate(REGRESSED, mode=GateMode.BLOCKING)
    assert not result.passed
    assert any("recall_at_10" in f for f in result.failures)


def test_advisory_mode_never_fails_but_still_reports() -> None:
    result = evaluate_gate(REGRESSED, mode=GateMode.ADVISORY)
    assert result.passed  # advisory always passes
    assert result.failures  # but the regression is still surfaced


def test_thresholds_cover_all_headline_metrics() -> None:
    assert set(THRESHOLDS) == set(PASSING)
