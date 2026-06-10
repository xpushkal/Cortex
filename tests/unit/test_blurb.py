"""Contextual blurbs (M1; docs/RETRIEVAL_AND_ML.md §1)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from cortex.retrieval.blurb import (
    ArtifactContext,
    LlmBlurb,
    TemplateBlurb,
    artifact_head,
    get_blurb_generator,
)

CTX = ArtifactContext(
    source_kind="sample",
    artifact_kind="page",
    external_id="doc-refund-policy",
    head="Refund policy.",
)


def test_artifact_head_takes_first_line_capped() -> None:
    text = "# A very long heading " + " ".join(f"w{i}" for i in range(20)) + "\nbody"
    head = artifact_head(text, max_words=5)
    assert head.startswith("A very long heading")
    assert head.endswith("…")
    assert "body" not in head


def test_template_blurb_is_deterministic_and_situating() -> None:
    gen = TemplateBlurb()
    blurbs = gen.generate(CTX, ["chunk one", "chunk two"])
    assert blurbs == gen.generate(CTX, ["chunk one", "chunk two"])
    assert len(blurbs) == 2
    assert "Refund policy." in blurbs[0]
    assert "doc-refund-policy" in blurbs[0]
    assert "part 1 of 2" in blurbs[0] and "part 2 of 2" in blurbs[1]


def test_template_blurb_single_chunk_omits_part() -> None:
    (blurb,) = TemplateBlurb().generate(CTX, ["only chunk"])
    assert "part" not in blurb


# --- LLM path with an injected fake client (no anthropic dependency needed) ----


@dataclass
class _Block:
    type: str = "text"
    text: str = "Situates the chunk."


@dataclass
class _Response:
    content: list[_Block] = field(default_factory=lambda: [_Block()])


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return _Response()


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_llm_blurb_calls_model_per_chunk() -> None:
    client = _FakeClient()
    gen = LlmBlurb(client=client)
    blurbs = gen.generate(CTX, ["alpha", "beta"])
    assert blurbs == ["Situates the chunk.", "Situates the chunk."]
    assert len(client.messages.calls) == 2
    first = client.messages.calls[0]
    assert first["model"] == "claude-haiku-4-5"
    assert "chunk 1 of 2" in first["messages"][0]["content"]
    assert "alpha" in first["messages"][0]["content"]


def test_factory_defaults_to_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_BLURB_MODE", raising=False)
    assert isinstance(get_blurb_generator(), TemplateBlurb)


def test_factory_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown blurb mode"):
        get_blurb_generator("vibes")
