"""HashingEmbedder: deterministic, normalized, and lexically meaningful."""

from __future__ import annotations

import math

import pytest

from cortex.retrieval.embedding import DIM, HashingEmbedder, get_embedder


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_dimension_and_normalization() -> None:
    [v] = HashingEmbedder().embed(["refund over five hundred dollars"])
    assert len(v) == DIM
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)


def test_deterministic_across_instances() -> None:
    assert HashingEmbedder().embed(["sev1 incident"]) == HashingEmbedder().embed(["sev1 incident"])


def test_lexical_overlap_scores_higher() -> None:
    emb = HashingEmbedder()
    (refund,) = emb.embed(["refund over $500 goes to finance for approval"])
    (related,) = emb.embed(["how do we approve a refund over 500"])
    (unrelated,) = emb.embed(["the on-call engineer is paged for a sev1 incident"])
    assert _cosine(refund, related) > _cosine(refund, unrelated)


def test_get_embedder_default_is_hashing() -> None:
    assert isinstance(get_embedder(), HashingEmbedder)


def test_get_embedder_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown embedder"):
        get_embedder("nope")
