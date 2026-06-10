"""Process-extraction eval harness (docs/RETRIEVAL_AND_ML.md §5).

Reads the *persisted* process bodies for a seeded tenant (what `/processes` and
`/ask` actually serve), then scores them against the process golden set and the
tenant's real chunks. The headline `process_citation_validity` feeds the
blocking gate; precision/recall/actor-accuracy are advisory (M2-PLAN D-gate).
"""

from __future__ import annotations

import json
import uuid
from importlib import resources
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.eval.process_metrics import (
    actor_resolution_accuracy,
    citation_validity,
    step_precision_recall,
)
from cortex.knowledge import get_process_body, list_processes


class ProcessEvalReport(BaseModel):
    n_processes: int
    n_golden: int
    metrics: dict[str, float]


def load_process_golden(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        ref = resources.files("cortex.eval") / "data" / "golden_processes.jsonl"
        text = ref.read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def _tenant_chunk_text(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, str]:
    rows = await session.execute(
        sa.text("SELECT id::text AS id, text FROM chunks WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    return {r.id: r.text for r in rows}


async def run_process_eval(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    golden_path: Path | None = None,
) -> ProcessEvalReport:
    """Score the tenant's persisted processes against golden + real chunks."""
    summaries = await list_processes(session, tenant_id=tenant_id)
    bodies: list[dict[str, Any]] = []
    for summary in summaries:
        body = await get_process_body(
            session, tenant_id=tenant_id, process_id=uuid.UUID(summary.id)
        )
        if body is not None:
            bodies.append(body)

    golden = load_process_golden(golden_path)
    text_by_chunk = await _tenant_chunk_text(session, tenant_id)
    valid_ids = set(text_by_chunk)

    precision, recall = step_precision_recall(bodies, golden)
    metrics = {
        "process_precision": precision,
        "process_recall": recall,
        "actor_resolution_accuracy": actor_resolution_accuracy(bodies, golden),
        "process_citation_validity": citation_validity(bodies, valid_ids, text_by_chunk),
    }
    return ProcessEvalReport(n_processes=len(bodies), n_golden=len(golden), metrics=metrics)
