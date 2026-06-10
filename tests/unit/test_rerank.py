"""Reranker interface: passthrough default + cross-encoder ordering (M1)."""

from __future__ import annotations

import pytest

from cortex.retrieval.rerank import (
    CrossEncoderReranker,
    PassthroughReranker,
    get_reranker,
)

CANDIDATES = [("c1", "refund policy text"), ("c2", "incident runbook"), ("c3", "pto policy")]


def test_passthrough_keeps_fused_order_and_truncates() -> None:
    rr = PassthroughReranker()
    assert rr.rerank("refunds", CANDIDATES, top_k=2) == ["c1", "c2"]


class _FakeCrossEncoder:
    """Scores by position: last candidate scores highest (reverses the order)."""

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [float(i) for i in range(len(pairs))]


def test_cross_encoder_orders_by_score() -> None:
    rr = CrossEncoderReranker(model=_FakeCrossEncoder())
    assert rr.rerank("q", CANDIDATES, top_k=3) == ["c3", "c2", "c1"]
    assert rr.rerank("q", CANDIDATES, top_k=1) == ["c3"]


def test_cross_encoder_empty_candidates() -> None:
    assert CrossEncoderReranker(model=_FakeCrossEncoder()).rerank("q", [], top_k=5) == []


def test_factory_defaults_to_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_RERANKER", raising=False)
    assert isinstance(get_reranker(), PassthroughReranker)


def test_factory_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown reranker"):
        get_reranker("tarot")
