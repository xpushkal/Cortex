"""Hybrid orchestration: dense + BM25 -> RRF -> rerank -> top-k (M1).

The two retrievers are faked via monkeypatch; this verifies orchestration
(fusion, dedup, mode switch, score propagation), not the stores themselves —
those have their own integration tests.
"""

from __future__ import annotations

import uuid
from itertools import pairwise

import pytest

import cortex.retrieval.hybrid as hybrid_mod
from cortex.retrieval import HashingEmbedder, PassthroughReranker
from cortex.retrieval.hybrid import hybrid_search
from cortex.storage import SearchHit

TENANT = uuid.uuid4()


def _hit(cid: str, score: float = 1.0) -> SearchHit:
    return SearchHit(
        chunk_id=cid,
        score=score,
        text=f"text of {cid}",
        source_kind="sample",
        artifact_id="a1",
        created_at=0,
    )


@pytest.fixture
def fake_stores(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[SearchHit]]:
    """Dense returns d1,d2,shared; sparse returns s1,shared. Patchable per-test."""
    stores = {
        "dense": [_hit("d1", 0.9), _hit("d2", 0.8), _hit("shared", 0.7)],
        "sparse": [_hit("s1", 0.5), _hit("shared", 0.4)],
    }

    async def fake_dense(client: object, **kwargs: object) -> list[SearchHit]:
        return stores["dense"]

    async def fake_sparse(session: object, **kwargs: object) -> list[SearchHit]:
        return stores["sparse"]

    monkeypatch.setattr(hybrid_mod, "dense_search", fake_dense)
    monkeypatch.setattr(hybrid_mod, "search_bm25", fake_sparse)
    return stores


async def _run(mode: str = "hybrid", k: int = 10) -> list[SearchHit]:
    return await hybrid_search(
        query="refund approval",
        tenant_id=TENANT,
        session=None,  # type: ignore[arg-type] - faked store ignores it
        qdrant=None,  # type: ignore[arg-type]
        embedder=HashingEmbedder(),
        reranker=PassthroughReranker(),
        k=k,
        mode=mode,  # type: ignore[arg-type]
    )


async def test_hybrid_fuses_and_dedupes(fake_stores: dict[str, list[SearchHit]]) -> None:
    hits = await _run()
    ids = [h.chunk_id for h in hits]
    # 'shared' appears in both lists -> highest RRF score -> rank 1, once.
    assert ids[0] == "shared"
    assert ids.count("shared") == 1
    assert set(ids) == {"shared", "d1", "d2", "s1"}


async def test_hybrid_scores_are_rrf(fake_stores: dict[str, list[SearchHit]]) -> None:
    hits = await _run()
    # shared: rank 3 dense + rank 2 sparse -> 1/63 + 1/62.
    assert hits[0].score == pytest.approx(1 / 63 + 1 / 62)
    # Scores are descending.
    assert all(a.score >= b.score for a, b in pairwise(hits))


async def test_dense_mode_skips_fusion(fake_stores: dict[str, list[SearchHit]]) -> None:
    hits = await _run(mode="dense", k=2)
    assert [h.chunk_id for h in hits] == ["d1", "d2"]
    assert hits[0].score == 0.9  # dense scores untouched


async def test_k_truncates(fake_stores: dict[str, list[SearchHit]]) -> None:
    hits = await _run(k=2)
    assert len(hits) == 2
