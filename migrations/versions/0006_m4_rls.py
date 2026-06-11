"""m4 row-level security + least-privilege app role

Defense-in-depth tenant isolation (docs/ARCHITECTURE.md §6). Every tenant table
gets RLS + FORCE with a fail-closed policy keyed to the `app.current_tenant`
GUC, and a non-superuser `cortex_app` role is created for the app to run as in
production (Postgres superusers bypass RLS, so the existing `cortex` connection
is unaffected and keeps the app-layer mandatory filter as the active guard).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table carrying tenant_id (docs/DATA_MODEL.md).
_TENANT_TABLES = [
    "sources",
    "artifacts",
    "chunks",
    "entities",
    "entity_mentions",
    "relations",
    "processes",
    "process_versions",
    "process_steps",
    "citations",
    "freshness",
]

_APP_ROLE = "cortex_app"


def upgrade() -> None:
    # Least-privilege role the app runs as in production (RLS applies to it).
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
            CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_ROLE}';
          END IF;
        END $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}"
    )

    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Fail-closed: an unset (or reset-to-empty) GUC yields NULL via NULLIF,
        # which matches no rows. A custom GUC resets to '' (not NULL) after its
        # first SET LOCAL, so the NULLIF guard is required, not cosmetic.
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (
                tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
              )
              WITH CHECK (
                tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
              )
            """
        )


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {_APP_ROLE}")
