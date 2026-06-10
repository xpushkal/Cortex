"""The golden-set regression gate as a test (docs/RETRIEVAL_AND_ML.md §5.4).

Runs the eval harness over the seeded corpus (held-out test split, hybrid mode)
and feeds the headline metrics to the gate. Honors EVAL_GATE (advisory|blocking).
The report lands in .eval-reports/ for the CI artifact upload.
"""

from __future__ import annotations

import os
import uuid

import pytest

from cortex.eval import GateMode, emit_report, evaluate_gate, run_retrieval_eval
from cortex.retrieval import get_embedder, get_reranker
from cortex.storage import get_qdrant, get_sessionmaker

pytestmark = pytest.mark.eval


async def test_retrieval_quality_meets_thresholds(seeded_tenant: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        report = await run_retrieval_eval(
            tenant_id=seeded_tenant,
            session=session,
            qdrant=get_qdrant(),
            embedder=get_embedder(),
            reranker=get_reranker(),
            split="test",
            mode="hybrid",
        )
    emit_report(report)

    mode = GateMode(os.environ.get("EVAL_GATE", "advisory"))
    result = evaluate_gate(report.metrics, mode=mode)
    headline = {k: round(v, 4) for k, v in report.metrics.items() if "10" in k or k == "mrr"}
    assert result.passed, f"gate failed in {mode} mode: {result.failures} (metrics: {headline})"
