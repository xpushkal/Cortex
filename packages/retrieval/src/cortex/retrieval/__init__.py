"""Cortex retrieval plane: chunking, embeddings, hybrid retrieve + rerank.

See docs/RETRIEVAL_AND_ML.md for the design and the eval-gated quality bar.
"""

from cortex.retrieval.chunking import chunk
from cortex.retrieval.embedding import DIM, Embedder, HashingEmbedder, get_embedder
from cortex.retrieval.fusion import reciprocal_rank_fusion

__all__ = [
    "DIM",
    "Embedder",
    "HashingEmbedder",
    "chunk",
    "get_embedder",
    "reciprocal_rank_fusion",
]
