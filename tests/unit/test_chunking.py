"""Fixed-size chunker (M0 baseline; docs/RETRIEVAL_AND_ML.md §1)."""

from __future__ import annotations

import pytest

from cortex.retrieval.chunking import chunk


def test_short_text_is_one_chunk() -> None:
    assert chunk("a short thread about refunds") == ["a short thread about refunds"]


def test_empty_text_is_no_chunks() -> None:
    assert chunk("   ") == []


def test_long_text_splits_with_overlap() -> None:
    words = [f"w{i}" for i in range(100)]
    chunks = chunk(" ".join(words), max_tokens=40, overlap=10)
    assert len(chunks) > 1
    # Each chunk has at most max_tokens words.
    assert all(len(c.split()) <= 40 for c in chunks)
    # Overlap: the tail of chunk 0 reappears at the head of chunk 1.
    first, second = chunks[0].split(), chunks[1].split()
    assert first[-10:] == second[:10]


def test_covers_all_words() -> None:
    words = [f"w{i}" for i in range(95)]
    chunks = chunk(" ".join(words), max_tokens=30, overlap=5)
    seen = {w for c in chunks for w in c.split()}
    assert seen == set(words)


def test_rejects_bad_params() -> None:
    with pytest.raises(ValueError, match="max_tokens must be positive"):
        chunk("x", max_tokens=0)
    with pytest.raises(ValueError, match="overlap must be in"):
        chunk("x", max_tokens=10, overlap=10)
