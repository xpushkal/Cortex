"""SQLAlchemy ORM models — docs/DATA_MODEL.md.

All tables carry `tenant_id` (tenant isolation is enforced at the query layer and,
in M4, by Postgres row-level security). M0 covered the ingestion metadata chain
(sources -> artifacts -> chunks); M2 adds the knowledge graph (entities,
entity_mentions, relations) and process registry (processes -> process_versions
-> process_steps, with citations).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Computed,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    """A connected source system for a tenant (docs/DATA_MODEL.md §2)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str]  # slack | gmail | notion | github | linear | file | sample
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(default="connected")  # connected|syncing|error
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Artifact(Base):
    """A normalized unit pulled from a source; idempotency key is content_hash."""

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_id", "external_id", name="uq_artifact_identity"),
        Index("ix_artifacts_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    external_id: Mapped[str]
    content_hash: Mapped[str]  # sha256 of normalized content
    kind: Mapped[str]  # message | email | page | pr | issue | doc
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    source: Mapped[Source] = relationship(back_populates="artifacts")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """A source-aware chunk of an artifact; the unit embedded into Qdrant."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_tenant", "tenant_id"),
        # The BM25 GIN index (created in migration 0003); declared here so
        # autogenerate sees it and doesn't propose dropping it.
        Index("ix_chunks_text_tsv", "text_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    text: Mapped[str]
    context_blurb: Mapped[str | None] = mapped_column(default=None)
    token_count: Mapped[int] = mapped_column(default=0)
    vector_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)  # Qdrant point id
    content_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Generated in Postgres (migration 0003); GIN-indexed for the BM25 path.
    text_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(context_blurb, '') || ' ' || text)",
            persisted=True,
        ),
        nullable=True,
    )

    artifact: Mapped[Artifact] = relationship(back_populates="chunks")


# --- Knowledge graph (docs/DATA_MODEL.md §3) ---------------------------------


class Entity(Base):
    """A canonical entity in the tenant's knowledge graph."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "type", "name", name="uq_entity_identity"),
        Index("ix_entities_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    type: Mapped[str]  # person | team | system | policy | product | customer | ...
    name: Mapped[str]  # canonical name
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    mentions: Mapped[list[EntityMention]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntityMention(Base):
    """Provenance: an entity as observed in a specific chunk."""

    __tablename__ = "entity_mentions"
    __table_args__ = (Index("ix_entity_mentions_tenant", "tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    confidence: Mapped[float] = mapped_column(default=1.0)

    entity: Mapped[Entity] = relationship(back_populates="mentions")


class Relation(Base):
    """A subject->predicate->object edge with provenance and temporal validity."""

    __tablename__ = "relations"
    __table_args__ = (Index("ix_relations_tenant", "tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    predicate: Mapped[str]  # approves | owns | escalates_to | reports_to | ...
    object_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    confidence: Mapped[float] = mapped_column(default=1.0)
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# --- Process registry (docs/DATA_MODEL.md §5) --------------------------------


class Process(Base):
    """A recurring task: named, versioned, source-cited. The product's core unit."""

    __tablename__ = "processes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_process_identity"),
        Index("ix_processes_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    name: Mapped[str]
    trigger: Mapped[str]
    current_version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(default="draft")  # draft|active|stale|deprecated
    confidence: Mapped[float] = mapped_column(default=1.0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    versions: Mapped[list[ProcessVersion]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )


class ProcessVersion(Base):
    """An immutable version of a process; `body` is the canonical JSON served."""

    __tablename__ = "process_versions"
    __table_args__ = (
        UniqueConstraint("process_id", "version", name="uq_process_version"),
        Index("ix_process_versions_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    process_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processes.id", ondelete="CASCADE"))
    version: Mapped[int]
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)  # canonical process JSON
    created_by: Mapped[str] = mapped_column(default="extractor")  # extractor | reviewer
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    process: Mapped[Process] = relationship(back_populates="versions")
    steps: Mapped[list[ProcessStep]] = relationship(
        back_populates="process_version", cascade="all, delete-orphan"
    )


class ProcessStep(Base):
    """One imperative step in a process version (queryable projection of `body`)."""

    __tablename__ = "process_steps"
    __table_args__ = (Index("ix_process_steps_tenant", "tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    process_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("process_versions.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int]
    action: Mapped[str]
    actor_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    process_version: Mapped[ProcessVersion] = relationship(back_populates="steps")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="process_step", cascade="all, delete-orphan"
    )


class Citation(Base):
    """A pointer from a process step (or other owner) back to its source chunk."""

    __tablename__ = "citations"
    __table_args__ = (Index("ix_citations_tenant", "tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    owner_type: Mapped[str]  # process_step | answer | relation
    process_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("process_steps.id", ondelete="CASCADE"), nullable=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    quote: Mapped[str | None] = mapped_column(nullable=True)

    process_step: Mapped[ProcessStep | None] = relationship(back_populates="citations")
