"""Alembic environment. Async (asyncpg) engine, URL injected from POSTGRES_DSN.

`target_metadata` is None until ORM models land (M0); explicit migrations still
run. Autogenerate is enabled once the SQLAlchemy metadata is wired here.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the DSN from the environment (never hard-code secrets in alembic.ini).
config.set_main_option(
    "sqlalchemy.url",
    os.environ.get(
        "POSTGRES_DSN",
        "postgresql+asyncpg://cortex:cortex@localhost:5433/cortex",
    ),
)

# Project MetaData drives autogenerate (M0+).
from cortex.storage.models import Base  # noqa: E402

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
