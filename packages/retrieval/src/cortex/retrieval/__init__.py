"""Cortex retrieval plane: chunking, embeddings, hybrid retrieve + rerank.

See docs/RETRIEVAL_AND_ML.md for the design and the eval-gated quality bar.
"""

from cortex.retrieval.fusion import reciprocal_rank_fusion

__all__ = ["reciprocal_rank_fusion"]
