"""Entity + relation extraction with provenance (M2; docs/RETRIEVAL_AND_ML.md §4.1)."""

from __future__ import annotations

import pytest

from cortex.knowledge.graph import HeuristicExtractor, LlmExtractor, get_extractor

REFUND = (
    "Refunds up to $500 can be issued directly by a support agent. Any refund over "
    "$500 must be routed to the finance team for approval before it is processed."
)


def test_heuristic_extracts_typed_entities_with_provenance() -> None:
    entities, _ = HeuristicExtractor().extract("chunk-1", REFUND)
    names = {(e.name, e.type) for e in entities}
    assert ("support agent", "role") in names
    assert ("finance team", "team") in names
    # Provenance + confidence on every candidate.
    assert all(e.source_chunk_id == "chunk-1" for e in entities)
    assert all(0.0 < e.confidence <= 1.0 for e in entities)


def test_heuristic_longest_match_wins() -> None:
    # "finance team" should be matched as one entity, not also "finance".
    entities, _ = HeuristicExtractor().extract("c", "Route to the finance team for approval.")
    names = [e.name for e in entities]
    assert "finance team" in names
    assert "finance" not in names


def test_heuristic_extracts_relation_with_provenance() -> None:
    _, relations = HeuristicExtractor().extract("chunk-1", REFUND)
    edge = {(r.subject, r.predicate, r.object) for r in relations}
    assert ("support agent", "requires_approval_from", "finance team") in edge
    assert all(r.source_chunk_id == "chunk-1" for r in relations)


def test_heuristic_no_entities_in_unrelated_text() -> None:
    entities, relations = HeuristicExtractor().extract("c", "The weather was sunny today.")
    assert entities == []
    assert relations == []


# --- LLM path with an injected `complete` (no provider/SDK dependency) ----------


def test_llm_extractor_parses_structured_output() -> None:
    calls: list[dict] = []

    def fake_complete(**kwargs: object) -> str:
        calls.append(kwargs)
        return (
            '{"entities": [{"name": "finance team", "type": "team"}], '
            '"relations": [{"subject": "support agent", "predicate": '
            '"requires_approval_from", "object": "finance team"}]}'
        )

    entities, relations = LlmExtractor(complete=fake_complete).extract("chunk-9", REFUND)
    assert entities[0].name == "finance team"
    assert entities[0].source_chunk_id == "chunk-9"
    assert relations[0].predicate == "requires_approval_from"
    # The chunk text + schema were passed to the gateway.
    assert REFUND in calls[0]["user"]
    assert calls[0]["json_schema"]["required"] == ["entities", "relations"]


def test_factory_defaults_to_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_EXTRACTOR", raising=False)
    assert isinstance(get_extractor(), HeuristicExtractor)


def test_factory_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown extractor"):
        get_extractor("ouija")
