"""Entity/relation + process extraction (M2). Stubs only — see docs/RETRIEVAL_AND_ML.md §4."""

from __future__ import annotations

from cortex.knowledge.models import Process


def extract_processes(chunks: list[str], *, tenant_id: str) -> list[Process]:
    """Cluster chunks describing a recurring task and synthesize cited processes.

    M2 deliverable. Synthesis must emit the canonical schema with a citation per
    step, then pass the faithfulness (NLI/LLM-judge) gate before persisting.
    """
    raise NotImplementedError("process extraction lands in M2")
