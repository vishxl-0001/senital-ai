"""Alembic environment — async (asyncpg) engine, URL + metadata from the app.

We reuse the application's DATABASE_URL (asyncpg) and Base.metadata so
autogenerate and online migrations match the real models. There is no psycopg
in this project, so offline/sync paths are not used — migrations run online
against the async engine via connection.run_sync().
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import settings
from app.db.database import Base

# Import models so they register on Base.metadata for autogenerate.
import app.models.incident  # noqa: F401
import app.models.tenant    # noqa: F401
import app.models.monitor   # noqa: F401

config = context.config

# Inject the app's DB URL (asyncpg). Escape % so ConfigParser doesn't choke.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


# Offline mode is unsupported (no sync driver); always run online.
run_migrations_online()
