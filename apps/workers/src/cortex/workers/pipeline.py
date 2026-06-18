"""The per-artifact ingestion pipeline (docs/INGESTION.md §2).

    normalize -> (content_hash changed?) -> chunk -> contextualize -> embed
              -> extract -> upsert -> mark dependents stale

Each stage is a small, unit-testable function; the full chain is implemented in
`cortex.workers.ingest` (`ingest_source` / `ingest_event`) and exercised by the
integration suite. `run_pipeline` is the arq job seam: it wraps `ingest_event` so
the same tested logic runs off the Redis queue. Embeddings and LLM extraction are
batched across an artifact's chunks to amortize cost.
"""

from __future__ import annotations

import uuid
from typing import Any

from cortex.obs import get_tracer
from cortex.workers.ingest import ingest_event

_tracer = get_tracer(__name__)


async def run_pipeline(
    ctx: Any,
    *,
    tenant_id: str,
    source_kind: str,
    external_id: str,
    kind: str,
    content: str,
) -> dict[str, int]:
    """arq job: run the per-artifact pipeline for one changed artifact.

    `ctx` is the arq job context (`None` when invoked inline outside a worker).
    Idempotent: an unchanged content_hash is a no-op. Returns the ingest stats so
    the job result is retrievable via the queue.
    """
    with _tracer.start_as_current_span("ingest.run_pipeline") as span:
        span.set_attribute("cortex.tenant_id", tenant_id)
        span.set_attribute("cortex.source_kind", source_kind)
        span.set_attribute("cortex.external_id", external_id)
        stats = await ingest_event(
            tenant_id=uuid.UUID(tenant_id),
            source_kind=source_kind,
            external_id=external_id,
            kind=kind,
            content=content,
        )
    return stats.model_dump()
