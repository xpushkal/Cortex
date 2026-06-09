"""Retrieval metrics (docs/RETRIEVAL_AND_ML.md §5.2): Recall@k, nDCG@k, MRR.

These are pure functions over (ranked ids, relevant ids) and are unit-tested.
Generation/extraction metrics (RAGAS-style, LLM-judge calibrated) land in M1/M2.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant items appearing in the top-k of `ranked`."""
    if not relevant:
        return 0.0
    hits = sum(1 for doc_id in ranked[:k] if doc_id in relevant)
    return hits / len(relevant)


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG@k."""
    dcg = sum(1.0 / math.log2(i + 2) for i, doc_id in enumerate(ranked[:k]) if doc_id in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0
