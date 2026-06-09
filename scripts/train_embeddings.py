"""Fine-tune domain embeddings (M5) — the from-first-principles ML proof.

Pipeline: mine hard negatives -> contrastive fine-tune (MultipleNegativesRankingLoss)
-> eval vs base on the held-out golden set -> emit a comparison report. The
fine-tuned model ships only if it beats base bge-small by >=5% Recall@10 and
>=0.03 nDCG@10 (docs/RETRIEVAL_AND_ML.md §2). Stub entrypoint.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("embedding fine-tune lands in M5")


if __name__ == "__main__":
    main()
