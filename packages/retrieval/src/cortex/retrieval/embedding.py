"""Embeddings behind a swappable interface (ADR-0002).

Two implementations:
  - HashingEmbedder: deterministic, dependency-free bag-of-words hashing vectorizer
    (384-d, L2-normalized). Gives real lexical signal — shared terms -> higher
    cosine — so the full ingest/search path is exercised hermetically in tests and
    CI without downloading a model. This is the default.
  - BGEEmbedder: the real base model, `bge-small-en-v1.5` (384-d). Lazy-imports
    sentence-transformers (the `ml` extra) so the base install stays light.
  - FineTunedEmbedder: a domain fine-tuned sentence-transformers model loaded
    from a path (M5) — the serving swap behind a flag.

Select via CORTEX_EMBEDDER=hashing|bge|finetuned (default hashing); the
fine-tuned variant additionally reads CORTEX_EMBEDDER_MODEL=<path>.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any, Protocol

DIM = 384  # matches bge-small-en-v1.5 and the Qdrant payload in docs/DATA_MODEL.md
_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingEmbedder:
    """Deterministic hashing vectorizer. No ML deps; stable across processes."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            digest = hashlib.md5(tok.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class BGEEmbedder:
    """Base bge-small-en-v1.5 via sentence-transformers (the `ml` extra)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise RuntimeError("BGEEmbedder needs the 'ml' extra: uv sync --extra ml") from exc
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - needs model
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


class FineTunedEmbedder:
    """A domain fine-tuned sentence-transformers model loaded from a path (`ml`).

    The serving swap (M5): point `CORTEX_EMBEDDER_MODEL` at a model produced by
    `scripts/train_embeddings.py`. `model` is injectable for tests; the real load
    is lazy so the base install stays light.
    """

    def __init__(self, model_path: str, model: Any | None = None) -> None:
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - only without the extra
                raise RuntimeError(
                    "FineTunedEmbedder needs the 'ml' extra: uv sync --extra ml"
                ) from exc
            model = SentenceTransformer(model_path)
        self._model = model
        self.dim = int(model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


def get_embedder(name: str | None = None) -> Embedder:
    """Return the configured embedder. CORTEX_EMBEDDER=hashing|bge|finetuned."""
    choice = (name or os.environ.get("CORTEX_EMBEDDER", "hashing")).lower()
    if choice == "bge":
        return BGEEmbedder()
    if choice == "hashing":
        return HashingEmbedder()
    if choice == "finetuned":
        path = os.environ.get("CORTEX_EMBEDDER_MODEL")
        if not path:
            raise ValueError("CORTEX_EMBEDDER=finetuned needs CORTEX_EMBEDDER_MODEL=<path>")
        return FineTunedEmbedder(path)
    raise ValueError(f"unknown embedder: {choice!r}")
