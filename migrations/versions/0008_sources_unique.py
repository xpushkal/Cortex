"""sources unique (tenant_id, kind) — race-safe get-or-create

The async backfill path enqueues one job per artifact, so concurrent workers can
first-ingest the same (tenant, kind) at once. Without a unique index they each
SELECT-miss and INSERT, creating duplicate sources (later reads then raise
MultipleResultsFound). This collapses any existing duplicates onto the oldest row
(repointing artifacts) and adds the unique constraint the upsert relies on.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Repoint artifacts off duplicate sources onto the surviving (oldest) one.
    op.execute(
        """
        WITH ranked AS (
            SELECT id, tenant_id, kind,
                   first_value(id) OVER (
                       PARTITION BY tenant_id, kind ORDER BY created_at, id
                   ) AS keep_id
            FROM sources
        )
        UPDATE artifacts a
        SET source_id = r.keep_id
        FROM ranked r
        WHERE a.source_id = r.id AND r.id <> r.keep_id
        """
    )
    # Delete the now-orphaned duplicate sources.
    op.execute(
        """
        DELETE FROM sources s
        USING (
            SELECT id,
                   first_value(id) OVER (
                       PARTITION BY tenant_id, kind ORDER BY created_at, id
                   ) AS keep_id
            FROM sources
        ) d
        WHERE s.id = d.id AND d.id <> d.keep_id
        """
    )
    op.create_unique_constraint("uq_source_identity", "sources", ["tenant_id", "kind"])


def downgrade() -> None:
    op.drop_constraint("uq_source_identity", "sources", type_="unique")
