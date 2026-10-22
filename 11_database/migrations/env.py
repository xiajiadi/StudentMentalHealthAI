"""Async Alembic environment for the database module."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from alembic.util.exc import CommandError
from database_layer import models  # noqa: F401 - registers all tables on metadata
from database_layer.base import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    configured = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not configured:
        raise CommandError("DATABASE_URL must be set for Alembic operations")
    if not configured.startswith(("mysql+aiomysql://", "mysql+asyncmy://")):
        raise CommandError("Alembic requires an async MySQL DATABASE_URL")
    return configured


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table="database_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        version_table="database_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = _database_url()
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
