"""Source-aware chunking (M1; docs/RETRIEVAL_AND_ML.md §1)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from cortex.retrieval.chunking import chunk

# --- baseline fixed window (unknown kinds keep M0 behavior) ---------------------


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


def test_unknown_kind_falls_back_to_fixed_window() -> None:
    words = " ".join(f"w{i}" for i in range(50))
    fixed = chunk(words, source_kind="mystery", max_tokens=20, overlap=5)
    assert len(fixed) > 1
    assert all(len(c.split()) <= 20 for c in fixed)


def test_rejects_bad_params() -> None:
    with pytest.raises(ValueError, match="max_tokens must be positive"):
        chunk("x", max_tokens=0)
    with pytest.raises(ValueError, match="overlap must be in"):
        chunk("x", max_tokens=10, overlap=10)


# --- markdown (page / doc / pr / issue) ------------------------------------------

HANDBOOK = (
    "# Support handbook\n"
    "Intro paragraph about support.\n\n"
    "## Refunds\n"
    "Refunds over five hundred dollars go to finance for approval.\n\n"
    "## Chargebacks\n"
    "Submit evidence through the provider dashboard within seven days."
)


def test_markdown_splits_on_headings() -> None:
    chunks = chunk(HANDBOOK, artifact_kind="page")
    assert len(chunks) == 3
    assert chunks[0].startswith("# Support handbook")
    assert chunks[1].startswith("## Refunds")
    assert chunks[2].startswith("## Chargebacks")
    # Section bodies stay attached to their heading.
    assert "finance for approval" in chunks[1]


def test_markdown_oversized_section_packs_paragraphs_with_heading() -> None:
    para1 = " ".join(f"alpha{i}" for i in range(15))
    para2 = " ".join(f"beta{i}" for i in range(15))
    text = f"## Big section\n{para1}\n\n{para2}"
    chunks = chunk(text, artifact_kind="page", max_tokens=20, overlap=4)
    assert len(chunks) == 2
    # Every packed chunk carries the heading for context.
    assert all(c.startswith("## Big section") for c in chunks)
    assert "alpha0" in chunks[0] and "beta0" in chunks[1]


def test_markdown_headingless_text_behaves_like_baseline() -> None:
    assert chunk("plain text page", artifact_kind="page") == ["plain text page"]


# --- thread (message) -------------------------------------------------------------

THREAD = "\n".join(
    f"user{i}: " + " ".join(f"word{i}_{j}" for j in range(8)) for i in range(6)
)  # 6 turns x 9 words


def test_thread_short_is_one_chunk() -> None:
    assert chunk("alice: hi\nbob: hello", artifact_kind="message") == ["alice: hi\nbob: hello"]


def test_thread_windows_turns_with_one_turn_overlap() -> None:
    chunks = chunk(THREAD, artifact_kind="message", max_tokens=20, overlap=4)
    assert len(chunks) > 1
    # Turns are never split mid-line; each chunk is whole turns.
    for c in chunks:
        assert all(line.split(":")[0].startswith("user") for line in c.splitlines())
    # One-turn overlap: last turn of chunk N is first turn of chunk N+1.
    for a, b in pairwise(chunks):
        assert a.splitlines()[-1] == b.splitlines()[0]


# --- email -----------------------------------------------------------------------

EMAIL = (
    "The contract renews March 1; decision due to finance by year end.\n\n"
    "On Mon, Dec 1, 2025, erin wrote:\n"
    "> When does the Acme contract renew?\n"
    "> I could not find it."
)


def test_email_strips_quoted_history() -> None:
    chunks = chunk(EMAIL, artifact_kind="email")
    assert len(chunks) == 1
    assert "renews March 1" in chunks[0]
    assert "erin wrote" not in chunks[0]
    assert "could not find" not in chunks[0]


def test_email_strips_inline_quote_lines() -> None:
    text = "Top reply here.\n> quoted line one\nMore of the reply."
    chunks = chunk(text, artifact_kind="email")
    assert chunks == ["Top reply here.\nMore of the reply."]


def test_email_all_quoted_yields_nothing() -> None:
    assert chunk("> only a quote\n> nothing else", artifact_kind="email") == []
