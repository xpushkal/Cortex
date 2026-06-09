"""Cross-encoder reranking (bge-reranker) — the biggest precision lever (M1).

See docs/RETRIEVAL_AND_ML.md §3. Stub.
"""

from __future__ import annotations


def rerank(query: str, candidates: list[str], *, top_k: int = 8) -> list[str]:
    """Rerank fused candidates with a cross-encoder, return top_k. M1 deliverable."""
    raise NotImplementedError("cross-encoder rerank lands in M1")
