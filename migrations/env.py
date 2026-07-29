"""Alembic environment.

The database URL is resolved from the environment, never from alembic.ini.
The previous alembic.ini hardcoded development credentials, which meant a
production ``alembic upgrade head`` would quietly target localhost.

``MIGRATION_DATABASE_URL`` takes precedence over ``DATABASE_URL`` so DDL can go
to Supabase's direct :5432 endpoint while the app runs through the :6543
transaction pooler, which cannot execute DDL.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make packages/ and services/ importable (mirrors prepend_sys_path).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.shared_core.db import models  # noqa: E402,F401  (registers tables)
from packages.shared_core.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        # Fail loudly. Falling back to a default would run DDL against the
        # wrong database, which is far worse than refusing to start.
        raise RuntimeError(
            "Set MIGRATION_DATABASE_URL or DATABASE_URL before running Alembic."
        )
    # Alembic drives DDL synchronously; strip async drivers.
    return url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")


config.set_main_option("sqlalchemy.url", _database_url())

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Never let autogenerate propose dropping Alembic's own bookkeeping table.
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        # Batch mode lets SQLite emulate ALTER TABLE by table rebuild.
        render_as_batch=_database_url().startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
