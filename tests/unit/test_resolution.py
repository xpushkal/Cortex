"""Entity resolution / alias merging (M2; docs/RETRIEVAL_AND_ML.md §4.1)."""

from __future__ import annotations

from cortex.knowledge.models import EntityCandidate
from cortex.knowledge.resolution import resolve_entities


def _c(name: str, type_: str, chunk: str, conf: float = 0.8) -> EntityCandidate:
    return EntityCandidate(name=name, type=type_, source_chunk_id=chunk, confidence=conf)


def test_case_and_article_variants_merge() -> None:
    resolved = resolve_entities(
        [_c("Finance Team", "team", "a"), _c("the finance team", "team", "b")]
    )
    assert len(resolved) == 1
    ent = resolved[0]
    assert ent.aliases == ["Finance Team", "the finance team"]
    assert ent.chunk_ids == ["a", "b"]  # provenance unioned + deduped


def test_seed_synonyms_merge_short_form() -> None:
    resolved = resolve_entities([_c("finance", "team", "a"), _c("finance team", "team", "b")])
    assert len(resolved) == 1
    assert resolved[0].name == "finance team"  # canonical = most specific
    assert set(resolved[0].aliases) == {"finance", "finance team"}


def test_distinct_entities_stay_distinct() -> None:
    # "manager" must NOT merge into "engineering manager" (different roles).
    resolved = resolve_entities(
        [_c("manager", "role", "a"), _c("engineering manager", "role", "b")]
    )
    assert {e.name for e in resolved} == {"manager", "engineering manager"}


def test_type_separates_same_name() -> None:
    resolved = resolve_entities([_c("security", "team", "a"), _c("security", "role", "b")])
    assert len(resolved) == 2


def test_idempotent_and_sorted() -> None:
    cands = [_c("finance", "team", "a"), _c("CFO", "role", "b"), _c("finance team", "team", "a")]
    first = resolve_entities(cands)
    second = resolve_entities(cands)
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]
    assert {e.name for e in first} == {"CFO", "finance team"}
    # Deterministic order: (type, name).
    assert first == sorted(first, key=lambda e: (e.type, e.name))


def test_injected_similarity_merges_near_duplicates() -> None:
    # A fake similarity that treats "ml team"/"machine learning team" as identical.
    def sim(a: str, b: str) -> float:
        return 1.0 if {a, b} == {"ml team", "machine learning team"} else 0.0

    resolved = resolve_entities(
        [_c("ml team", "team", "a"), _c("machine learning team", "team", "b")],
        similarity=sim,
        sim_threshold=0.9,
    )
    assert len(resolved) == 1
    assert resolved[0].name == "machine learning team"  # longer canonical
    assert set(resolved[0].chunk_ids) == {"a", "b"}
