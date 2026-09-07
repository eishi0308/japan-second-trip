"""Alembic environment.

Runs against whatever ``DATABASE_URL`` points at, so the same migration chain
covers PostgreSQL (production) and SQLite (tests, offline demo). Custom column
types are rendered by import path so autogenerate keeps ``Vector``/``JSONBCompat``
rather than collapsing them to the SQLite representation.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from jst_api.core.config import get_settings
from jst_api.db import models  # noqa: F401  (registers all tables)
from jst_api.db import types as jst_types
from jst_api.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    if type_ == "type" and isinstance(obj, jst_types.Vector):
        autogen_context.imports.add("import jst_api.db.types")
        return f"jst_api.db.types.Vector({obj.dim})"
    if type_ == "type" and isinstance(obj, jst_types.JSONBCompat):
        autogen_context.imports.add("import jst_api.db.types")
        return "jst_api.db.types.JSONBCompat()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
