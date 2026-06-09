"""Source-aware chunking (M1). A Slack thread != a PR != a wiki page.

See the chunk-unit table in docs/RETRIEVAL_AND_ML.md §1. Each strategy is a pure,
unit-testable function. Stubs only.
"""

from __future__ import annotations


def chunk(text: str, *, source_kind: str) -> list[str]:
    """Split an artifact into source-appropriate chunks. M1 deliverable."""
    raise NotImplementedError("source-aware chunking lands in M1")
