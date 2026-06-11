"""Embedding A/B acceptance gate (M5; RETRIEVAL_AND_ML.md §2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortex.eval import ab_compare, emit_ab_report

BASE = {"recall_at_10": 0.80, "ndcg_at_10": 0.70, "mrr": 0.75}


def test_clears_both_thresholds_ships() -> None:
    finetuned = {"recall_at_10": 0.85, "ndcg_at_10": 0.73, "mrr": 0.80}  # +0.05 / +0.03
    report = ab_compare(BASE, finetuned)
    assert report.passed
    assert report.deltas["recall_at_10"] == pytest.approx(0.05)
    assert report.reasons == []


def test_recall_below_threshold_does_not_ship() -> None:
    finetuned = {"recall_at_10": 0.84, "ndcg_at_10": 0.74}  # +0.04 recall — short
    report = ab_compare(BASE, finetuned)
    assert not report.passed
    assert any("recall_at_10" in r for r in report.reasons)


def test_ndcg_below_threshold_does_not_ship() -> None:
    finetuned = {"recall_at_10": 0.90, "ndcg_at_10": 0.72}  # +0.02 ndcg — short
    report = ab_compare(BASE, finetuned)
    assert not report.passed
    assert any("ndcg_at_10" in r for r in report.reasons)


def test_regression_does_not_ship() -> None:
    finetuned = {"recall_at_10": 0.78, "ndcg_at_10": 0.68}  # worse than base
    report = ab_compare(BASE, finetuned)
    assert not report.passed
    assert len(report.reasons) == 2


def test_emit_ab_report_writes_verdict(tmp_path: Path) -> None:
    report = ab_compare(BASE, {"recall_at_10": 0.86, "ndcg_at_10": 0.74})
    json_path, md_path = emit_ab_report(report, out_dir=tmp_path)
    assert json_path.exists()
    md = md_path.read_text()
    assert "SHIP" in md
    assert "recall_at_10" in md
