"""m3 freshness table

Per-object freshness state (fresh | stale | expired) with TTL, the source of
truth for the M3 freshness loop (docs/DATA_MODEL.md §2). Tenant-scoped.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "freshness",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "last_validated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "object_type", "object_id", name="uq_freshness_object"),
    )
    op.create_index("ix_freshness_tenant", "freshness", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_freshness_tenant", table_name="freshness")
    op.drop_table("freshness")
