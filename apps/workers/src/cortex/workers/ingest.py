"""M0 ingestion orchestrator: connector -> Postgres + Qdrant.

Pipeline per artifact (docs/INGESTION.md §2): normalize -> content_hash ->
(unchanged? skip) -> chunk -> embed -> persist chunks (Postgres) + upsert vectors
(Qdrant). Idempotent: re-ingesting an artifact whose content_hash is unchanged is a
no-op. M0 runs this as one synchronous backfill; the arq per-artifact job + delta
polling land in M3.

CLI: `python -m cortex.workers.ingest --source sample --tenant <uuid|name>`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.connectors import SampleConnector
from cortex.connectors.base import Connector, SourceConfig
from cortex.obs import get_tracer, init_tracing
from cortex.retrieval import chunk, get_embedder
from cortex.retrieval.embedding import Embedder
from cortex.storage import (
    Artifact,
    Chunk,
    ChunkVector,
    Source,
    delete_artifact_points,
    ensure_collection,
    get_qdrant,
    get_sessionmaker,
    resolve_tenant,
    upsert_chunks,
)

CONNECTORS: dict[str, type[Connector]] = {"sample": SampleConnector}
_tracer = get_tracer(__name__)


class IngestStats(BaseModel):
    artifacts: int = 0
    skipped: int = 0
    chunks: int = 0


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


async def _get_or_create_source(
    session: AsyncSession, *, tenant_id: uuid.UUID, kind: str
) -> Source:
    existing = (
        await session.execute(
            select(Source).where(Source.tenant_id == tenant_id, Source.kind == kind)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    source = Source(tenant_id=tenant_id, kind=kind)
    session.add(source)
    await session.flush()
    return source


async def ingest_source(
    connector: Connector,
    *,
    tenant_id: uuid.UUID,
    dsn: str | None = None,
    qdrant_url: str | None = None,
    embedder: Embedder | None = None,
) -> IngestStats:
    """Backfill a connector into Postgres + Qdrant for one tenant. Idempotent."""
    span = _tracer.start_span(f"ingest.{connector.kind}")
    span.set_attribute("cortex.tenant_id", str(tenant_id))
    embedder = embedder or get_embedder()
    qclient = get_qdrant(qdrant_url)
    await ensure_collection(qclient, dim=embedder.dim)

    stats = IngestStats()
    vectors: list[ChunkVector] = []
    sessionmaker = get_sessionmaker(dsn)

    async with sessionmaker() as session:
        source = await _get_or_create_source(session, tenant_id=tenant_id, kind=connector.kind)
        cfg = SourceConfig(kind=connector.kind)

        for raw in connector.backfill(cfg):
            art = connector.normalize(raw)
            content_hash = _hash(art.content)

            existing = (
                await session.execute(
                    select(Artifact).where(
                        Artifact.tenant_id == tenant_id,
                        Artifact.source_id == source.id,
                        Artifact.external_id == art.external_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None and existing.content_hash == content_hash:
                stats.skipped += 1
                continue

            if existing is not None:
                # Content changed: drop stale chunks (Postgres cascade + Qdrant points).
                await delete_artifact_points(qclient, tenant_id=tenant_id, artifact_id=existing.id)
                await session.delete(existing)
                await session.flush()

            artifact = Artifact(
                tenant_id=tenant_id,
                source_id=source.id,
                external_id=art.external_id,
                content_hash=content_hash,
                kind=art.kind,
                content=art.content,
            )
            session.add(artifact)
            await session.flush()
            stats.artifacts += 1

            texts = chunk(art.content, source_kind=art.source_kind, artifact_kind=art.kind)
            embeddings = embedder.embed(texts)
            created_at = int(art.created_at.timestamp())
            for ordinal, (text, vector) in enumerate(zip(texts, embeddings, strict=True)):
                row = Chunk(
                    tenant_id=tenant_id,
                    artifact_id=artifact.id,
                    ordinal=ordinal,
                    text=text,
                    token_count=len(text.split()),
                    content_hash=_hash(text),
                )
                session.add(row)
                await session.flush()
                vectors.append(
                    ChunkVector(
                        vector_id=row.vector_id,
                        vector=vector,
                        tenant_id=tenant_id,
                        source_kind=art.source_kind,
                        artifact_id=artifact.id,
                        chunk_id=row.id,
                        kind=art.kind,
                        created_at=created_at,
                        content_hash=row.content_hash,
                        text=text,
                    )
                )
                stats.chunks += 1

        await session.commit()

    await upsert_chunks(qclient, vectors)
    span.set_attribute("cortex.artifacts", stats.artifacts)
    span.set_attribute("cortex.chunks", stats.chunks)
    span.set_attribute("cortex.skipped", stats.skipped)
    span.end()
    return stats


async def _amain(source: str, tenant: str) -> None:
    if source not in CONNECTORS:
        raise SystemExit(f"unknown source {source!r}; known: {sorted(CONNECTORS)}")
    init_tracing("cortex-workers")
    tenant_id = resolve_tenant(tenant)
    stats = await ingest_source(CONNECTORS[source](), tenant_id=tenant_id)
    print(f"ingested tenant={tenant} ({tenant_id}): {stats.model_dump()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a source into Cortex (M0).")
    parser.add_argument("--source", default="sample")
    parser.add_argument("--tenant", required=True, help="tenant UUID or name")
    args = parser.parse_args()
    asyncio.run(_amain(args.source, args.tenant))


if __name__ == "__main__":
    main()
