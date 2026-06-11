"""Fine-tuned embedder serving swap behind a flag (M5)."""

from __future__ import annotations

import pytest

from cortex.retrieval.embedding import FineTunedEmbedder, get_embedder


class _FakeModel:
    """Stands in for a loaded sentence-transformers model (no `ml` extra needed)."""

    def get_sentence_embedding_dimension(self) -> int:
        return 384

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
        # Deterministic length-based vectors; just enough to exercise the wrapper.
        return [[float(len(t))] + [0.0] * 383 for t in texts]


def test_finetuned_embedder_wraps_model() -> None:
    emb = FineTunedEmbedder("ignored", model=_FakeModel())
    assert emb.dim == 384
    vecs = emb.embed(["ab", "abcd"])
    assert vecs[0][0] == 2.0
    assert vecs[1][0] == 4.0
    assert all(len(v) == 384 for v in vecs)


def test_factory_requires_model_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_EMBEDDER_MODEL", raising=False)
    with pytest.raises(ValueError, match="CORTEX_EMBEDDER_MODEL"):
        get_embedder("finetuned")


def test_factory_finetuned_needs_ml_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    # Path set, but the `ml` extra isn't installed in the base test env -> RuntimeError.
    monkeypatch.setenv("CORTEX_EMBEDDER_MODEL", "/models/cortex-bge-ft")
    with pytest.raises(RuntimeError, match="needs the 'ml' extra"):
        get_embedder("finetuned")
