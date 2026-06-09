"""SQLAlchemy ORM models — M0 subset of docs/DATA_MODEL.md.

All tables carry `tenant_id` (tenant isolation is enforced at the query layer and,
in M4, by Postgres row-level security). M0 covers the ingestion metadata chain:
sources -> artifacts -> chunks. Graph/process tables land in M2.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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
    __table_args__ = (Index("ix_chunks_tenant", "tenant_id"),)

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

    artifact: Mapped[Artifact] = relationship(back_populates="chunks")
