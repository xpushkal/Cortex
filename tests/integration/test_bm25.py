"""BM25 (Postgres FTS) sparse retrieval — exact-token recall + tenant isolation (M1)."""

from __future__ import annotations

import uuid

import pytest

from cortex.storage import get_sessionmaker, search_bm25

pytestmark = pytest.mark.integration


async def test_bm25_finds_exact_error_code(seeded_tenant: uuid.UUID) -> None:
    """The hybrid path's reason to exist: rare tokens dense embeddings can miss."""
    async with get_sessionmaker()() as session:
        hits = await search_bm25(session, tenant_id=seeded_tenant, query="ERR-5022", k=5)
    assert hits, "exact error-code query returned nothing"
    assert "ERR-5022" in hits[0].text


async def test_bm25_ranks_relevant_doc_for_phrase_query(seeded_tenant: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        hits = await search_bm25(
            session, tenant_id=seeded_tenant, query="refund finance approval", k=5
        )
    assert hits
    assert any("refund" in h.text.lower() for h in hits[:3])


async def test_bm25_respects_source_kind_filter(seeded_tenant: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        hits = await search_bm25(
            session,
            tenant_id=seeded_tenant,
            query="refund finance approval",
            k=5,
            source_kinds=["does-not-exist"],
        )
    assert hits == []


async def test_bm25_is_tenant_isolated(
    isolated_tenants: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    tenant_a, tenant_b, marker = isolated_tenants
    async with get_sessionmaker()() as session:
        leak = await search_bm25(session, tenant_id=tenant_a, query=marker, k=10)
        own = await search_bm25(session, tenant_id=tenant_b, query=marker, k=10)
    assert leak == [], "tenant B's marker doc leaked into tenant A's BM25 results"
    assert own and marker in own[0].text
