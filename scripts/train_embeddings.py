"""Fine-tune domain embeddings (M5) — the from-first-principles ML proof.

Pipeline: build the seed corpus → augment golden pairs with round-trip-filtered
synthetic queries + mined hard negatives → contrastive fine-tune of
`bge-small-en-v1.5` (`MultipleNegativesRankingLoss`) → A/B vs base on the
**held-out test split** → emit a report. The model ships only if it beats base
by ≥ 0.05 Recall@10 and ≥ 0.03 nDCG@10 (docs/RETRIEVAL_AND_ML.md §2); otherwise
this exits non-zero and writes nothing to serving.

The data-prep (`prepare_training_data`) and eval (`evaluate_embedder`) are
deterministic and unit-tested with the hashing embedder. The `.fit()` call needs
the `ml` extra + compute and is not run in CI:

    uv sync --extra ml
    uv run python scripts/train_embeddings.py --epochs 1 --out models/cortex-bge-ft
    # then serve it:  CORTEX_EMBEDDER=finetuned CORTEX_EMBEDDER_MODEL=models/cortex-bge-ft
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cortex.connectors import SampleConnector
from cortex.connectors.base import SourceConfig
from cortex.eval import ab_compare, emit_ab_report, evaluate_embedder, load_golden
from cortex.retrieval import (
    BGEEmbedder,
    FineTunedEmbedder,
    LabeledQuery,
    TrainingExample,
    chunk,
    prepare_training_data,
)

BASE_MODEL = "BAAI/bge-small-en-v1.5"


def build_corpus() -> dict[str, str]:
    """Reconstruct the seed corpus as {`external_id#ordinal`: text}, matching ingest."""
    connector = SampleConnector()
    cfg = SourceConfig(kind="sample")
    corpus: dict[str, str] = {}
    for raw in connector.backfill(cfg):
        art = connector.normalize(raw)
        chunks = chunk(art.content, source_kind=art.source_kind, artifact_kind=art.kind)
        for ordinal, text in enumerate(chunks):
            corpus[f"{art.external_id}#{ordinal}"] = text
    return corpus


def golden_labeled(split: str) -> list[LabeledQuery]:
    """Golden (query, {chunk key}) labels for a split — keys match `build_corpus`."""
    return [
        (ex.query, {f"{ext}#{ordinal}" for ext, ordinal in ex.relevant})
        for ex in load_golden()
        if ex.split == split
    ]


def train(
    examples: list[TrainingExample], *, base: str, out: Path, epochs: int, batch_size: int
) -> Path:
    """Contrastive fine-tune with MultipleNegativesRankingLoss (needs the `ml` extra)."""
    try:
        from sentence_transformers import InputExample, SentenceTransformer, losses
        from torch.utils.data import DataLoader
    except ImportError as exc:  # pragma: no cover - only without the extra
        raise RuntimeError("training needs the 'ml' extra: uv sync --extra ml") from exc

    model = SentenceTransformer(base)
    train_examples = [InputExample(texts=[e.query, e.positive, *e.negatives]) for e in examples]
    loader = DataLoader(train_examples, shuffle=True, batch_size=batch_size)
    loss = losses.MultipleNegativesRankingLoss(model)
    model.fit(
        train_objectives=[(loader, loss)],
        epochs=epochs,
        warmup_steps=min(10, len(train_examples)),
        show_progress_bar=False,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune Cortex domain embeddings (M5).")
    parser.add_argument("--base", default=BASE_MODEL)
    parser.add_argument("--out", type=Path, default=Path("models/cortex-bge-ft"))
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    corpus = build_corpus()
    base_embedder = BGEEmbedder(args.base)

    print(f"# preparing training data ({len(corpus)} chunks, dev split)")
    examples = prepare_training_data(corpus, golden_labeled("dev"), base_embedder)
    print(f"# {len(examples)} training examples; fine-tuning {args.base}")
    model_path = train(
        examples, base=args.base, out=args.out, epochs=args.epochs, batch_size=args.batch_size
    )

    print("# A/B on the held-out test split")
    test = golden_labeled("test")
    base_metrics = evaluate_embedder(base_embedder, test, corpus)
    finetuned_metrics = evaluate_embedder(FineTunedEmbedder(str(model_path)), test, corpus)
    report = ab_compare(base_metrics, finetuned_metrics)
    _, md_path = emit_ab_report(report)
    print(Path(md_path).read_text())

    if not report.passed:
        print(f"# DO NOT SHIP — gate failed: {report.reasons}", file=sys.stderr)
        return 1
    print(f"# SHIP — serve with CORTEX_EMBEDDER=finetuned CORTEX_EMBEDDER_MODEL={model_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
