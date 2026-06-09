"""Embeddings: base bge-small-en-v1.5 (384-d), fine-tuned variant behind a flag.

See docs/RETRIEVAL_AND_ML.md §2. Heavy ML deps are the `ml`/`onnx` extras. Stub.
"""

from __future__ import annotations


def embed(texts: list[str]) -> list[list[float]]:
    """Batch-embed `context_blurb + text`. M0 (base) / M5 (fine-tuned)."""
    raise NotImplementedError("embedding lands in M0 (base) and M5 (fine-tuned)")
