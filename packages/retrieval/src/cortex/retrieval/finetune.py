"""Fine-tune data pipeline (docs/RETRIEVAL_AND_ML.md §2).

Builds the contrastive training set for the BGE fine-tune: synthetic queries
(round-trip filtered) augment the golden `(query → relevant chunk)` pairs, and
hard negatives are mined from the base retriever. Everything here is pure over
the `Embedder` interface, so it is deterministic and CI-tested with the hashing
embedder; the actual `.fit()` lives in `scripts/train_embeddings.py` behind the
`ml` extra.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from cortex.retrieval.embedding import Embedder

# A (query, set of relevant chunk ids) training label.
LabeledQuery = tuple[str, set[str]]

_TOKEN = re.compile(r"[a-z0-9$]+")
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "or",
        "for",
        "in",
        "on",
        "at",
        "by",
        "is",
        "are",
        "be",
        "it",
        "its",
        "this",
        "that",
        "with",
        "as",
        "from",
        "into",
        "within",
        "then",
        "than",
        "must",
        "should",
        "can",
        "may",
        "will",
        "if",
        "any",
        "every",
        "all",
        "be",
        "can",
    ]
)
_QUERYGEN_MODEL = "claude-haiku-4-5"


class SyntheticQuery(BaseModel):
    query: str
    chunk_id: str


def _salient(text: str, *, limit: int) -> list[str]:
    seen: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOPWORDS or len(tok) <= 2 or tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


class QueryGenerator(Protocol):
    def generate(self, text: str) -> list[str]:
        """Return synthetic queries a user might ask that this chunk answers."""
        ...


class TemplateQueryGenerator:
    """Deterministic salient-keyword query — the dependency-free CI default."""

    def __init__(self, terms: int = 6) -> None:
        self._terms = terms

    def generate(self, text: str) -> list[str]:
        terms = _salient(text, limit=self._terms)
        return [" ".join(terms)] if terms else []


class LlmQueryGenerator:
    """Natural questions via claude-haiku-4-5 (the `llm` extra); injectable client."""

    def __init__(self, n: int = 2, model: str = _QUERYGEN_MODEL, client: Any | None = None) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - only without the extra
                raise RuntimeError(
                    "LlmQueryGenerator needs the 'llm' extra: uv sync --extra llm"
                ) from exc
            client = anthropic.Anthropic()
        self._client = client
        self._model = model
        self._n = n

    def generate(self, text: str) -> list[str]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            system=(
                f"Write {self._n} short, natural search queries a user would type "
                "that this text answers. One per line, no numbering."
            ),
            messages=[{"role": "user", "content": text}],
        )
        body = next(b.text for b in response.content if b.type == "text")
        return [line.strip(" -*\t") for line in body.splitlines() if line.strip()]


def get_query_generator(mode: str | None = None) -> QueryGenerator:
    """Return the configured generator. CORTEX_QUERYGEN=template|llm (default template)."""
    choice = (mode or os.environ.get("CORTEX_QUERYGEN", "template")).lower()
    if choice == "template":
        return TemplateQueryGenerator()
    if choice == "llm":
        return LlmQueryGenerator()
    raise ValueError(f"unknown query generator: {choice!r}")


def generate_synthetic_queries(
    chunks: list[tuple[str, str]], *, generator: QueryGenerator | None = None
) -> list[SyntheticQuery]:
    """Generate `(query, chunk_id)` pairs from `(chunk_id, text)` chunks."""
    generator = generator or get_query_generator()
    pairs: list[SyntheticQuery] = []
    for chunk_id, text in chunks:
        for query in generator.generate(text):
            if query:
                pairs.append(SyntheticQuery(query=query, chunk_id=chunk_id))
    return pairs


def _rank(
    query_vec: list[float], corpus_ids: list[str], corpus_vecs: list[list[float]]
) -> list[str]:
    # Embedders return L2-normalized vectors, so dot product == cosine.
    scored = (
        (sum(q * c for q, c in zip(query_vec, vec, strict=True)), cid)
        for cid, vec in zip(corpus_ids, corpus_vecs, strict=True)
    )
    return [cid for _, cid in sorted(scored, key=lambda s: -s[0])]


def filter_round_trip(
    pairs: list[SyntheticQuery],
    corpus: dict[str, str],
    embedder: Embedder,
    *,
    k: int = 10,
) -> list[SyntheticQuery]:
    """Keep only queries whose source chunk is retrieved in the top-k.

    Drops ambiguous/leaky synthetic queries — round-trip consistency (§2). The
    corpus is embedded once; ranking is cosine over the `Embedder` interface, so
    this is deterministic with the hashing embedder.
    """
    if not pairs:
        return []
    corpus_ids = list(corpus)
    corpus_vecs = embedder.embed([corpus[cid] for cid in corpus_ids])
    query_vecs = embedder.embed([p.query for p in pairs])
    kept: list[SyntheticQuery] = []
    for pair, qvec in zip(pairs, query_vecs, strict=True):
        if pair.chunk_id in _rank(qvec, corpus_ids, corpus_vecs)[:k]:
            kept.append(pair)
    return kept


# --- hard-negative mining + training-data assembly ------------------------------


class TrainingExample(BaseModel):
    """One contrastive example for MultipleNegativesRankingLoss."""

    query: str
    positive: str  # relevant chunk text (the anchor's positive)
    negatives: list[str] = []  # mined hard-negative chunk texts


def mine_hard_negatives(
    labeled: list[LabeledQuery],
    corpus: dict[str, str],
    embedder: Embedder,
    *,
    fetch_k: int = 20,
    cap: int = 3,
) -> list[list[str]]:
    """Per labeled query, the highest-ranked non-relevant chunk ids (hard negatives).

    Runs the base retriever over each query and keeps the top non-positive chunks,
    capped — the chunks the model confuses with the answer (§2). Deterministic
    over the `Embedder` interface; returned list is aligned with `labeled`.
    """
    corpus_ids = list(corpus)
    corpus_vecs = embedder.embed([corpus[cid] for cid in corpus_ids])
    query_vecs = embedder.embed([q for q, _ in labeled])
    out: list[list[str]] = []
    for (_, positives), qvec in zip(labeled, query_vecs, strict=True):
        ranked = _rank(qvec, corpus_ids, corpus_vecs)[:fetch_k]
        out.append([cid for cid in ranked if cid not in positives][:cap])
    return out


def build_training_examples(
    labeled: list[LabeledQuery],
    hard_negatives: list[list[str]],
    corpus: dict[str, str],
) -> list[TrainingExample]:
    """Assemble (query, positive_text, [hard_negative_texts]) training examples."""
    examples: list[TrainingExample] = []
    for (query, positives), neg_ids in zip(labeled, hard_negatives, strict=True):
        neg_texts = [corpus[n] for n in neg_ids if n in corpus]
        for pid in sorted(positives):
            if pid in corpus:
                examples.append(
                    TrainingExample(query=query, positive=corpus[pid], negatives=neg_texts)
                )
    return examples


def dump_training_examples(examples: list[TrainingExample], path: Path) -> None:
    """Write examples as JSONL (the shape train_embeddings.py reads)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(e.model_dump_json() for e in examples) + "\n", encoding="utf-8")


def load_training_examples(path: Path) -> list[TrainingExample]:
    text = path.read_text(encoding="utf-8")
    return [TrainingExample.model_validate_json(line) for line in text.splitlines() if line.strip()]
