"""Contradiction detection between process versions (M3)."""

from __future__ import annotations

from cortex.knowledge.contradiction import detect_contradiction


def _body(steps: list[dict]) -> dict:
    return {"trigger": "t", "steps": steps}


def test_changed_approver_is_a_contradiction() -> None:
    active = _body([{"action": "Route the refund for approval", "actor": "finance team"}])
    new = _body([{"action": "Route the refund for approval", "actor": "vp of sales"}])
    report = detect_contradiction(active, new)
    assert report.contradictory
    assert report.conflicts[0].field == "actor"
    assert report.conflicts[0].old == "finance team"
    assert report.conflicts[0].new == "vp of sales"


def test_changed_decision_threshold_is_a_contradiction() -> None:
    active = _body(
        [{"action": "Route to finance if amount over limit", "decision": {"if": "amount > 500"}}]
    )
    new = _body(
        [{"action": "Route to finance if amount over limit", "decision": {"if": "amount > 1000"}}]
    )
    report = detect_contradiction(active, new)
    assert report.contradictory
    assert report.conflicts[0].field == "decision"


def test_added_step_is_not_a_contradiction() -> None:
    active = _body([{"action": "Verify order eligibility", "actor": "support agent"}])
    new = _body(
        [
            {"action": "Verify order eligibility", "actor": "support agent"},
            {"action": "Send a confirmation email to the customer", "actor": "support agent"},
        ]
    )
    report = detect_contradiction(active, new)
    assert not report.contradictory
    assert report.summary == "no contradiction"


def test_identical_bodies_no_contradiction() -> None:
    body = _body(
        [{"action": "Verify order eligibility", "actor": "support agent", "decision": None}]
    )
    assert not detect_contradiction(body, body).contradictory
