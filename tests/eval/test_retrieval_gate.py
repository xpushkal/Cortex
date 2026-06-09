"""The golden-set regression gate as a test (docs/RETRIEVAL_AND_ML.md §5.4).

Runs the eval harness over the seed corpus and asserts no metric regresses below
threshold. Honors EVAL_GATE (advisory|blocking). Skipped until a credible golden
set exists — shipping a blocking gate on synthetic-only data would be dishonest.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.eval


@pytest.mark.skip(reason="needs M1 retrieval + a human-labeled golden set")
def test_retrieval_quality_meets_thresholds() -> None:
    # metrics = run_eval(seed_corpus)
    # result = evaluate_gate(metrics, mode=GateMode(os.environ["EVAL_GATE"]))
    # assert result.passed, result.failures
    raise AssertionError("unimplemented eval harness run")
