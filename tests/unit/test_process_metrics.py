"""Process-extraction metrics (M2; docs/RETRIEVAL_AND_ML.md §5.2)."""

from __future__ import annotations

from cortex.eval.process_metrics import (
    actor_resolution_accuracy,
    citation_validity,
    step_precision_recall,
)

PROCESSES = [
    {
        "name": "Refund policy. Refunds up to $500 ...",
        "steps": [
            {
                "action": "Refund over $500 routed to the finance team for approval",
                "actor": "finance team",
                "citations": [{"chunk_id": "c1"}],
            },
            {
                "action": "Finance reviews eligibility and approves",
                "actor": None,
                "citations": [{"chunk_id": "c1"}],
            },
        ],
    }
]
GOLDEN = [
    {
        "name_contains": "Refund policy",
        "steps": [
            "refund over $500 routed to the finance team for approval",
            "finance reviews eligibility",
        ],
        "actors": ["finance team"],
    }
]


def test_step_precision_recall_full_match() -> None:
    precision, recall = step_precision_recall(PROCESSES, GOLDEN)
    assert recall == 1.0  # both golden phrases covered
    assert precision == 1.0  # both extracted steps match a golden phrase


def test_recall_penalizes_missing_step() -> None:
    golden = [
        {
            "name_contains": "Refund policy",
            "steps": [*GOLDEN[0]["steps"], "issue a chargeback to the bank"],
        }
    ]
    _, recall = step_precision_recall(PROCESSES, golden)
    assert recall == 2 / 3  # the third golden step is not extracted


def test_actor_resolution_accuracy() -> None:
    assert actor_resolution_accuracy(PROCESSES, GOLDEN) == 1.0
    miss = [
        {"name_contains": "Refund policy", "steps": GOLDEN[0]["steps"], "actors": ["legal team"]}
    ]
    assert actor_resolution_accuracy(PROCESSES, miss) == 0.0


def test_citation_validity_all_valid() -> None:
    text_by_chunk = {
        "c1": (
            "Any refund over $500 is routed to the finance team for approval. "
            "Finance reviews eligibility and approves."
        )
    }
    assert citation_validity(PROCESSES, {"c1"}, text_by_chunk) == 1.0


def test_citation_validity_dangling_reference() -> None:
    processes = [
        {
            "name": "Bad",
            "steps": [
                {"action": "Route to finance for approval", "citations": [{"chunk_id": "c1"}]},
                {"action": "Wire funds offshore", "citations": [{"chunk_id": "ghost"}]},
            ],
        }
    ]
    text_by_chunk = {"c1": "Route the refund to finance for approval."}
    assert citation_validity(processes, {"c1"}, text_by_chunk) == 0.5


def test_citation_validity_unfaithful_step() -> None:
    processes = [
        {
            "name": "X",
            "steps": [
                {"action": "Delete all customer backups now", "citations": [{"chunk_id": "c1"}]}
            ],
        }
    ]
    text_by_chunk = {"c1": "Refunds over $500 go to finance for approval."}
    assert citation_validity(processes, {"c1"}, text_by_chunk) == 0.0
