"""Process extraction — the product core (docs/RETRIEVAL_AND_ML.md §4.2).

A cluster of chunks describing one recurring task is synthesized into a
`Process`: imperative steps, **each citing the source chunk it came from**. The
pipeline is: synthesize → Pydantic validation (the citation invariant) →
faithfulness gate (drop steps the cited chunk doesn't support) → emit only
fully-cited, faithful processes.

Two synthesizers behind one interface (the M0/M1 pattern):
  - HeuristicProcessSynth (default): split chunks into sentences, keep the
    procedural ones (action/modal cues), cite the source chunk. Faithful by
    construction (the step text is a span of the cited chunk). Runs in CI.
  - LlmProcessSynth: synthesis via the pluggable gateway (cortex.obs.complete
    — Anthropic or OpenRouter, CORTEX_LLM_PROVIDER); never runs in CI.

Select via CORTEX_EXTRACTOR=heuristic|llm (default heuristic).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from cortex.knowledge.faithfulness import is_faithful
from cortex.knowledge.models import (
    Citation,
    Process,
    ProcessCluster,
    ProcessStep,
)
from cortex.obs import complete as llm_complete
from cortex.obs import loads_json

# A pluggable LLM completion callable (cortex.obs.complete), injectable for tests.
Completer = Callable[..., str]

# Verb/modal cues that mark a sentence as a procedural step (vs. a title or
# definition). A general signal, not memorized sample text.
_ACTION_WORDS = (
    "issue issued issues route routed routes review reviews reviewed approve approves "
    "approved submit submitted verify verifies verified escalate escalates page pages "
    "create creates send sends assign assigns delete deletes merge merged request "
    "requests schedule schedules record records report reports trigger triggers promote "
    "lock locked reset cancel cancelled coordinate notify confirm confirms must require "
    "requires"
)
_ACTION_CUES = frozenset(_ACTION_WORDS.split())

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def _is_procedural(sentence: str) -> bool:
    words = {w.strip(".,:;").lower() for w in sentence.split()}
    return bool(words & _ACTION_CUES)


class ProcessSynth(Protocol):
    def synthesize(self, cluster: ProcessCluster) -> Process | None:
        """Synthesize a candidate Process from a cluster, or None if not procedural."""
        ...


class HeuristicProcessSynth:
    """Sentence-splitting synthesizer. Steps are spans of their cited chunk."""

    def synthesize(self, cluster: ProcessCluster) -> Process | None:
        steps: list[ProcessStep] = []
        ordinal = 1
        for chunk in cluster.chunks:
            for sentence in _sentences(chunk.text):
                if not _is_procedural(sentence):
                    continue
                steps.append(
                    ProcessStep(
                        ordinal=ordinal,
                        action=sentence,
                        citations=[Citation(chunk_id=chunk.chunk_id, quote=sentence)],
                    )
                )
                ordinal += 1
        if not steps:
            return None
        return Process(name=cluster.name, trigger=cluster.trigger, steps=steps)


class LlmProcessSynth:
    """Process synthesis via the pluggable LLM gateway (Anthropic | OpenRouter).

    The schema constrains each step to cite a `chunk_id`; the faithfulness gate
    downstream drops any step whose citation the cluster text doesn't support.
    """

    _SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "actor": {"type": "string"},
                        "chunk_id": {"type": "string"},
                    },
                    "required": ["action", "chunk_id"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    }

    def __init__(self, model: str | None = None, complete: Completer | None = None) -> None:
        self._model = model
        self._complete = complete or llm_complete

    def synthesize(self, cluster: ProcessCluster) -> Process | None:
        catalog = "\n".join(f"[{c.chunk_id}] {c.text}" for c in cluster.chunks)
        raw = self._complete(
            system=(
                "Assemble the recurring task in these source chunks into ordered, "
                "imperative steps. Every step MUST cite the chunk_id it is grounded "
                "in. Only include steps stated in the sources."
            ),
            user=f"Task: {cluster.name}\n\n{catalog}",
            model=self._model,
            max_tokens=2048,
            json_schema=self._SCHEMA,
        )
        payload = loads_json(raw)
        # JSON mode instructs but doesn't enforce the schema; keep only well-formed,
        # cited steps (an action + a chunk_id) and drop the rest.
        steps: list[ProcessStep] = []
        for s in payload.get("steps", []):
            action = s.get("action") or s.get("step")
            chunk_id = s.get("chunk_id") or s.get("citation")
            if action and chunk_id:
                steps.append(
                    ProcessStep(
                        ordinal=len(steps) + 1,
                        action=action,
                        actor=s.get("actor"),
                        citations=[Citation(chunk_id=chunk_id)],
                    )
                )
        if not steps:
            return None
        return Process(name=cluster.name, trigger=cluster.trigger, steps=steps)


def get_process_synth(mode: str | None = None) -> ProcessSynth:
    """Return the configured synthesizer. CORTEX_EXTRACTOR=heuristic|llm (default heuristic)."""
    choice = (mode or os.environ.get("CORTEX_EXTRACTOR", "heuristic")).lower()
    if choice == "heuristic":
        return HeuristicProcessSynth()
    if choice == "llm":
        return LlmProcessSynth()
    raise ValueError(f"unknown process synthesizer: {choice!r}")


def extract_processes(
    clusters: list[ProcessCluster],
    *,
    synth: ProcessSynth | None = None,
    faithfulness_threshold: float = 0.5,
) -> list[Process]:
    """Synthesize, validate, and faithfulness-gate processes from clusters.

    Steps whose citations are not supported by the cluster's chunk text are
    dropped; a process with no surviving steps is discarded. Only fully-cited,
    faithful processes are returned.
    """
    synth = synth or get_process_synth()
    out: list[Process] = []
    for cluster in clusters:
        candidate = synth.synthesize(cluster)
        if candidate is None:
            continue
        text_by_chunk = {c.chunk_id: c.text for c in cluster.chunks}
        kept: list[ProcessStep] = []
        for step in candidate.steps:
            cited = [
                text_by_chunk[c.chunk_id] for c in step.citations if c.chunk_id in text_by_chunk
            ]
            if is_faithful(step.action, cited, threshold=faithfulness_threshold):
                kept.append(step.model_copy(update={"ordinal": len(kept) + 1}))
        if not kept:
            continue
        out.append(candidate.model_copy(update={"steps": kept}))
    return out
