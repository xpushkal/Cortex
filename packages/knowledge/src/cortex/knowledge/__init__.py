"""Cortex knowledge plane.

Entity/relation extraction into the graph, and the product's core unit: the
versioned, source-cited **process object**. See docs/DATA_MODEL.md §5.
"""

from cortex.knowledge.contradiction import (
    ContradictionReport,
    StepConflict,
    detect_contradiction,
)
from cortex.knowledge.extraction import (
    HeuristicProcessSynth,
    ProcessSynth,
    extract_processes,
    get_process_synth,
)
from cortex.knowledge.faithfulness import coverage, is_faithful
from cortex.knowledge.freshness import (
    EXPIRED,
    FRESH,
    PROCESS_TTL_SECONDS,
    STALE,
    get_freshness_map,
    mark_processes_stale_for_artifact,
    revalidate_process,
    set_freshness,
    ttl_sweep,
)
from cortex.knowledge.graph import (
    Extractor,
    HeuristicExtractor,
    get_extractor,
)
from cortex.knowledge.models import (
    ChunkRef,
    Citation,
    EntityCandidate,
    Process,
    ProcessCluster,
    ProcessStep,
    RelationCandidate,
    ResolvedEntity,
)
from cortex.knowledge.repository import (
    ProcessSummary,
    get_process_body,
    get_process_versions,
    list_processes,
    match_process,
    review_process,
    save_graph,
    save_process,
)
from cortex.knowledge.resolution import resolve_entities

__all__ = [
    "EXPIRED",
    "FRESH",
    "PROCESS_TTL_SECONDS",
    "STALE",
    "ChunkRef",
    "Citation",
    "ContradictionReport",
    "EntityCandidate",
    "Extractor",
    "HeuristicExtractor",
    "HeuristicProcessSynth",
    "Process",
    "ProcessCluster",
    "ProcessStep",
    "ProcessSummary",
    "ProcessSynth",
    "RelationCandidate",
    "ResolvedEntity",
    "StepConflict",
    "coverage",
    "detect_contradiction",
    "extract_processes",
    "get_extractor",
    "get_freshness_map",
    "get_process_body",
    "get_process_synth",
    "get_process_versions",
    "is_faithful",
    "list_processes",
    "mark_processes_stale_for_artifact",
    "match_process",
    "resolve_entities",
    "revalidate_process",
    "review_process",
    "save_graph",
    "save_process",
    "set_freshness",
    "ttl_sweep",
]
