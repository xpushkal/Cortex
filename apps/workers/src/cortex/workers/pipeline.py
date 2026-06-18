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

from arq import Retry

from cortex.obs import get_tracer
from cortex.workers.deadletter import record_dead_letter
from cortex.workers.ingest import ingest_event

_tracer = get_tracer(__name__)

# Total attempts before a job is dead-lettered. Mirror this in WorkerSettings.max_tries
# so arq does not give up earlier than we capture the failure. Sized to absorb the
# transient unique-constraint conflicts that concurrent backfill jobs hit while
# racing to create the same shared entity/source — the retry's rolled-back txn finds
# the row already present on the next attempt (optimistic concurrency).
MAX_TRIES = 5


async def run_pipeline(
    ctx: Any,
    *,
    tenant_id: str,
    source_kind: str,
    external_id: str,
    kind: str,
    content: str,
) -> dict[str, Any]:
    """arq job: run the per-artifact pipeline for one changed artifact.

    `ctx` is the arq job context (`None` when invoked inline outside a worker).
    Idempotent: an unchanged content_hash is a no-op. Returns the ingest stats so
    the job result is retrievable via the queue.

    Failure handling (worker path only): a transient error retries up to
    `MAX_TRIES`; the final failure is recorded to the dead-letter list and the job
    completes (rather than erroring) so the lane keeps draining. Inline callers get
    the exception raised so they see ingest failures synchronously.
    """
    payload = {
        "tenant_id": tenant_id,
        "source_kind": source_kind,
        "external_id": external_id,
        "kind": kind,
        "content": content,
    }
    with _tracer.start_as_current_span("ingest.run_pipeline") as span:
        span.set_attribute("cortex.tenant_id", tenant_id)
        span.set_attribute("cortex.source_kind", source_kind)
        span.set_attribute("cortex.external_id", external_id)
        try:
            stats = await ingest_event(
                tenant_id=uuid.UUID(tenant_id),
                source_kind=source_kind,
                external_id=external_id,
                kind=kind,
                content=content,
            )
        except Exception as exc:
            if ctx is None:
                raise  # inline path: surface the failure to the caller
            span.record_exception(exc)
            job_try = int(ctx.get("job_try", 1))
            if job_try < MAX_TRIES:
                # arq only retries on Retry (a bare raise is terminal). Back off a
                # little so racing jobs don't immediately re-collide.
                raise Retry(defer=0.2 * job_try) from exc
            await record_dead_letter(ctx["redis"], payload=payload, error=repr(exc))
            return {"error": repr(exc), "dead_lettered": True}
    return stats.model_dump()
