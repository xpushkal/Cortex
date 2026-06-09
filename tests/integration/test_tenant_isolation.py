"""Cross-tenant leakage test — non-negotiable (docs/ARCHITECTURE.md §6).

Seeds two tenants with distinct data and asserts tenant A can never retrieve
tenant B's document, while B can. This is a build-blocking guarantee.
"""

from __future__ import annotations

import uuid

import pytest

from cortex.retrieval import HashingEmbedder
from cortex.storage import get_qdrant, search

pytestmark = pytest.mark.integration


async def test_no_cross_tenant_results(
    isolated_tenants: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    tenant_a, tenant_b, marker = isolated_tenants
    client = get_qdrant()
    # Query for tenant B's unique marker...
    vector = HashingEmbedder().embed([marker])[0]

    # ...as tenant A: must see nothing of B's.
    hits_a = await search(client, tenant_id=tenant_a, vector=vector, k=20)
    assert all(marker not in h.text for h in hits_a)

    # ...as tenant B: must find it (proves the data exists and the filter is the gate).
    hits_b = await search(client, tenant_id=tenant_b, vector=vector, k=20)
    assert any(marker in h.text for h in hits_b)
