"""The M1 done-when proof: a deliberate quality regression FAILS the gate.

A degraded retriever (constant query embedding -> query-independent ranking,
dense-only so BM25 can't rescue it) is run through the same harness; the gate
must report failures and refuse to pass in blocking mode. This keeps the
"regression fails CI" guarantee in-repo and permanent instead of a one-off
manual experiment.
"""

from __future__ import annotations

import uuid

import pytest

from cortex.eval import GateMode, evaluate_gate, run_retrieval_eval
from cortex.retrieval import DIM, PassthroughReranker
from cortex.storage import get_qdrant, get_sessionmaker

pytestmark = pytest.mark.eval


class _DegradedEmbedder:
    """Embeds every query as the same constant vector: ranking ignores the query."""

    dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (self.dim - 1) for _ in texts]


async def test_deliberate_regression_fails_blocking_gate(seeded_tenant: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        report = await run_retrieval_eval(
            tenant_id=seeded_tenant,
            session=session,
            qdrant=get_qdrant(),
            embedder=_DegradedEmbedder(),
            reranker=PassthroughReranker(),
            split="test",
            mode="dense",
        )

    result = evaluate_gate(report.metrics, mode=GateMode.BLOCKING)
    assert not result.passed, f"degraded retrieval slipped past the blocking gate: {report.metrics}"
    failed_metrics = " ".join(result.failures)
    assert "recall_at_10" in failed_metrics or "ndcg_at_10" in failed_metrics

    # Advisory mode surfaces the same failures without failing the build.
    advisory = evaluate_gate(report.metrics, mode=GateMode.ADVISORY)
    assert advisory.passed and advisory.failures
