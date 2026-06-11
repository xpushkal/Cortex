"""Entity + relation extraction into the knowledge graph (docs/RETRIEVAL_AND_ML.md §4.1).

Per-chunk extraction → typed entity candidates and subject/predicate/object
relation candidates, each carrying its `source_chunk_id` (provenance) and a
confidence. Sub-threshold candidates are dropped by the caller.

Two implementations behind one interface, the M0/M1 pattern:
  - HeuristicExtractor (default): a typed org-entity lexicon + relation-cue
    regexes. A genuine (if naive) NER-lite method — dependency-free, runs in CI.
  - LlmExtractor: LLM extraction via the pluggable gateway (cortex.obs.complete
    — Anthropic or OpenRouter, CORTEX_LLM_PROVIDER); never runs in CI.

Select via CORTEX_EXTRACTOR=heuristic|llm (default heuristic).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from cortex.knowledge.models import EntityCandidate, RelationCandidate
from cortex.obs import complete as llm_complete

# A pluggable LLM completion callable (cortex.obs.complete), injectable for tests.
Completer = Callable[..., str]

# Typed lexicon of common organizational entities. Longest phrases first so
# "finance team" wins over "finance". Generalizes across companies (roles,
# teams, common systems) rather than memorizing the sample corpus.
_LEXICON: list[tuple[str, str]] = [
    ("customer success manager", "role"),
    ("engineering manager", "role"),
    ("incident commander", "role"),
    ("on-call engineer", "role"),
    ("head of finance", "role"),
    ("vp of sales", "role"),
    ("security team", "team"),
    ("finance team", "team"),
    ("deal desk", "system"),
    ("hr portal", "system"),
    ("pagerduty", "system"),
    ("expensify", "system"),
    ("security owner", "role"),
    ("support agent", "role"),
    ("direct manager", "role"),
    ("finance", "team"),
    ("security", "team"),
    ("support", "role"),
    ("manager", "role"),
    ("cfo", "role"),
]

# (regex over lowercased text, predicate). The captured group is the object
# entity; the subject is the nearest preceding lexicon entity in the sentence.
_RELATION_CUES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"routed?\s+to\s+(?:the\s+)?([a-z ]+?)\s+for\s+approval"),
        "requires_approval_from",
    ),
    (
        re.compile(r"approval\s+from\s+(?:the\s+)?([a-z ]+?)(?:\.|,|\s+to\b)"),
        "requires_approval_from",
    ),
    (re.compile(r"escalate\s+to\s+(?:the\s+)?([a-z ]+?)(?:\.|,|\s+if\b)"), "escalates_to"),
    (re.compile(r"approved?\s+by\s+(?:the\s+)?([a-z ]+?)(?:\.|,)"), "approved_by"),
]


class Extractor(Protocol):
    def extract(
        self, chunk_id: str, text: str
    ) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
        """Return (entities, relations) observed in one chunk, with provenance."""
        ...


def _match_entities(text_lower: str) -> list[tuple[int, str, str]]:
    """Lexicon matches as (start_offset, canonical_name, type), longest-first, non-overlapping."""
    spans: list[tuple[int, int]] = []
    found: list[tuple[int, str, str]] = []
    for name, type_ in _LEXICON:
        for m in re.finditer(rf"\b{re.escape(name)}\b", text_lower):
            start, end = m.span()
            if any(start < e and s < end for s, e in spans):
                continue  # overlaps a longer match already taken
            spans.append((start, end))
            found.append((start, name, type_))
    return sorted(found)


class HeuristicExtractor:
    """Lexicon + relation-cue extraction. The dependency-free default and CI path."""

    def extract(
        self, chunk_id: str, text: str
    ) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
        lower = text.lower()
        matched = _match_entities(lower)
        entities = [
            EntityCandidate(name=name, type=type_, source_chunk_id=chunk_id, confidence=0.8)
            for _, name, type_ in matched
        ]
        relations: list[RelationCandidate] = []
        for pattern, predicate in _RELATION_CUES:
            for m in pattern.finditer(lower):
                obj = self._canonical_object(m.group(1))
                if obj is None:
                    continue
                subject = self._subject_before(matched, m.start(), exclude=obj)
                if subject is None or subject == obj:
                    continue
                relations.append(
                    RelationCandidate(
                        subject=subject,
                        predicate=predicate,
                        object=obj,
                        source_chunk_id=chunk_id,
                        confidence=0.7,
                    )
                )
        return entities, relations

    @staticmethod
    def _canonical_object(raw: str) -> str | None:
        """Resolve a captured phrase to a lexicon entity name (longest containment)."""
        raw = raw.strip()
        for name, _ in _LEXICON:  # lexicon is longest-first
            if name in raw or raw in name:
                return name
        return None

    @staticmethod
    def _subject_before(
        matched: list[tuple[int, str, str]], cue_start: int, *, exclude: str
    ) -> str | None:
        candidates = [name for start, name, _ in matched if start < cue_start and name != exclude]
        return candidates[-1] if candidates else None


class LlmExtractor:
    """Entity/relation extraction via the pluggable LLM gateway (Anthropic | OpenRouter)."""

    _SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["name", "type"],
                    "additionalProperties": False,
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                    },
                    "required": ["subject", "predicate", "object"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["entities", "relations"],
        "additionalProperties": False,
    }

    def __init__(self, model: str | None = None, complete: Completer | None = None) -> None:
        self._model = model
        self._complete = complete or llm_complete

    def extract(
        self, chunk_id: str, text: str
    ) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
        raw = self._complete(
            system=(
                "Extract organizational entities (people, teams, roles, systems, "
                "policies) and their relations (approves, requires_approval_from, "
                "escalates_to, owns, reports_to) from the text. Only what is stated."
            ),
            user=text,
            model=self._model,
            max_tokens=1024,
            json_schema=self._SCHEMA,
        )
        payload = json.loads(raw)
        entities = [
            EntityCandidate(
                name=e["name"], type=e["type"], source_chunk_id=chunk_id, confidence=0.9
            )
            for e in payload.get("entities", [])
        ]
        relations = [
            RelationCandidate(
                subject=r["subject"],
                predicate=r["predicate"],
                object=r["object"],
                source_chunk_id=chunk_id,
                confidence=0.9,
            )
            for r in payload.get("relations", [])
        ]
        return entities, relations


def get_extractor(name: str | None = None) -> Extractor:
    """Return the configured extractor. CORTEX_EXTRACTOR=heuristic|llm (default heuristic)."""
    choice = (name or os.environ.get("CORTEX_EXTRACTOR", "heuristic")).lower()
    if choice == "heuristic":
        return HeuristicExtractor()
    if choice == "llm":
        return LlmExtractor()
    raise ValueError(f"unknown extractor: {choice!r}")
