"""Cortex retrieval plane: chunking, embeddings, hybrid retrieve + rerank.

See docs/RETRIEVAL_AND_ML.md for the design and the eval-gated quality bar.
"""

from cortex.retrieval.blurb import BlurbGenerator, TemplateBlurb, get_blurb_generator
from cortex.retrieval.chunking import chunk
from cortex.retrieval.embedding import DIM, Embedder, HashingEmbedder, get_embedder
from cortex.retrieval.fusion import reciprocal_rank_fusion
from cortex.retrieval.hybrid import SearchMode, hybrid_search
from cortex.retrieval.rerank import PassthroughReranker, Reranker, get_reranker

__all__ = [
    "DIM",
    "BlurbGenerator",
    "Embedder",
    "HashingEmbedder",
    "PassthroughReranker",
    "Reranker",
    "SearchMode",
    "TemplateBlurb",
    "chunk",
    "get_blurb_generator",
    "get_embedder",
    "get_reranker",
    "hybrid_search",
    "reciprocal_rank_fusion",
]
