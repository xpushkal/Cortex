"""Entity resolution — alias merging (docs/RETRIEVAL_AND_ML.md §4.1).

Collapse entity candidates that name the same thing into one canonical
`ResolvedEntity`, unioning surface forms (aliases) and provenance (chunk ids).
Deterministic and idempotent so re-ingest is stable.

Default merge key: normalized name (lowercased, leading article + trailing
punctuation stripped) plus a small seed synonym map for common org short-forms
(`finance` ↔ `finance team`). An optional injectable `similarity` callable —
e.g. embedding cosine via the `ml` extra — additionally merges near-duplicate
canonical names above `sim_threshold`; off by default to keep CI deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from cortex.knowledge.models import EntityCandidate, ResolvedEntity

_ARTICLE = re.compile(r"^(the|a|an)\s+")

# Seed synonyms: short department/role forms → their canonical key. A curated
# starting set; the `similarity` hook generalizes beyond it.
_SYNONYMS: dict[str, str] = {
    "finance": "finance team",
    "security": "security team",
    "support": "support agent",
}


def _normalize(name: str) -> str:
    n = _ARTICLE.sub("", name.strip().lower()).strip(" .")
    return re.sub(r"\s+", " ", n)


def _merge_key(name: str) -> str:
    norm = _normalize(name)
    return _SYNONYMS.get(norm, norm)


def resolve_entities(
    candidates: list[EntityCandidate],
    *,
    similarity: Callable[[str, str], float] | None = None,
    sim_threshold: float = 0.9,
) -> list[ResolvedEntity]:
    """Merge candidates into canonical entities. Deterministic and idempotent."""
    groups: dict[tuple[str, str], list[EntityCandidate]] = {}
    for cand in candidates:
        groups.setdefault((cand.type, _merge_key(cand.name)), []).append(cand)

    resolved = [_collapse(members) for members in groups.values()]

    if similarity is not None:
        resolved = _merge_by_similarity(resolved, similarity, sim_threshold)

    return sorted(resolved, key=lambda e: (e.type, e.name))


def _collapse(members: list[EntityCandidate]) -> ResolvedEntity:
    """One resolved entity from candidates sharing a merge key."""
    surface_forms = sorted({m.name for m in members})
    # Canonical = the longest surface form (most specific).
    canonical = max(surface_forms, key=len)
    chunk_ids = sorted({m.source_chunk_id for m in members})
    return ResolvedEntity(
        name=canonical,
        type=members[0].type,
        aliases=surface_forms,
        chunk_ids=chunk_ids,
        confidence=max(m.confidence for m in members),
    )


def _merge_by_similarity(
    entities: list[ResolvedEntity],
    similarity: Callable[[str, str], float],
    threshold: float,
) -> list[ResolvedEntity]:
    """Union-merge same-type entities whose canonical names are similar enough."""
    out: list[ResolvedEntity] = []
    for ent in sorted(entities, key=lambda e: (e.type, e.name)):
        target = next(
            (o for o in out if o.type == ent.type and similarity(o.name, ent.name) >= threshold),
            None,
        )
        if target is None:
            out.append(ent)
            continue
        merged = ResolvedEntity(
            name=max(target.name, ent.name, key=len),
            type=target.type,
            aliases=sorted(set(target.aliases) | set(ent.aliases)),
            chunk_ids=sorted(set(target.chunk_ids) | set(ent.chunk_ids)),
            confidence=max(target.confidence, ent.confidence),
        )
        out[out.index(target)] = merged
    return out
