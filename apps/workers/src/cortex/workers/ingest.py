"""M0 ingestion orchestrator: connector -> Postgres + Qdrant.

Pipeline per artifact (docs/INGESTION.md §2): normalize -> content_hash ->
(unchanged? skip) -> chunk -> embed -> persist chunks (Postgres) + upsert vectors
(Qdrant). Idempotent: re-ingesting an artifact whose content_hash is unchanged is a
no-op. Backfill runs this synchronously (the CLI below); the change-driven path runs
it per artifact via the arq worker (`cortex.workers.pipeline.run_pipeline`). Delta
polling and priority lanes land later.

CLI: `python -m cortex.workers.ingest --source sample --tenant <uuid|name>`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.connectors import GitHubConnector, SampleConnector
from cortex.connectors.base import (
    Artifact as RawArtifact,
)
from cortex.connectors.base import (
    Connector,
    Cursor,
    RawItem,
    SourceConfig,
    TokenBucketSpec,
)
from cortex.knowledge import (
    ChunkRef,
    Extractor,
    get_extractor,
    mark_processes_stale_for_artifact,
)
from cortex.obs import get_tracer, init_tracing
from cortex.retrieval import chunk, get_blurb_generator, get_embedder
from cortex.retrieval.blurb import ArtifactContext, artifact_head
from cortex.retrieval.embedding import Embedder
from cortex.storage import (
    Artifact,
    Chunk,
    ChunkVector,
    Source,
    acquire,
    build_limiter,
    delete_artifact_points,
    ensure_collection,
    get_qdrant,
    get_sessionmaker,
    resolve_tenant,
    upsert_chunks,
)
from cortex.workers.enrich import enrich_artifact

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
    # Race-safe: concurrent backfill jobs for the same (tenant, kind) would
    # otherwise SELECT-miss and both INSERT, creating duplicate sources. The
    # unique index (migration 0008) + ON CONFLICT DO NOTHING collapses that to one.
    await session.execute(
        pg_insert(Source)
        .values(tenant_id=tenant_id, kind=kind)
        .on_conflict_do_nothing(index_elements=["tenant_id", "kind"])
    )
    await session.flush()
    return (
        await session.execute(
            select(Source).where(Source.tenant_id == tenant_id, Source.kind == kind)
        )
    ).scalar_one()


async def ingest_source(
    connector: Connector,
    *,
    tenant_id: uuid.UUID,
    dsn: str | None = None,
    qdrant_url: str | None = None,
    embedder: Embedder | None = None,
    extractor: Extractor | None = None,
) -> IngestStats:
    """Backfill a connector into Postgres + Qdrant for one tenant. Idempotent.

    Per artifact: chunk -> blurb -> embed -> persist chunks/vectors, then extract
    the knowledge graph + process objects (M2) within the same transaction.
    """
    span = _tracer.start_span(f"ingest.{connector.kind}")
    span.set_attribute("cortex.tenant_id", str(tenant_id))
    embedder = embedder or get_embedder()
    blurber = get_blurb_generator()
    extractor = extractor or get_extractor()
    qclient = get_qdrant(qdrant_url)
    await ensure_collection(qclient, dim=embedder.dim)

    # Egress: a per-source token bucket so a connector never exceeds the source's
    # API quota (docs/INGESTION.md §4). Redis-backed across workers when REDIS_URL
    # is set, else process-local; sized to the connector's documented rate limit.
    egress = build_limiter(
        connector.rate_limit.capacity,
        connector.rate_limit.refill_per_second,
        redis_url=os.environ.get("REDIS_URL"),
        namespace="egress",
    )

    stats = IngestStats()
    vectors: list[ChunkVector] = []
    sessionmaker = get_sessionmaker(dsn)

    async with sessionmaker() as session:
        source = await _get_or_create_source(session, tenant_id=tenant_id, kind=connector.kind)
        cfg = SourceConfig(kind=connector.kind)

        for raw in connector.backfill(cfg):
            # Wait for an egress token before touching the source's next item.
            await acquire(egress, connector.kind)
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
                # Content changed (M3): mark processes that cite this artifact stale
                # BEFORE dropping its chunks (citations cascade with the chunks).
                await mark_processes_stale_for_artifact(
                    session,
                    tenant_id=tenant_id,
                    artifact_id=existing.id,
                    reason=f"source artifact {art.external_id} changed",
                )
                # Drop stale chunks (Postgres cascade + Qdrant points).
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
            ctx = ArtifactContext(
                source_kind=art.source_kind,
                artifact_kind=art.kind,
                external_id=art.external_id,
                head=artifact_head(art.content),
            )
            blurbs = blurber.generate(ctx, texts)
            # Contextual retrieval: embed blurb + text; serve/store the raw text.
            embeddings = embedder.embed(
                [
                    f"{blurb}\n\n{text}" if blurb else text
                    for text, blurb in zip(texts, blurbs, strict=True)
                ]
            )
            created_at = int(art.created_at.timestamp())
            chunk_refs: list[ChunkRef] = []
            for ordinal, (text, blurb, vector) in enumerate(
                zip(texts, blurbs, embeddings, strict=True)
            ):
                row = Chunk(
                    tenant_id=tenant_id,
                    artifact_id=artifact.id,
                    ordinal=ordinal,
                    text=text,
                    context_blurb=blurb or None,
                    token_count=len(text.split()),
                    content_hash=_hash(text),
                )
                session.add(row)
                await session.flush()
                chunk_refs.append(ChunkRef(chunk_id=str(row.id), text=text))
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

            # M2: extract the graph + cited process objects for this artifact.
            head = artifact_head(art.content)
            await enrich_artifact(
                session,
                tenant_id=tenant_id,
                name=head,
                trigger=f"Relevant when handling: {head}",
                chunks=chunk_refs,
                extractor=extractor,
            )

        await session.commit()

    await upsert_chunks(qclient, vectors)
    span.set_attribute("cortex.artifacts", stats.artifacts)
    span.set_attribute("cortex.chunks", stats.chunks)
    span.set_attribute("cortex.skipped", stats.skipped)
    span.end()
    return stats


class _EventConnector:
    """A one-artifact connector built from an incremental-sync event (M3)."""

    rate_limit = TokenBucketSpec(capacity=100, refill_per_second=100.0)

    def __init__(self, *, source_kind: str, external_id: str, kind: str, content: str) -> None:
        self.kind = source_kind
        self._external_id = external_id
        self._artifact_kind = kind
        self._content = content

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        yield RawItem(
            external_id=self._external_id,
            payload={"kind": self._artifact_kind, "content": self._content},
        )

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        return iter(()), cursor

    def normalize(self, raw: RawItem) -> RawArtifact:
        return RawArtifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind=str(raw.payload["kind"]),
            content=str(raw.payload["content"]),
            created_at=datetime.now(tz=UTC),
        )


async def ingest_event(
    *,
    tenant_id: uuid.UUID,
    source_kind: str,
    external_id: str,
    kind: str,
    content: str,
    dsn: str | None = None,
    qdrant_url: str | None = None,
) -> IngestStats:
    """Incremental-sync entry point: ingest one changed artifact (the webhook path).

    Idempotent and change-driven — unchanged content is a no-op; changed content
    re-runs the per-artifact pipeline and marks dependent processes stale.
    """
    connector = _EventConnector(
        source_kind=source_kind, external_id=external_id, kind=kind, content=content
    )
    return await ingest_source(connector, tenant_id=tenant_id, dsn=dsn, qdrant_url=qdrant_url)


def _load_dotenv(path: str = ".env") -> None:
    """Load .env into os.environ (existing vars win) so GITHUB_TOKEN etc. resolve."""
    env = Path(path)
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _build_connector(
    source: str,
    *,
    repo: str | None,
    max_files: int | None = None,
    max_items: int | None = None,
) -> Connector:
    if source == "sample":
        return SampleConnector()
    if source == "github":
        if not repo:
            raise SystemExit("github needs --repo owner/name")
        caps: dict[str, Any] = {
            k: v for k, v in (("max_files", max_files), ("max_items", max_items)) if v is not None
        }
        return GitHubConnector(repo=repo, **caps)
    raise SystemExit(f"unknown source {source!r}; known: sample, github")


async def _amain(
    source: str,
    tenant: str,
    *,
    repo: str | None,
    max_files: int | None,
    max_items: int | None,
    enqueue: bool,
) -> None:
    init_tracing("cortex-workers")
    tenant_id = resolve_tenant(tenant)
    connector = _build_connector(source, repo=repo, max_files=max_files, max_items=max_items)
    if enqueue:
        # Async backfill: fan out per-artifact jobs onto the backfill lane for the
        # worker to drain. Requires Redis + a worker on CORTEX_WORKER_QUEUE=cortex:backfill.
        from cortex.workers.queue import enqueue_backfill

        n = await enqueue_backfill(connector, tenant_id=tenant_id)
        print(f"enqueued {n} backfill job(s) tenant={tenant} ({tenant_id}) -> cortex:backfill")
        return
    stats = await ingest_source(connector, tenant_id=tenant_id)
    print(f"ingested tenant={tenant} ({tenant_id}): {stats.model_dump()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a source into Cortex.")
    parser.add_argument("--source", default="sample", help="sample | github")
    parser.add_argument("--tenant", required=True, help="tenant UUID or name")
    parser.add_argument("--repo", help="owner/name (required for --source github)")
    parser.add_argument("--max-files", type=int, help="cap markdown files (github)")
    parser.add_argument("--max-items", type=int, help="cap issues+PRs (github)")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="enqueue per-artifact jobs onto the backfill lane instead of ingesting inline",
    )
    args = parser.parse_args()
    _load_dotenv()
    asyncio.run(
        _amain(
            args.source,
            args.tenant,
            repo=args.repo,
            max_files=args.max_files,
            max_items=args.max_items,
            enqueue=args.enqueue,
        )
    )


if __name__ == "__main__":
    main()
