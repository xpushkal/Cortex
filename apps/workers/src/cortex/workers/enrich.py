"""M2 knowledge enrichment for the ingestion pipeline (docs/RETRIEVAL_AND_ML.md §4).

Given an artifact's persisted chunks, extract the knowledge graph (entities +
relations, with provenance) and synthesize cited process objects, then persist
both. Runs inside the ingest transaction so chunk ids resolve and everything
commits atomically. Idempotent by construction — `save_graph` / `save_process`
de-duplicate and version rather than clobber.
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cortex.knowledge import (
    ChunkRef,
    Extractor,
    ProcessCluster,
    extract_processes,
    resolve_entities,
    save_graph,
    save_process,
)
from cortex.knowledge.models import EntityCandidate, RelationCandidate


def _detect_actor(action: str, alias_to_canonical: dict[str, str]) -> str | None:
    """Set a step's actor to the longest entity alias mentioned in the action."""
    lower = action.lower()
    for alias in sorted(alias_to_canonical, key=len, reverse=True):
        if alias in lower:
            return alias_to_canonical[alias]
    return None


async def enrich_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    trigger: str,
    chunks: list[ChunkRef],
    extractor: Extractor,
) -> None:
    """Extract + persist the graph and process objects for one artifact's chunks."""
    # Best-effort enrichment: an LLM extractor can fail on a chunk (provider error,
    # malformed reply) — skip that chunk rather than abort the whole ingest. The
    # deterministic heuristic extractor never raises, so this is a no-op for it.
    entities: list[EntityCandidate] = []
    relations: list[RelationCandidate] = []
    for ref in chunks:
        try:
            ents, rels = extractor.extract(ref.chunk_id, ref.text)
        except Exception as exc:
            print(f"warn: entity extraction skipped chunk {ref.chunk_id}: {exc}", file=sys.stderr)
            continue
        entities.extend(ents)
        relations.extend(rels)

    resolved = resolve_entities(entities)
    name_to_id = await save_graph(
        session, tenant_id=tenant_id, entities=resolved, relations=relations
    )

    alias_to_canonical = {
        alias.lower(): ent.name for ent in resolved for alias in [ent.name, *ent.aliases]
    }
    cluster = ProcessCluster(name=name, trigger=trigger, chunks=chunks)
    try:
        processes = extract_processes([cluster])
    except Exception as exc:
        print(f"warn: process synthesis skipped {name!r}: {exc}", file=sys.stderr)
        processes = []
    for proc in processes:
        steps = [
            step.model_copy(update={"actor": _detect_actor(step.action, alias_to_canonical)})
            for step in proc.steps
        ]
        await save_process(
            session,
            tenant_id=tenant_id,
            process=proc.model_copy(update={"steps": steps}),
            actor_resolver=name_to_id,
        )
