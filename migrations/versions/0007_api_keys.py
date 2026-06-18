"""m4 api_keys: bearer credentials bound to a tenant

Control-plane table for per-tenant bearer auth (docs/API.md). Looked up by
`token_hash` before any tenant context is set, so it is deliberately NOT under
row-level security; it is granted to the least-privilege `cortex_app` role
(0006 only granted tables that existed then).

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE = "cortex_app"


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_api_keys_token_hash"),
    )
    op.create_index("ix_api_keys_tenant", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_token_hash", "api_keys", ["token_hash"])
    # Grant the app role (0006 granted only the tables that existed then).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON api_keys TO {_APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON api_keys FROM {_APP_ROLE}")
    op.drop_index("ix_api_keys_token_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant", table_name="api_keys")
    op.drop_table("api_keys")
