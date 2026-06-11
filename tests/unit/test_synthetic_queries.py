"""Synthetic query generation + round-trip filter (M5; RETRIEVAL_AND_ML.md §2)."""

from __future__ import annotations

import pytest

from cortex.retrieval import HashingEmbedder, generate_synthetic_queries, get_query_generator
from cortex.retrieval.finetune import (
    LlmQueryGenerator,
    SyntheticQuery,
    TemplateQueryGenerator,
    filter_round_trip,
)

CHUNKS = [
    ("c-refund", "Refund policy. Refunds over $500 are routed to the finance team for approval."),
    ("c-incident", "On-call runbook: page the on-call engineer for a Sev1 incident via PagerDuty."),
]


def test_template_generator_extracts_salient_keyword_query() -> None:
    (query,) = TemplateQueryGenerator(terms=4).generate(CHUNKS[0][1])
    tokens = query.split()
    assert len(tokens) == 4
    assert "refund" in tokens or "refunds" in tokens
    # Stopwords are excluded.
    assert "the" not in tokens and "are" not in tokens


def test_generate_synthetic_queries_pairs_with_source_chunk() -> None:
    pairs = generate_synthetic_queries(CHUNKS, generator=TemplateQueryGenerator())
    assert {p.chunk_id for p in pairs} == {"c-refund", "c-incident"}
    assert all(p.query for p in pairs)


def test_round_trip_filter_keeps_self_retrieving_queries() -> None:
    corpus = dict(CHUNKS)
    pairs = generate_synthetic_queries(CHUNKS, generator=TemplateQueryGenerator())
    kept = filter_round_trip(pairs, corpus, HashingEmbedder(), k=1)
    # A salient-keyword query should retrieve its own chunk at rank 1.
    assert {p.chunk_id for p in kept} == {"c-refund", "c-incident"}


def test_round_trip_filter_drops_mislabeled_query() -> None:
    corpus = dict(CHUNKS)
    # This query retrieves the incident chunk, but claims the refund chunk as its
    # source -> round-trip fails -> dropped.
    bad = [SyntheticQuery(query="incident on-call engineer pagerduty sev1", chunk_id="c-refund")]
    assert filter_round_trip(bad, corpus, HashingEmbedder(), k=1) == []


# --- LLM generator with an injected fake client ---------------------------------


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _FakeMessages:
    def create(self, **kwargs: object) -> _Resp:
        return _Resp("How do refunds over 500 get approved?\n- who signs off on a big refund")


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_llm_generator_parses_lines() -> None:
    queries = LlmQueryGenerator(client=_FakeClient()).generate("refund text")
    assert queries == [
        "How do refunds over 500 get approved?",
        "who signs off on a big refund",
    ]


def test_factory_default_is_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_QUERYGEN", raising=False)
    assert isinstance(get_query_generator(), TemplateQueryGenerator)
