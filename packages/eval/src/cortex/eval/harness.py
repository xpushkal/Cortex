"""Retrieval eval harness (docs/RETRIEVAL_AND_ML.md §5).

Loads the golden set, resolves its stable labels — `(artifact external_id,
chunk ordinal)` pairs, which survive re-ingestion where raw chunk UUIDs do not
(docs/plans/M1-PLAN.md D5) — to live chunk ids, runs retrieval per query, and
computes Recall@k / nDCG@k / MRR. Emits a markdown + JSON report with deltas
vs the previous run; the headline metrics feed `evaluate_gate`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import sqlalchemy as sa
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.eval.metrics import mrr, ndcg_at_k, recall_at_k
from cortex.retrieval import Reranker, hybrid_search
from cortex.retrieval.embedding import Embedder
from cortex.retrieval.hybrid import SearchMode

DEFAULT_K_VALUES = (5, 10, 20)


class GoldenExample(BaseModel):
    query: str
    relevant: list[tuple[str, int]]  # (artifact external_id, chunk ordinal)
    split: str  # dev | test


class QueryResult(BaseModel):
    query: str
    metrics: dict[str, float]


class EvalReport(BaseModel):
    ran_at: str
    mode: str
    split: str
    n_queries: int
    metrics: dict[str, float]  # mean over queries
    per_query: list[QueryResult]


def load_golden(path: Path | None = None) -> list[GoldenExample]:
    """Load the golden set; defaults to the packaged golden_retrieval.jsonl."""
    if path is None:
        ref = resources.files("cortex.eval") / "data" / "golden_retrieval.jsonl"
        text = ref.read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    return [GoldenExample.model_validate_json(line) for line in text.splitlines() if line.strip()]


async def resolve_labels(
    session: AsyncSession, *, tenant_id: uuid.UUID, examples: list[GoldenExample]
) -> dict[tuple[str, int], str]:
    """Map (external_id, ordinal) labels to live chunk ids; missing labels raise.

    A missing label means chunk boundaries moved without the golden set being
    re-authored — failing loudly here protects the metrics from silent drift.
    """
    rows = await session.execute(
        sa.text(
            "SELECT a.external_id, c.ordinal, c.id::text AS chunk_id "
            "FROM chunks c JOIN artifacts a ON a.id = c.artifact_id "
            "WHERE c.tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    live = {(r.external_id, r.ordinal): r.chunk_id for r in rows}
    wanted = {label for ex in examples for label in ex.relevant}
    missing = sorted(label for label in wanted if label not in live)
    if missing:
        raise ValueError(
            f"golden labels not found in tenant {tenant_id} (chunking drift? re-seed "
            f"or re-author the golden set): {missing}"
        )
    return {label: live[label] for label in wanted}


async def run_retrieval_eval(
    *,
    tenant_id: uuid.UUID,
    session: AsyncSession,
    qdrant: AsyncQdrantClient,
    embedder: Embedder,
    reranker: Reranker,
    split: str = "test",
    mode: SearchMode = "hybrid",
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
    golden_path: Path | None = None,
) -> EvalReport:
    """Run retrieval over the golden split and return mean metrics."""
    examples = [ex for ex in load_golden(golden_path) if ex.split == split]
    if not examples:
        raise ValueError(f"golden set has no examples for split {split!r}")
    labels = await resolve_labels(session, tenant_id=tenant_id, examples=examples)

    per_query: list[QueryResult] = []
    for ex in examples:
        hits = await hybrid_search(
            query=ex.query,
            tenant_id=tenant_id,
            session=session,
            qdrant=qdrant,
            embedder=embedder,
            reranker=reranker,
            k=max(k_values),
            mode=mode,
        )
        ranked = [h.chunk_id for h in hits]
        relevant = {labels[label] for label in ex.relevant}
        metrics: dict[str, float] = {"mrr": mrr(ranked, relevant)}
        for k in k_values:
            metrics[f"recall_at_{k}"] = recall_at_k(ranked, relevant, k)
            metrics[f"ndcg_at_{k}"] = ndcg_at_k(ranked, relevant, k)
        per_query.append(QueryResult(query=ex.query, metrics=metrics))

    names = per_query[0].metrics.keys()
    mean = {name: sum(q.metrics[name] for q in per_query) / len(per_query) for name in names}
    return EvalReport(
        ran_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        mode=mode,
        split=split,
        n_queries=len(per_query),
        metrics=mean,
        per_query=per_query,
    )


def emit_report(report: EvalReport, out_dir: Path = Path(".eval-reports")) -> tuple[Path, Path]:
    """Write report.json + report.md (with deltas vs the previous JSON, if any)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"

    previous: dict[str, float] = {}
    if json_path.exists():
        previous = json.loads(json_path.read_text()).get("metrics", {})

    json_path.write_text(report.model_dump_json(indent=2) + "\n")

    lines = [
        f"# Retrieval eval — {report.mode} / {report.split} split",
        "",
        f"Ran {report.ran_at} over {report.n_queries} queries.",
        "",
        "| metric | value | Δ vs last |",
        "|---|---:|---:|",
    ]
    for name in sorted(report.metrics):
        value = report.metrics[name]
        delta = f"{value - previous[name]:+.4f}" if name in previous else "—"
        lines.append(f"| {name} | {value:.4f} | {delta} |")
    lines += ["", "## Worst queries (by MRR)", ""]
    for q in sorted(report.per_query, key=lambda q: q.metrics["mrr"])[:5]:
        lines.append(f"- `{q.query}` — mrr {q.metrics['mrr']:.2f}")
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path
