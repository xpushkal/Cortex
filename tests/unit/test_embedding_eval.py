"""In-memory embedding eval + training-data prep over the real golden (M5).

Exercises the fine-tune pipeline end-to-end *minus* the GPU `.fit()`: rebuild
the seed corpus the way ingest does, run the harness pieces with the hashing
embedder. Deterministic, no DB/Qdrant.
"""

from __future__ import annotations

from cortex.connectors import SampleConnector
from cortex.connectors.base import SourceConfig
from cortex.eval import evaluate_embedder, load_golden
from cortex.retrieval import HashingEmbedder, chunk, prepare_training_data


def _corpus() -> dict[str, str]:
    connector = SampleConnector()
    corpus: dict[str, str] = {}
    for raw in connector.backfill(SourceConfig(kind="sample")):
        art = connector.normalize(raw)
        for ordinal, text in enumerate(
            chunk(art.content, source_kind=art.source_kind, artifact_kind=art.kind)
        ):
            corpus[f"{art.external_id}#{ordinal}"] = text
    return corpus


def _labeled(split: str) -> list[tuple[str, set[str]]]:
    return [
        (ex.query, {f"{ext}#{ordinal}" for ext, ordinal in ex.relevant})
        for ex in load_golden()
        if ex.split == split
    ]


def test_corpus_keys_align_with_golden_labels() -> None:
    corpus = _corpus()
    labels = {cid for _, positives in _labeled("test") for cid in positives}
    # Every golden label resolves to a real corpus chunk (keys match ingest).
    assert labels <= set(corpus)


def test_evaluate_embedder_returns_bounded_metrics() -> None:
    corpus = _corpus()
    metrics = evaluate_embedder(HashingEmbedder(), _labeled("test"), corpus)
    for name in ("recall_at_10", "ndcg_at_10", "mrr"):
        assert 0.0 <= metrics[name] <= 1.0
    # The hashing embedder has real lexical signal, so it retrieves above chance.
    assert metrics["recall_at_10"] > 0.3


def test_prepare_training_data_augments_and_mines() -> None:
    corpus = _corpus()
    labeled = _labeled("dev")
    examples = prepare_training_data(corpus, labeled, HashingEmbedder(), cap=2)
    assert len(examples) >= len(labeled)  # augmented with synthetic queries
    assert all(e.positive for e in examples)
    assert any(e.negatives for e in examples)  # hard negatives mined
    # Positives never leak into their own negatives.
    assert all(e.positive not in e.negatives for e in examples)


def test_prepare_without_augmentation_matches_labeled() -> None:
    corpus = _corpus()
    labeled = _labeled("dev")
    examples = prepare_training_data(corpus, labeled, HashingEmbedder(), augment=False)
    # One example per (query, positive); no synthetic queries added.
    expected = sum(len(positives) for _, positives in labeled)
    assert len(examples) == expected
