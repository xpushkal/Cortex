"""Contextual blurbs (docs/RETRIEVAL_AND_ML.md §1, "contextual retrieval").

Before embedding, each chunk gets a short blurb situating it in its artifact;
we embed `blurb + text` and store the blurb on the chunk row. Blurbs lift
retrieval on short, context-poor chunks (single Slack messages); they are only
recomputed when the artifact's content_hash changes — unchanged artifacts are
skipped by ingest entirely.

Two generators behind one interface:
  - TemplateBlurb (default): deterministic, metadata-only. Zero cost, no
    network — CI and the eval gate run on this.
  - LlmBlurb: `claude-haiku-4-5` via the anthropic SDK (the `llm` extra) —
    cheapest current model, fine for one-sentence context blurbs. Offline
    backfills should prefer the Batches API (50% off).

Select via CORTEX_BLURB_MODE=template|llm (default template).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

_LLM_MODEL = "claude-haiku-4-5"
_LLM_MAX_TOKENS = 120


@dataclass(frozen=True)
class ArtifactContext:
    """The metadata a blurb situates a chunk within."""

    source_kind: str  # slack | gmail | notion | ... | sample
    artifact_kind: str  # message | email | page | pr | issue | doc
    external_id: str
    head: str  # opening of the artifact, used as a cheap title


class BlurbGenerator(Protocol):
    def generate(self, ctx: ArtifactContext, chunks: list[str]) -> list[str]:
        """Return one blurb per chunk (parallel to `chunks`)."""
        ...


def artifact_head(content: str, *, max_words: int = 12) -> str:
    """First line of the artifact, capped — a cheap, deterministic title."""
    first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    words = first_line.lstrip("#").strip().split()
    head = " ".join(words[:max_words])
    return head + ("…" if len(words) > max_words else "")


class TemplateBlurb:
    """Deterministic blurb from metadata only. The default and the CI path."""

    def generate(self, ctx: ArtifactContext, chunks: list[str]) -> list[str]:
        total = len(chunks)
        blurbs = []
        for i in range(total):
            part = f", part {i + 1} of {total}" if total > 1 else ""
            blurbs.append(
                f"From the {ctx.artifact_kind} '{ctx.head}' "
                f"({ctx.source_kind}/{ctx.external_id}{part})."
            )
        return blurbs


class LlmBlurb:
    """One-sentence LLM blurbs via claude-haiku-4-5 (the `llm` extra).

    `client` is injectable for tests; when omitted, the anthropic SDK is
    lazy-imported so the base install stays light.
    """

    def __init__(self, model: str = _LLM_MODEL, client: Any | None = None) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - only without the extra
                raise RuntimeError("LlmBlurb needs the 'llm' extra: uv sync --extra llm") from exc
            client = anthropic.Anthropic()
        self._client = client
        self._model = model

    def generate(self, ctx: ArtifactContext, chunks: list[str]) -> list[str]:
        total = len(chunks)
        blurbs: list[str] = []
        for i, text in enumerate(chunks):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_LLM_MAX_TOKENS,
                system=(
                    "Write one short sentence situating the given chunk within its "
                    "source artifact, for use as retrieval context. Mention what the "
                    "artifact is about and where the chunk fits. No preamble."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Artifact: {ctx.artifact_kind} '{ctx.head}' from "
                            f"{ctx.source_kind} (id {ctx.external_id}), "
                            f"chunk {i + 1} of {total}.\n\nChunk:\n{text}"
                        ),
                    }
                ],
            )
            blurbs.append(next((b.text for b in response.content if b.type == "text"), "").strip())
        return blurbs


def get_blurb_generator(mode: str | None = None) -> BlurbGenerator:
    """Return the configured generator. CORTEX_BLURB_MODE=template|llm (default template)."""
    choice = (mode or os.environ.get("CORTEX_BLURB_MODE", "template")).lower()
    if choice == "template":
        return TemplateBlurb()
    if choice == "llm":
        return LlmBlurb()
    raise ValueError(f"unknown blurb mode: {choice!r}")
