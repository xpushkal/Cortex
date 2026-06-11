"""Cortex retrieval plane: chunking, embeddings, hybrid retrieve + rerank.

See docs/RETRIEVAL_AND_ML.md for the design and the eval-gated quality bar.
"""

from cortex.retrieval.blurb import BlurbGenerator, TemplateBlurb, get_blurb_generator
from cortex.retrieval.chunking import chunk
from cortex.retrieval.embedding import DIM, Embedder, HashingEmbedder, get_embedder
from cortex.retrieval.finetune import (
    LabeledQuery,
    QueryGenerator,
    SyntheticQuery,
    TemplateQueryGenerator,
    TrainingExample,
    build_training_examples,
    dump_training_examples,
    filter_round_trip,
    generate_synthetic_queries,
    get_query_generator,
    load_training_examples,
    mine_hard_negatives,
)
from cortex.retrieval.fusion import reciprocal_rank_fusion
from cortex.retrieval.hybrid import SearchMode, hybrid_search
from cortex.retrieval.rerank import PassthroughReranker, Reranker, get_reranker

__all__ = [
    "DIM",
    "BlurbGenerator",
    "Embedder",
    "HashingEmbedder",
    "LabeledQuery",
    "PassthroughReranker",
    "QueryGenerator",
    "Reranker",
    "SearchMode",
    "SyntheticQuery",
    "TemplateBlurb",
    "TemplateQueryGenerator",
    "TrainingExample",
    "build_training_examples",
    "chunk",
    "dump_training_examples",
    "filter_round_trip",
    "generate_synthetic_queries",
    "get_blurb_generator",
    "get_embedder",
    "get_query_generator",
    "get_reranker",
    "hybrid_search",
    "load_training_examples",
    "mine_hard_negatives",
    "reciprocal_rank_fusion",
]
