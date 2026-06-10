"""Process-extraction metrics (docs/RETRIEVAL_AND_ML.md §5.2).

Computed over the *shipped* process bodies (canonical JSON with cited steps):

  - step precision / recall vs the process golden set — does the extractor find
    the real steps, and are its steps real? (advisory; see M2-PLAN D-gate)
  - actor-resolution accuracy — did the expected actor get attached to a step?
  - **citation-validity rate** — fraction of shipped steps whose citations all
    resolve to a real tenant chunk AND pass the faithfulness check. This is the
    blocking metric and the "100% of shipped steps carry valid citations" half
    of the done-when.

Step matching reuses the faithfulness lexical coverage: a golden phrase is
"found" when an extracted step action covers enough of its salient tokens.
"""

from __future__ import annotations

from typing import Any

from cortex.knowledge import coverage, is_faithful

_MATCH_THRESHOLD = 0.6


def _matched(phrase: str, actions: list[str]) -> bool:
    return any(coverage(phrase, [a]) >= _MATCH_THRESHOLD for a in actions)


def _best_process(processes: list[dict[str, Any]], name_contains: str) -> dict[str, Any] | None:
    needle = name_contains.lower()
    return next((p for p in processes if needle in str(p.get("name", "")).lower()), None)


def step_precision_recall(
    processes: list[dict[str, Any]], golden: list[dict[str, Any]]
) -> tuple[float, float]:
    """Micro-averaged step precision/recall over golden-matched processes."""
    g_total = g_hit = e_total = e_hit = 0
    for g in golden:
        proc = _best_process(processes, g["name_contains"])
        actions = [s["action"] for s in proc["steps"]] if proc else []
        for phrase in g["steps"]:
            g_total += 1
            if _matched(phrase, actions):
                g_hit += 1
        for action in actions:
            e_total += 1
            if any(_matched(phrase, [action]) for phrase in g["steps"]):
                e_hit += 1
    recall = g_hit / g_total if g_total else 0.0
    precision = e_hit / e_total if e_total else 0.0
    return precision, recall


def actor_resolution_accuracy(
    processes: list[dict[str, Any]], golden: list[dict[str, Any]]
) -> float:
    """Fraction of golden processes whose expected actor is attached to some step."""
    total = hit = 0
    for g in golden:
        if not g.get("actors"):
            continue
        total += 1
        proc = _best_process(processes, g["name_contains"])
        if proc is None:
            continue
        actors = {str(s.get("actor") or "").lower() for s in proc["steps"]}
        if any(a.lower() in actors for a in g["actors"]):
            hit += 1
    return hit / total if total else 1.0


def citation_validity(
    processes: list[dict[str, Any]],
    valid_chunk_ids: set[str],
    text_by_chunk: dict[str, str],
    *,
    threshold: float = 0.5,
) -> float:
    """Fraction of shipped steps whose citations resolve to a real chunk and hold up.

    A step is valid when it has at least one citation, every cited chunk exists
    in the tenant, and the cited text supports the step (faithfulness). A
    dangling or unfaithful citation makes the step invalid.
    """
    total = valid = 0
    for proc in processes:
        for step in proc["steps"]:
            total += 1
            cites = step.get("citations", [])
            ids = [c["chunk_id"] for c in cites]
            if not ids or not all(i in valid_chunk_ids for i in ids):
                continue
            if is_faithful(step["action"], [text_by_chunk[i] for i in ids], threshold=threshold):
                valid += 1
    return valid / total if total else 1.0
