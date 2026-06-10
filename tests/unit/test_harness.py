"""Eval harness pure parts: golden-set loading, MRR, report emission (M1)."""

from __future__ import annotations

import json
from pathlib import Path

from cortex.eval import EvalReport, load_golden
from cortex.eval.harness import QueryResult, emit_report
from cortex.eval.metrics import mrr


def test_mrr_first_hit_position() -> None:
    assert mrr(["a", "b", "c"], {"a"}) == 1.0
    assert mrr(["a", "b", "c"], {"c"}) == 1.0 / 3
    assert mrr(["a", "b"], {"z"}) == 0.0
    assert mrr([], {"a"}) == 0.0


def test_load_golden_packaged_set() -> None:
    examples = load_golden()
    assert len(examples) >= 40
    splits = {ex.split for ex in examples}
    assert splits == {"dev", "test"}
    # Every example labels at least one (external_id, ordinal) pair.
    assert all(ex.relevant for ex in examples)
    # The held-out split is substantial, not a token gesture.
    assert sum(1 for ex in examples if ex.split == "test") >= 15


def _report(recall: float) -> EvalReport:
    metrics = {"recall_at_10": recall, "ndcg_at_10": 0.8, "mrr": 0.9}
    return EvalReport(
        ran_at="2026-06-10T00:00:00+00:00",
        mode="hybrid",
        split="test",
        n_queries=2,
        metrics=metrics,
        per_query=[
            QueryResult(query="q1", metrics=metrics),
            QueryResult(query="q2", metrics=metrics),
        ],
    )


def test_emit_report_writes_json_and_md_with_deltas(tmp_path: Path) -> None:
    json_path, md_path = emit_report(_report(0.90), out_dir=tmp_path)
    assert json.loads(json_path.read_text())["metrics"]["recall_at_10"] == 0.90
    assert "| recall_at_10 | 0.9000 | — |" in md_path.read_text()

    # Second run reports the delta vs the first.
    emit_report(_report(0.95), out_dir=tmp_path)
    assert "| recall_at_10 | 0.9500 | +0.0500 |" in md_path.read_text()
    assert "Worst queries" in md_path.read_text()
