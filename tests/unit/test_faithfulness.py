"""Faithfulness gate (M2; docs/RETRIEVAL_AND_ML.md §4.2)."""

from __future__ import annotations

from cortex.knowledge.faithfulness import coverage, is_faithful


def test_step_supported_by_citation_is_faithful() -> None:
    action = "Route the refund to the finance team for approval"
    cited = ["Any refund over $500 must be routed to the finance team for approval."]
    assert is_faithful(action, cited)
    assert coverage(action, cited) >= 0.8


def test_unsupported_step_is_unfaithful() -> None:
    action = "Escalate the incident to the security team via PagerDuty"
    cited = ["Refunds over $500 are routed to finance for approval."]
    assert not is_faithful(action, cited)


def test_empty_citation_is_unfaithful() -> None:
    # A citation to a chunk outside the cluster yields no text -> coverage 0.
    assert not is_faithful("Verify order eligibility", [])
    assert coverage("Verify order eligibility", []) == 0.0


def test_all_stopword_action_is_trivially_faithful() -> None:
    # No salient tokens to ground -> coverage 1.0 (not a faithfulness failure).
    assert coverage("it must then be", ["unrelated text"]) == 1.0
    assert is_faithful("it must then be", ["unrelated text"])
