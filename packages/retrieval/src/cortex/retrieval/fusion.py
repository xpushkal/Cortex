"""Reciprocal Rank Fusion of multiple ranked result lists.

RRF combines the dense (BGE→Qdrant) and sparse (BM25) result lists without score
calibration: score(d) = Σ 1 / (k + rank_i(d)). Robust and parameter-light — see
docs/RETRIEVAL_AND_ML.md §3. Implemented here as a pure function so it is unit
tested (and later swappable for a Rust hot-path, per the roadmap stretch goal).
"""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked lists of document ids into one RRF-scored, descending ranking.

    Args:
        ranked_lists: each inner sequence is doc ids ordered best-first.
        k: RRF dampening constant (60 is the standard default).

    Returns:
        (doc_id, score) pairs sorted by score descending; ties broken by doc_id.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
