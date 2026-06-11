"""Hard-negative mining + training-data assembly (M5; RETRIEVAL_AND_ML.md §2)."""

from __future__ import annotations

from pathlib import Path

from cortex.retrieval import (
    HashingEmbedder,
    build_training_examples,
    dump_training_examples,
    load_training_examples,
    mine_hard_negatives,
)

# A positive about refunds, a confusable distractor (also "refund"), and an
# unrelated chunk. The distractor should surface as the hard negative.
CORPUS = {
    "pos": "Refunds over $500 are routed to the finance team for approval.",
    "distractor": "Refunds under $500 are issued directly by a support agent.",
    "unrelated": "The office plants are watered every Tuesday by facilities.",
}
LABELED = [("refund over 500 finance approval", {"pos"})]


def test_mine_excludes_positives_and_caps() -> None:
    negs = mine_hard_negatives(LABELED, CORPUS, HashingEmbedder(), fetch_k=20, cap=1)
    assert len(negs) == 1
    (per_query,) = negs
    assert "pos" not in per_query  # never mine the positive
    assert len(per_query) == 1  # capped
    assert per_query[0] == "distractor"  # the confusable refund chunk


def test_build_examples_pairs_positive_text_with_negative_texts() -> None:
    negs = mine_hard_negatives(LABELED, CORPUS, HashingEmbedder(), cap=2)
    examples = build_training_examples(LABELED, negs, CORPUS)
    assert len(examples) == 1
    ex = examples[0]
    assert ex.query == "refund over 500 finance approval"
    assert ex.positive == CORPUS["pos"]
    assert CORPUS["distractor"] in ex.negatives
    assert ex.positive not in ex.negatives


def test_training_examples_jsonl_round_trip(tmp_path: Path) -> None:
    negs = mine_hard_negatives(LABELED, CORPUS, HashingEmbedder())
    examples = build_training_examples(LABELED, negs, CORPUS)
    path = tmp_path / "train.jsonl"
    dump_training_examples(examples, path)
    assert [e.model_dump() for e in load_training_examples(path)] == [
        e.model_dump() for e in examples
    ]
