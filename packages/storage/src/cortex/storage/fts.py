"""Sparse retrieval via Postgres full-text search (the M1 BM25 path).

Exact-term / rare-token recall (IDs, error codes, names) that dense embeddings
miss — see docs/RETRIEVAL_AND_ML.md §3. `ts_rank_cd` is not literal BM25
scoring, but downstream RRF fusion consumes *ranks*, not scores, so the
difference is immaterial; the function is the seam where a dedicated index
could slot in later.

Tenant isolation mirrors the Qdrant store: `tenant_id` is a required argument
and is always applied — no cross-tenant path exists.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.storage.qdrant import SearchHit

_SQL = """
SELECT c.id::text AS chunk_id,
       ts_rank_cd(c.text_tsv, q)::float AS score,
       c.text AS text,
       s.kind AS source_kind,
       a.id::text AS artifact_id,
       coalesce(extract(epoch FROM c.created_at), 0)::bigint AS created_at
FROM chunks c
JOIN artifacts a ON a.id = c.artifact_id
JOIN sources s ON s.id = a.source_id,
     websearch_to_tsquery('english', :query) AS q
WHERE c.tenant_id = :tenant_id
  AND c.text_tsv @@ q
  {kind_clause}
ORDER BY score DESC, chunk_id
LIMIT :k
"""


async def search_bm25(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    k: int = 10,
    source_kinds: list[str] | None = None,
) -> list[SearchHit]:
    """Full-text search, ALWAYS filtered to `tenant_id`. Ranked by ts_rank_cd."""
    kind_clause = "AND s.kind = ANY(:kinds)" if source_kinds else ""
    stmt = sa.text(_SQL.format(kind_clause=kind_clause))
    params: dict[str, object] = {"tenant_id": tenant_id, "query": query, "k": k}
    if source_kinds:
        stmt = stmt.bindparams(sa.bindparam("kinds", type_=sa.ARRAY(sa.String())))
        params["kinds"] = source_kinds
    rows = (await session.execute(stmt, params)).mappings()
    return [SearchHit(**row) for row in rows]
