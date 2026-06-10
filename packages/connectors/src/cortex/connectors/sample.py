"""Deterministic sample connector — seeds a synthetic company-knowledge corpus.

This is the fixture the eval golden set and integration tests build on, so it must
be **stable**: same items, same external_ids, same content every run. It covers a
spread of recurring company processes (refunds, incidents, pricing, etc.) so seed
queries have clearly-relevant targets.

Ingest it with: `python -m cortex.workers.ingest --source sample --tenant demo`
(or `just seed`).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec

# (external_id, artifact_kind, content). Order and ids are stable by contract.
SAMPLE_CORPUS: list[tuple[str, str, str]] = [
    (
        "doc-refund-policy",
        "page",
        "Refund policy. Refunds up to $500 can be issued directly by a support "
        "agent. Any refund over $500 must be routed to the finance team for "
        "approval before it is processed. Finance reviews eligibility and the "
        "original payment method, then approves or denies within one business day.",
    ),
    (
        "msg-incident-escalation",
        "message",
        "On-call runbook: for a Sev1 incident, page the on-call engineer "
        "immediately via PagerDuty, open a #incident channel, and escalate to the "
        "engineering manager if not acknowledged within 15 minutes. The incident "
        "commander owns comms until resolution.",
    ),
    (
        "doc-pricing-exception",
        "page",
        "Pricing exceptions. Discounts above 20% require approval from the VP of "
        "Sales. Discounts above 40% additionally require the CFO to sign off. "
        "Record every exception in the deal desk spreadsheet with a justification.",
    ),
    (
        "doc-pto-policy",
        "page",
        "Time off. Employees request PTO in the HR portal at least two weeks in "
        "advance. The direct manager approves or declines. Unused PTO does not roll "
        "over past the end of the calendar year.",
    ),
    (
        "doc-expense-reimbursement",
        "doc",
        "Expense reimbursement. Submit receipts in Expensify within 30 days. "
        "Expenses under $75 are auto-approved; anything higher needs manager "
        "approval. Reimbursement is paid in the next payroll cycle.",
    ),
    (
        "doc-customer-onboarding",
        "page",
        "Customer onboarding. After contract signature, create the workspace, "
        "send the welcome email, schedule a kickoff call within 3 business days, "
        "and assign a customer success manager. Track each step in the onboarding "
        "checklist.",
    ),
    (
        "msg-security-disclosure",
        "message",
        "Security: report suspected vulnerabilities to security@cortex.example. Do "
        "not post details in public channels. The security team triages within 24 "
        "hours and coordinates disclosure with the reporter.",
    ),
    (
        "doc-data-deletion",
        "doc",
        "Data deletion requests (GDPR). When a customer requests deletion, verify "
        "identity, locate all records by tenant id, delete from primary stores and "
        "backups within 30 days, and send written confirmation once complete.",
    ),
    (
        "doc-deploy-process",
        "pr",
        "Production deploys. Merge to main triggers CI; a green build is required. "
        "Deploys go out behind a feature flag, are rolled to 10% of traffic first, "
        "and are promoted to 100% after metrics look healthy for 30 minutes.",
    ),
    (
        "doc-procurement",
        "page",
        "Vendor procurement. New vendors over $10k/year require a security review "
        "and approval from the head of finance. Contracts are stored in the legal "
        "drive and renew annually unless cancelled 60 days prior.",
    ),
    (
        "msg-account-lockout",
        "message",
        "Account lockout: after 5 failed logins an account is locked for 30 "
        "minutes. Support can trigger a password reset email but cannot unlock an "
        "account manually; the user must use the reset link.",
    ),
    (
        "doc-code-review",
        "pr",
        "Code review policy. Every change needs one approving review and a green "
        "CI run before merge to main. Use squash merge. Security-sensitive changes "
        "additionally require review from the security owner.",
    ),
    # M1 additions: shapes that exercise the source-aware chunkers (markdown
    # headings, message threads, emails with quoted history) and exact-token
    # lookups (error codes) for the BM25/hybrid path. Stable by contract.
    (
        "doc-support-handbook",
        "page",
        "# Support handbook\n"
        "How support handles money-related requests end to end.\n\n"
        "## Refund escalation\n"
        "Agents issue refunds up to $500 in the admin panel. Larger refunds go "
        "to finance with the order id and reason; finance replies within one "
        "business day and support communicates the outcome to the customer.\n\n"
        "## Chargeback disputes\n"
        "When a chargeback notice arrives, pull the order history and delivery "
        "confirmation, submit evidence through the payment provider dashboard "
        "within 7 days, and tag the account for review.\n\n"
        "## Account credits\n"
        "Goodwill credits up to $100 may be granted once per customer per "
        "quarter. Log every credit in the billing notes with a reason code.",
    ),
    (
        "msg-refund-thread",
        "message",
        "alice: customer in #billing is asking for a $750 refund on order 18233 — "
        "that's over my limit, what do I do?\n"
        "bob: anything over $500 has to go to finance for approval before it is "
        "processed, file it with the order id.\n"
        "alice: filed as FIN-2291. how long does finance usually take?\n"
        "bob: one business day per the refund policy — they verify eligibility "
        "and the original payment method.\n"
        "carol: once it's approved, support issues the refund from the admin "
        "panel and replies to the customer on the ticket.",
    ),
    (
        "email-vendor-renewal",
        "email",
        "Heads up: the Acme Analytics contract auto-renews on March 1. Per the "
        "procurement policy we must cancel at least 60 days prior, so the "
        "keep-or-cancel decision is due to the head of finance by year end. The "
        "signed contract is in the legal drive under vendors/acme.\n\n"
        "On Mon, Dec 1, 2025, erin wrote:\n"
        "> Does anyone know when the Acme vendor contract renews?\n"
        "> I could not find it in the legal drive.",
    ),
    (
        "doc-api-error-codes",
        "page",
        "API error codes. ERR-4031 means the X-Tenant header is missing or "
        "malformed; the request is rejected before retrieval. ERR-5022 indicates "
        "a vector store timeout — retry with backoff. ERR-1187 is returned when "
        "an ingestion job exceeds its per-source rate limit and will be retried "
        "automatically.",
    ),
]

# Stable timestamp so the corpus is fully deterministic.
_SEEDED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class SampleConnector:
    """Connector over the in-memory SAMPLE_CORPUS (implements the Connector protocol)."""

    kind = "sample"
    rate_limit = TokenBucketSpec(capacity=1000, refill_per_second=1000.0)

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        for external_id, kind, content in SAMPLE_CORPUS:
            yield RawItem(external_id=external_id, payload={"kind": kind, "content": content})

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        # The sample corpus is static: nothing new after backfill.
        return iter(()), cursor

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind=str(raw.payload["kind"]),
            content=str(raw.payload["content"]),
            created_at=_SEEDED_AT,
        )
