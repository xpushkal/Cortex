"""In-memory retrieval eval for the embedding A/B (M5; RETRIEVAL_AND_ML.md §2).

`evaluate_embedder` ranks a labeled query set against a corpus using a given
`Embedder` and returns Recall@k / nDCG@k / MRR — no DB or Qdrant, so
`scripts/train_embeddings.py` can score base vs fine-tuned models directly.
Pure and deterministic with the hashing embedder.
"""

from __future__ import annotations

from cortex.eval.metrics import mrr, ndcg_at_k, recall_at_k
from cortex.retrieval.embedding import Embedder

LabeledQuery = tuple[str, set[str]]  # (query, relevant chunk ids)
DEFAULT_K_VALUES = (5, 10, 20)


def _rank(
    query_vec: list[float], corpus_ids: list[str], corpus_vecs: list[list[float]]
) -> list[str]:
    scored = (
        (sum(q * c for q, c in zip(query_vec, vec, strict=True)), cid)
        for cid, vec in zip(corpus_ids, corpus_vecs, strict=True)
    )
    return [cid for _, cid in sorted(scored, key=lambda s: -s[0])]


def evaluate_embedder(
    embedder: Embedder,
    labeled: list[LabeledQuery],
    corpus: dict[str, str],
    *,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> dict[str, float]:
    """Mean Recall@k / nDCG@k / MRR for `embedder` over the labeled query set."""
    corpus_ids = list(corpus)
    corpus_vecs = embedder.embed([corpus[cid] for cid in corpus_ids])
    query_vecs = embedder.embed([q for q, _ in labeled])

    sums: dict[str, float] = {f"recall_at_{k}": 0.0 for k in k_values}
    sums.update({f"ndcg_at_{k}": 0.0 for k in k_values})
    sums["mrr"] = 0.0
    n = len(labeled)
    for (_, relevant), qvec in zip(labeled, query_vecs, strict=True):
        ranked = _rank(qvec, corpus_ids, corpus_vecs)
        for k in k_values:
            sums[f"recall_at_{k}"] += recall_at_k(ranked, relevant, k)
            sums[f"ndcg_at_{k}"] += ndcg_at_k(ranked, relevant, k)
        sums["mrr"] += mrr(ranked, relevant)
    return {name: total / n for name, total in sums.items()} if n else dict.fromkeys(sums, 0.0)
