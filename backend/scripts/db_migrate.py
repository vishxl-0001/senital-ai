"""
Apply database migrations on startup (idempotent, replica-safe entrypoint).

Logic:
  * Fresh DB (no alembic_version, no incidents)  -> upgrade head creates schema.
  * Pre-Alembic DB (tables exist, no alembic_version) -> stamp the baseline so
    Alembic adopts the existing schema, then upgrade head applies later revisions.
  * Already-migrated DB -> upgrade head is a no-op.

Run this as a deploy step (and from the backend container command). Do NOT run
it from multiple services concurrently — only the backend service invokes it.
"""

import asyncio
import os
import sys

# Ensure the backend root (containing the `app` package and alembic.ini) is
# importable and is the working dir, regardless of where this is invoked from.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_ROOT)
os.chdir(_BACKEND_ROOT)

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def _inspect_state():
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            def check(sync_conn):
                tables = set(inspect(sync_conn).get_table_names())
                return ("alembic_version" in tables, "incidents" in tables)
            return await conn.run_sync(check)
    finally:
        await engine.dispose()


def main():
    cfg = Config("alembic.ini")
    has_alembic_version, has_incidents = asyncio.run(_inspect_state())

    if not has_alembic_version and has_incidents:
        print("[migrate] pre-Alembic database detected — stamping 0001_baseline")
        command.stamp(cfg, "0001_baseline")

    print("[migrate] running alembic upgrade head")
    command.upgrade(cfg, "head")
    print("[migrate] done")


if __name__ == "__main__":
    main()
