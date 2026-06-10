"""chunks full-text search: generated tsvector + GIN index (M1 BM25 path)

The sparse retriever (docs/RETRIEVAL_AND_ML.md §3) queries this column with
websearch_to_tsquery + ts_rank_cd. Blurb is included so contextual signal also
benefits exact-term recall.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chunks ADD COLUMN text_tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('english', coalesce(context_blurb, '') || ' ' || text)) STORED"
    )
    op.create_index("ix_chunks_text_tsv", "chunks", ["text_tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_chunks_text_tsv", table_name="chunks")
    op.drop_column("chunks", "text_tsv")
