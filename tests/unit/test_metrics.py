"""Retrieval metrics (docs/RETRIEVAL_AND_ML.md §5.2)."""

from __future__ import annotations

from cortex.eval.metrics import ndcg_at_k, recall_at_k


def test_recall_at_k_counts_hits_over_relevant() -> None:
    assert recall_at_k(["a", "b", "x", "y"], {"a", "b", "z"}, k=4) == 2 / 3


def test_recall_at_k_respects_cutoff() -> None:
    assert recall_at_k(["x", "y", "a"], {"a"}, k=2) == 0.0


def test_ndcg_perfect_ranking_is_one() -> None:
    assert ndcg_at_k(["a", "b"], {"a", "b"}, k=2) == 1.0


def test_ndcg_rewards_higher_placement() -> None:
    high = ndcg_at_k(["a", "x", "y"], {"a"}, k=3)
    low = ndcg_at_k(["x", "y", "a"], {"a"}, k=3)
    assert high > low
