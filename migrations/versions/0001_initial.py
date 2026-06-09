"""initial empty baseline

The real schema (sources, artifacts, chunks, freshness, entities, relations,
processes, citations — docs/DATA_MODEL.md) lands in M0/M2. This empty baseline
establishes the alembic version chain so `alembic upgrade head` is runnable from
day one and CI can exercise the migration path.

Revision ID: 0001
Revises:
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
