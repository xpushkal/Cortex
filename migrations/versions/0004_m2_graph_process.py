"""m2 knowledge graph + process registry tables

Adds the graph (entities, entity_mentions, relations) and process registry
(processes, process_versions, process_steps, citations) from docs/DATA_MODEL.md
§3 and §5. All tenant-scoped; provenance FKs reference chunks.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("aliases", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "type", "name", name="uq_entity_identity"),
    )
    op.create_index("ix_entities_tenant", "entities", ["tenant_id"], unique=False)

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_mentions_tenant", "entity_mentions", ["tenant_id"], unique=False)

    op.create_table(
        "relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("predicate", sa.String(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["object_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_relations_tenant", "relations", ["tenant_id"], unique=False)

    op.create_table(
        "processes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_process_identity"),
    )
    op.create_index("ix_processes_tenant", "processes", ["tenant_id"], unique=False)

    op.create_table(
        "process_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("process_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["processes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("process_id", "version", name="uq_process_version"),
    )
    op.create_index("ix_process_versions_tenant", "process_versions", ["tenant_id"], unique=False)

    op.create_table(
        "process_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("process_version_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor_entity_id", sa.Uuid(), nullable=True),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["actor_entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["process_version_id"], ["process_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_steps_tenant", "process_steps", ["tenant_id"], unique=False)

    op.create_table(
        "citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(), nullable=False),
        sa.Column("process_step_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("quote", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["process_step_id"], ["process_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_citations_tenant", "citations", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_citations_tenant", table_name="citations")
    op.drop_table("citations")
    op.drop_index("ix_process_steps_tenant", table_name="process_steps")
    op.drop_table("process_steps")
    op.drop_index("ix_process_versions_tenant", table_name="process_versions")
    op.drop_table("process_versions")
    op.drop_index("ix_processes_tenant", table_name="processes")
    op.drop_table("processes")
    op.drop_index("ix_relations_tenant", table_name="relations")
    op.drop_table("relations")
    op.drop_index("ix_entity_mentions_tenant", table_name="entity_mentions")
    op.drop_table("entity_mentions")
    op.drop_index("ix_entities_tenant", table_name="entities")
    op.drop_table("entities")
