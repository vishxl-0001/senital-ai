"""
Sentinel AI — Database Connection
Async SQLAlchemy engine and session management.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import structlog

from app.config import settings

log = structlog.get_logger()


import sys
from sqlalchemy.pool import NullPool

# ── Engine ──
is_celery = "celery" in sys.argv[0] or (len(sys.argv) > 1 and "celery" in sys.argv[1])

kwargs = {}
if is_celery:
    kwargs["poolclass"] = NullPool
else:
    kwargs["pool_size"] = 20
    kwargs["max_overflow"] = 10

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    **kwargs
)

# ── Session Factory ──
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base Model ──
class Base(DeclarativeBase):
    pass


# ── Schema management ──
# Schema is owned by Alembic migrations (backend/alembic). Run
# `alembic upgrade head` as a deploy step — NOT create_all / ad-hoc DDL on
# startup, which races across replicas and has no rollback history.
async def init_db():
    """
    No-op kept for backwards-compatible startup imports.

    Previously this ran Base.metadata.create_all plus ad-hoc
    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on every boot. That is unsafe
    with multiple replicas (concurrent DDL) and leaves no migration history.
    Apply schema with `alembic upgrade head` before/at deploy instead.
    """
    log.info(
        "init_db is a no-op — schema is managed by Alembic. "
        "Run 'alembic upgrade head' to apply migrations."
    )


# ── Dependency: Get DB Session ──
async def get_db():
    """FastAPI dependency to get a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
