"""Migration 0006: RLS enabled + policies + least-privilege role exist (M4)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from cortex.storage import get_sessionmaker

pytestmark = pytest.mark.integration

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


async def test_rls_enabled_and_forced_on_all_tenant_tables() -> None:
    async with get_sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    sa.text(
                        "SELECT relname FROM pg_class "
                        "WHERE relrowsecurity AND relforcerowsecurity "
                        "AND relname = ANY(:tables)"
                    ),
                    {"tables": _TENANT_TABLES},
                )
            )
            .scalars()
            .all()
        )
    assert set(rows) == set(_TENANT_TABLES)


async def test_isolation_policy_present_on_every_tenant_table() -> None:
    async with get_sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    sa.text(
                        "SELECT tablename FROM pg_policies "
                        "WHERE policyname = 'tenant_isolation' AND tablename = ANY(:tables)"
                    ),
                    {"tables": _TENANT_TABLES},
                )
            )
            .scalars()
            .all()
        )
    assert set(rows) == set(_TENANT_TABLES)


async def test_app_role_exists_and_is_not_superuser() -> None:
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'cortex_app'")
            )
        ).one_or_none()
    assert row is not None, "cortex_app role missing"
    assert row.rolsuper is False
    assert row.rolbypassrls is False  # RLS is actually enforced for this role
