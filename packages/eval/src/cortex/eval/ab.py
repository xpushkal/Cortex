"""A/B comparison + acceptance gate for the embedding fine-tune (RETRIEVAL_AND_ML.md §2).

The fine-tuned model ships only if it beats base `bge-small` on the held-out
golden set by **≥ 0.05 Recall@10 and ≥ 0.03 nDCG@10** ("5%" read as +0.05
absolute). `ab_compare` is pure and unit-tested; `scripts/train_embeddings.py`
feeds it the base and fine-tuned harness metrics and refuses to ship on failure.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

RECALL_AT_10_MIN_DELTA = 0.05
NDCG_AT_10_MIN_DELTA = 0.03
_EPS = 1e-9  # tolerance so a boundary-equal delta (≥) isn't failed by float noise


class ABReport(BaseModel):
    base: dict[str, float]
    finetuned: dict[str, float]
    deltas: dict[str, float]
    passed: bool
    reasons: list[str]  # why it failed, if it did


def ab_compare(base: dict[str, float], finetuned: dict[str, float]) -> ABReport:
    """Compare fine-tuned vs base metrics against the acceptance thresholds."""
    deltas = {
        name: finetuned.get(name, 0.0) - base.get(name, 0.0) for name in set(base) | set(finetuned)
    }
    reasons: list[str] = []
    d_recall = deltas.get("recall_at_10", 0.0)
    d_ndcg = deltas.get("ndcg_at_10", 0.0)
    if d_recall < RECALL_AT_10_MIN_DELTA - _EPS:
        reasons.append(f"Δrecall_at_10 {d_recall:+.4f} < {RECALL_AT_10_MIN_DELTA:+.4f}")
    if d_ndcg < NDCG_AT_10_MIN_DELTA - _EPS:
        reasons.append(f"Δndcg_at_10 {d_ndcg:+.4f} < {NDCG_AT_10_MIN_DELTA:+.4f}")
    return ABReport(
        base=base, finetuned=finetuned, deltas=deltas, passed=not reasons, reasons=reasons
    )


def emit_ab_report(
    report: ABReport, out_dir: Path = Path(".embeddings-report")
) -> tuple[Path, Path]:
    """Write the A/B comparison as report.json + report.md."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ab_report.json"
    md_path = out_dir / "ab_report.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n")

    verdict = "SHIP ✅" if report.passed else "DO NOT SHIP ❌"
    lines = [
        f"# Embedding A/B — base vs fine-tuned ({verdict})",
        "",
        "| metric | base | fine-tuned | Δ |",
        "|---|---:|---:|---:|",
    ]
    for name in sorted(report.deltas):
        lines.append(
            f"| {name} | {report.base.get(name, 0.0):.4f} | "
            f"{report.finetuned.get(name, 0.0):.4f} | {report.deltas[name]:+.4f} |"
        )
    if report.reasons:
        lines += ["", "## Failed thresholds", *(f"- {r}" for r in report.reasons)]
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path
