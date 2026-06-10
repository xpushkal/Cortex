"""Cross-encoder reranking — the single biggest precision lever (M1).

See docs/RETRIEVAL_AND_ML.md §3. Two implementations behind one interface:
  - PassthroughReranker: identity over the fused order. Dependency-free default
    so the base install and CI stay model-free.
  - CrossEncoderReranker: `BAAI/bge-reranker-base` via sentence-transformers
    (the `ml` extra), scoring (query, text) pairs over the top-N fused
    candidates. Lazy model load; `model` is injectable for tests.

Select via CORTEX_RERANKER=passthrough|bge (default passthrough).
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[tuple[str, str]], *, top_k: int) -> list[str]:
        """Order (id, text) candidates by relevance to `query`; return top_k ids."""
        ...


class PassthroughReranker:
    """Identity reranker: keeps the fused order. The default and the CI path."""

    def rerank(self, query: str, candidates: list[tuple[str, str]], *, top_k: int) -> list[str]:
        return [cid for cid, _ in candidates[:top_k]]


class CrossEncoderReranker:
    """bge-reranker cross-encoder via sentence-transformers (the `ml` extra)."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base", model: Any | None = None):
        if model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - only without the extra
                raise RuntimeError(
                    "CrossEncoderReranker needs the 'ml' extra: uv sync --extra ml"
                ) from exc
            model = CrossEncoder(model_name)
        self._model = model

    def rerank(self, query: str, candidates: list[tuple[str, str]], *, top_k: int) -> list[str]:
        if not candidates:
            return []
        scores = self._model.predict([(query, text) for _, text in candidates])
        ranked = sorted(
            zip(candidates, scores, strict=True), key=lambda pair: (-float(pair[1]), pair[0][0])
        )
        return [cid for (cid, _), _ in ranked[:top_k]]


def get_reranker(name: str | None = None) -> Reranker:
    """Return the configured reranker. CORTEX_RERANKER=passthrough|bge (default passthrough)."""
    choice = (name or os.environ.get("CORTEX_RERANKER", "passthrough")).lower()
    if choice == "passthrough":
        return PassthroughReranker()
    if choice == "bge":
        return CrossEncoderReranker()
    raise ValueError(f"unknown reranker: {choice!r}")
