"""The per-artifact ingestion pipeline (docs/INGESTION.md §2).

    normalize -> (content_hash changed?) -> chunk -> contextualize -> embed
              -> extract -> upsert -> mark dependents stale

Each stage is a small, unit-testable function. Embeddings and LLM extraction are
batched across a job's chunks to amortize cost. Stubs land their logic in M0-M2.
"""

from __future__ import annotations


async def run_pipeline(artifact_id: str, *, tenant_id: str) -> None:
    """Orchestrate the stages for one artifact. Idempotent: unchanged hash = no-op."""
    raise NotImplementedError("ingestion pipeline lands in M0 (chunk->embed->upsert)")
