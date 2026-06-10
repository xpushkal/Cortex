"""Source-aware chunking (M1; docs/RETRIEVAL_AND_ML.md §1).

Each source type chunks differently: docs split on the author's headings,
threads split on turns, emails drop quoted history first. `chunk()` stays the
single entrypoint — it dispatches on the artifact kind (message | email | page |
doc | pr | issue), falls back to the source kind, and degenerates to the M0
fixed word-window for anything unknown. All strategies are pure functions.

Token counts are approximated by whitespace words to avoid a tokenizer
dependency on the hot ingest path.
"""

from __future__ import annotations

import re
from collections.abc import Callable

DEFAULT_MAX_TOKENS = 200
DEFAULT_OVERLAP = 40

_HEADING = re.compile(r"^#{1,6}\s+\S")
# Reply markers that begin the quoted tail of an email body.
_QUOTE_TAIL = re.compile(r"^(On .{0,200} wrote:|-{2,}\s*Original Message\s*-{0,}|From: .+)$")


def chunk(
    text: str,
    *,
    source_kind: str = "file",
    artifact_kind: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split text into retrieval chunks using the strategy for its source type.

    Dispatch order: `artifact_kind` -> `source_kind` -> fixed word-window.
    Returns whole-text as a single chunk when short (except markdown, where the
    author's headings always delimit). Raises on degenerate parameters.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not 0 <= overlap < max_tokens:
        raise ValueError("overlap must be in [0, max_tokens)")
    if not text.strip():
        return []

    strategy = _resolve(artifact_kind, source_kind)
    return strategy(text, max_tokens, overlap)


# --- strategy resolution ------------------------------------------------------


def _resolve(artifact_kind: str | None, source_kind: str) -> Callable[[str, int, int], list[str]]:
    if artifact_kind in _BY_ARTIFACT_KIND:
        return _BY_ARTIFACT_KIND[artifact_kind]
    return _BY_SOURCE_KIND.get(source_kind, _fixed_window)


# --- strategies -----------------------------------------------------------------


def _markdown(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Heading-delimited sections; oversized sections split by paragraph, then window."""
    chunks: list[str] = []
    for heading, body in _sections(text):
        section = f"{heading}\n{body}".strip() if heading else body.strip()
        if not section:
            continue
        if _words(section) <= max_tokens:
            chunks.append(section)
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        chunks.extend(_pack(paragraphs, max_tokens, overlap, prefix=heading))
    return chunks


def _thread(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Sliding window of turns within a thread; one-turn overlap between windows."""
    if _words(text) <= max_tokens:
        return [text.strip()]
    turns = [line.strip() for line in text.splitlines() if line.strip()]
    return _pack(turns, max_tokens, overlap, overlap_units=1)


def _email(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Strip quoted history (near-duplicate noise), then paragraph-pack the rest."""
    kept: list[str] = []
    for line in text.splitlines():
        if _QUOTE_TAIL.match(line.strip()):
            break  # everything from the reply marker down is quoted history
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    if not body:
        return []
    if _words(body) <= max_tokens:
        return [body]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return _pack(paragraphs, max_tokens, overlap)


def _fixed_window(text: str, max_tokens: int, overlap: int) -> list[str]:
    """M0 baseline: overlapping fixed-size windows of ~max_tokens words."""
    words = text.split()
    if len(words) <= max_tokens:
        return [text.strip()]
    step = max_tokens - overlap
    chunks: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + max_tokens]
        if window:
            chunks.append(" ".join(window))
        if start + max_tokens >= len(words):
            break
    return chunks


_BY_ARTIFACT_KIND: dict[str, Callable[[str, int, int], list[str]]] = {
    "page": _markdown,
    "doc": _markdown,
    "pr": _markdown,
    "issue": _markdown,
    "message": _thread,
    "email": _email,
}

_BY_SOURCE_KIND: dict[str, Callable[[str, int, int], list[str]]] = {
    "notion": _markdown,
    "file": _markdown,
    "github": _markdown,
    "linear": _markdown,
    "slack": _thread,
    "gmail": _email,
}


# --- helpers --------------------------------------------------------------------


def _words(text: str) -> int:
    return len(text.split())


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs; preamble gets an empty heading."""
    sections: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in text.splitlines():
        if _HEADING.match(line):
            if heading or any(s.strip() for s in body):
                sections.append((heading, "\n".join(body)))
            heading, body = line.strip(), []
        else:
            body.append(line)
    sections.append((heading, "\n".join(body)))
    return sections


def _pack(
    units: list[str],
    max_tokens: int,
    overlap: int,
    *,
    prefix: str = "",
    overlap_units: int = 0,
) -> list[str]:
    """Greedily pack semantic units (paragraphs, turns) into <= max_tokens chunks.

    `prefix` (a section heading) is prepended to every chunk and counted against
    the budget. `overlap_units` carries the last N units into the next chunk.
    Units that alone exceed the budget fall back to the fixed window.
    """
    budget = max_tokens - (_words(prefix) if prefix else 0)
    chunks: list[str] = []
    window: list[str] = []
    size = 0

    def emit() -> None:
        if window:
            body = "\n".join(window)
            chunks.append(f"{prefix}\n{body}" if prefix else body)

    for unit in units:
        n = _words(unit)
        if n > max(budget, 1):
            emit()
            window, size = [], 0
            chunks.extend(_fixed_window(unit, max_tokens, overlap))
            continue
        if size + n > budget and window:
            emit()
            window = window[-overlap_units:] if overlap_units else []
            size = sum(_words(u) for u in window)
        window.append(unit)
        size += n
    emit()
    return chunks
