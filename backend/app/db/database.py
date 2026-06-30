"""
Sentinel AI — Database Connection
Async SQLAlchemy engine and session management.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# ── Engine ──
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_size=20,
    max_overflow=10,
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


# ── Init DB (create tables + migrations) ──
async def init_db():
    """Create all tables on startup and run necessary migrations."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)

        # Migration: update rca_embedding dimension from 1536 → 384 if needed
        try:
            result = await conn.execute(text("""
                SELECT atttypmod FROM pg_attribute
                JOIN pg_class ON pg_class.oid = pg_attribute.attrelid
                WHERE pg_class.relname = 'incidents'
                AND pg_attribute.attname = 'rca_embedding'
                AND pg_attribute.atttypmod > 0;
            """))
            row = result.fetchone()
            if row and row[0] != 384:
                # Clear stale embeddings (wrong dimension) and alter column
                await conn.execute(text("UPDATE incidents SET rca_embedding = NULL WHERE rca_embedding IS NOT NULL;"))
                await conn.execute(text("ALTER TABLE incidents ALTER COLUMN rca_embedding TYPE vector(384);"))
        except Exception:
            pass  # Table might not exist yet on first run
            
        # Migration: Add tenant_id to tables if it doesn't exist
        for table in ["incidents", "incident_timeline", "policies", "runbooks"]:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(255);"))
                await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id);"))
            except Exception as e:
                pass


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
