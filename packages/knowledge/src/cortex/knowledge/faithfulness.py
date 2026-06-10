"""Faithfulness gate for process steps (docs/RETRIEVAL_AND_ML.md §4.2).

A process step is *faithful* only if its cited chunk(s) actually support it.
This is the second guard against hallucinated processes (the first being the
Pydantic citation invariant): a step may carry a citation yet say something the
cited chunk never states — faithfulness catches that.

Default check: **lexical entailment** — the fraction of the step action's
salient (non-stopword) tokens that appear in the cited text must clear a
coverage threshold. Dependency-free, deterministic, runs in CI. The NLI /
LLM-judge check (docs §5.3) is `CORTEX_FAITHFULNESS=llm` and is out of scope for
the hermetic default.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9$]+")
_STOPWORD_WORDS = (
    "a an the of to and or for in on at by is are be been being it its this that "
    "with as from into within then than must should can may will if any every all "
    "before after once each per via not no"
)
_STOPWORDS = frozenset(_STOPWORD_WORDS.split())


def _salient(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1}


def coverage(action: str, cited_texts: list[str]) -> float:
    """Fraction of the action's salient tokens present in the cited text(s)."""
    salient = _salient(action)
    if not salient:
        return 1.0  # nothing to ground (e.g. all stopwords); not a faithfulness failure
    cited = set()
    for text in cited_texts:
        cited |= _salient(text)
    return len(salient & cited) / len(salient)


def is_faithful(action: str, cited_texts: list[str], *, threshold: float = 0.5) -> bool:
    """True if the cited text covers enough of the step's salient content.

    An empty `cited_texts` (e.g. a citation to a chunk outside the cluster — a
    hallucinated reference) yields coverage 0.0 and is therefore unfaithful.
    """
    return coverage(action, cited_texts) >= threshold
