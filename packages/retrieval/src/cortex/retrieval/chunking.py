"""Chunking. M0 ships a fixed-size word-window chunker (the baseline the docs
call out); source-aware strategies per docs/RETRIEVAL_AND_ML.md §1 land in M1.

`source_kind` is accepted now so callers don't change when M1 swaps in
source-specific logic. Token counts are approximated by whitespace words to avoid
a tokenizer dependency on the hot ingest path.
"""

from __future__ import annotations

DEFAULT_MAX_TOKENS = 200
DEFAULT_OVERLAP = 40


def chunk(
    text: str,
    *,
    source_kind: str = "file",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split text into overlapping fixed-size windows of ~`max_tokens` words.

    Returns whole-text as a single chunk when short. Overlap preserves context
    across boundaries. Raises on degenerate parameters.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not 0 <= overlap < max_tokens:
        raise ValueError("overlap must be in [0, max_tokens)")

    words = text.split()
    if len(words) <= max_tokens:
        stripped = text.strip()
        return [stripped] if stripped else []

    step = max_tokens - overlap
    chunks: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + max_tokens]
        if window:
            chunks.append(" ".join(window))
        if start + max_tokens >= len(words):
            break
    return chunks
