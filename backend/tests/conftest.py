"""
Shared pytest fixtures for the backend test-suite.

These tests exercise the REAL Clerk session-JWT verification path (Phase 1
trust boundary). We do NOT need live Clerk credentials: ``ClerkJWTVerifier``
accepts an injectable ``static_keys`` mapping, so the test mints its own RSA
keypair, signs tokens with it, and injects the public key — the verifier then
runs its genuine signature/issuer/expiry/``org_id`` checks against those tokens.

DB-backed routes run against a throwaway ``sentinel_test`` database created on
the already-running compose Postgres (``pgvector/pgvector:pg16``), so dev data
is never touched.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

# ── Test DB connection (override via env if your compose differs) ──
PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5432"))
PG_USER = os.environ.get("TEST_PG_USER", "postgres")
PG_PASS = os.environ.get("TEST_PG_PASSWORD", "sentinel_dev")
TEST_DB = os.environ.get("TEST_DB_NAME", "sentinel_test")
TEST_DATABASE_URL = (
    f"postgresql+asyncpg://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{TEST_DB}"
)

# Point the app's settings at the throwaway test DB and provide harmless
# placeholders, BEFORE any `app.*` module is imported. (`app.agents.*` build an
# AsyncOpenAI client at import time, which raises on an empty api_key.)
# Env vars take precedence over the .env file in pydantic-settings, so this is
# deterministic regardless of the working directory.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
# Disable rate limiting in the suite: the slowapi decorator becomes a passthrough,
# so endpoint coroutines can be called directly and repeated calls don't 429.
# Dedicated 429 behavior is covered by test_rate_limit.py with its own limiter.
os.environ["RATE_LIMIT_ENABLED"] = "false"

TEST_ISSUER = "https://test.clerk.local"
TEST_KID = "test-kid"


# ── Test database lifecycle ────────────────────────────────────────────────

async def _ensure_database() -> None:
    """Create the test DB + pgvector extension if they don't already exist."""
    sys_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database="postgres"
    )
    try:
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB
        )
        if not exists:
            await sys_conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await sys_conn.close()

    db_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database=TEST_DB
    )
    try:
        await db_conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await db_conn.close()


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    asyncio.run(_ensure_database())
    yield


@pytest_asyncio.fixture
async def db_engine():
    """Fresh engine per test; create the schema and start from a clean slate."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.database import Base
    import app.models.incident  # noqa: F401 — register models on Base.metadata
    import app.models.tenant    # noqa: F401

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        # drop_all + create_all so model/schema changes always take effect
        # (create_all alone won't ALTER an existing table from a prior run).
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def app_session_maker(db_engine, monkeypatch):
    """
    Point app.db.database.async_session at the per-test engine.

    Code under test (e.g. Slack handlers, Celery task bodies) opens its own
    ``async_session()`` against the module-level engine, which is bound to the
    event loop alive at import time. pytest-asyncio runs each test on a fresh
    loop, and asyncpg connections are loop-bound — so without this, the second
    DB-touching test reusing that engine hits "another operation is in progress".
    Rebinding to db_engine (created on the current test's loop) avoids that.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    import app.db.database as database

    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session", maker)
    return maker


@pytest_asyncio.fixture
async def app_session_nullpool(db_engine, monkeypatch):
    """
    Like app_session_maker, but backed by a NullPool engine.

    For code under test that runs its own event loop (Celery task bodies call
    asyncio.run internally). Such tasks must be driven via asyncio.to_thread so
    their loop is separate from the test's. A pooled engine would reuse a
    connection across those loops (asyncpg forbids that); NullPool opens and
    closes a fresh connection per session, so each loop gets its own.
    db_engine is requested first purely to (re)create the schema.
    """
    from sqlalchemy.pool import NullPool
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    import app.db.database as database

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session", maker)
    yield maker
    await engine.dispose()


# ── Auth: self-signed Clerk-style tokens + matching verifier ───────────────

@pytest.fixture(scope="session")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return {"private": private_pem, "public": public_pem, "kid": TEST_KID}


@pytest.fixture(scope="session")
def make_token(rsa_keypair):
    """Factory for signed tokens. Mirrors what Clerk would issue."""
    def _make(org_id=None, sub="user_test", expired=False, omit_org=False,
              issuer=TEST_ISSUER):
        now = datetime.now(timezone.utc)
        exp = now + (timedelta(minutes=-5) if expired else timedelta(hours=1))
        claims = {
            "iss": issuer,
            "sub": sub,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        if not omit_org and org_id is not None:
            claims["org_id"] = org_id
        return jwt.encode(
            claims, rsa_keypair["private"], algorithm="RS256",
            headers={"kid": rsa_keypair["kid"]},
        )
    return _make


@pytest_asyncio.fixture
async def client(db_session, rsa_keypair):
    """
    httpx AsyncClient bound to the real FastAPI app, with:
      • get_db overridden to the test session
      • get_verifier overridden to a verifier holding the test public key

    Lifespan (init_db) is intentionally NOT run — schema is managed by db_engine.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.db.database import get_db
    from app.auth.clerk import ClerkJWTVerifier, get_verifier

    async def _override_get_db():
        yield db_session

    verifier = ClerkJWTVerifier(
        issuer=TEST_ISSUER,
        jwks_url=None,
        static_keys={rsa_keypair["kid"]: rsa_keypair["public"]},
        verify_issuer=True,
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_verifier] = lambda: verifier
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
