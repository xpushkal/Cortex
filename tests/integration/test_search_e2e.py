"""M0 done-when: ingest the sample corpus and /search returns relevant chunks for
the seed queries (docs/ROADMAP.md M0). Dense-only, tenant-filtered.
"""

from __future__ import annotations

import uuid

import pytest

from cortex.eval.metrics import recall_at_k
from cortex.retrieval import HashingEmbedder
from cortex.storage import get_qdrant, search

pytestmark = pytest.mark.integration

# (query, substring that must appear in the relevant chunk's text)
SEED_QUERIES: list[tuple[str, str]] = [
    ("how do we approve a refund over 500 dollars", "Refund policy"),
    ("sev1 incident on-call escalation pagerduty", "On-call runbook"),
    ("pricing exception discount approval from VP of sales", "Pricing exceptions"),
    ("request PTO time off vacation manager approval", "Time off"),
    ("expense reimbursement receipts expensify approval", "Expense reimbursement"),
    ("customer onboarding kickoff welcome checklist", "Customer onboarding"),
    ("report a security vulnerability disclosure", "Security:"),
    ("gdpr data deletion request delete records backups", "Data deletion"),
    ("production deploy feature flag rollout to main", "Production deploys"),
    ("vendor procurement approval finance contract", "Vendor procurement"),
]


async def test_search_returns_relevant_chunk_per_seed_query(seeded_tenant: uuid.UUID) -> None:
    embedder = HashingEmbedder()
    client = get_qdrant()
    found_at_1 = 0
    for query, expected in SEED_QUERIES:
        vector = embedder.embed([query])[0]
        hits = await search(client, tenant_id=seeded_tenant, vector=vector, k=5)
        texts = [h.text for h in hits]
        assert any(expected in t for t in texts), f"{expected!r} not in top-5 for {query!r}"
        if expected in hits[0].text:
            found_at_1 += 1
    # Dense-only with a lexical embedder should put most targets at rank 1.
    assert found_at_1 / len(SEED_QUERIES) >= 0.8


async def test_recall_at_5_meets_bar(seeded_tenant: uuid.UUID) -> None:
    embedder = HashingEmbedder()
    client = get_qdrant()
    recalls: list[float] = []
    for query, expected in SEED_QUERIES:
        vector = embedder.embed([query])[0]
        hits = await search(client, tenant_id=seeded_tenant, vector=vector, k=5)
        relevant = {h.chunk_id for h in hits if expected in h.text}
        ranked = [h.chunk_id for h in hits]
        recalls.append(recall_at_k(ranked, relevant, k=5) if relevant else 0.0)
    assert sum(recalls) / len(recalls) >= 0.8
