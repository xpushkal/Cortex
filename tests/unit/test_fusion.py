"""Reciprocal Rank Fusion (docs/RETRIEVAL_AND_ML.md §3)."""

from __future__ import annotations

import pytest

from cortex.retrieval import reciprocal_rank_fusion


def test_rrf_rewards_agreement_across_lists() -> None:
    dense = ["a", "b", "c"]
    sparse = ["b", "a", "d"]
    fused = reciprocal_rank_fusion([dense, sparse])
    # "b" is rank 2 then 1; "a" is rank 1 then 2 -> "b" edges ahead, both lead.
    top_ids = [doc for doc, _ in fused[:2]]
    assert set(top_ids) == {"a", "b"}


def test_rrf_includes_all_unique_docs() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
    assert {doc for doc, _ in fused} == {"a", "b", "c"}


def test_rrf_scores_descending() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"]])
    scores = [score for _, score in fused]
    assert scores == sorted(scores, reverse=True)


def test_rrf_rejects_nonpositive_k() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        reciprocal_rank_fusion([["a"]], k=0)
