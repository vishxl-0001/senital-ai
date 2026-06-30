"""
Sentinel AI — Health Check Routes
Comprehensive health checks for all system components.
"""

from fastapi import APIRouter
from datetime import datetime
from openai import AsyncOpenAI
from app.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "sentinel-ai",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/full")
async def full_health_check():
    """
    Comprehensive health check — tests ALL system components.
    Returns individual status for: database, redis, LLM, embeddings, celery.
    """
    checks = {}
    all_healthy = True

    # ── 1. Database (PostgreSQL) ──
    try:
        from app.db.database import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()

            # Check pgvector
            ext_result = await conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            ext_row = ext_result.fetchone()
            pgvector_version = ext_row[0] if ext_row else None

            # Count incidents
            count_result = await conn.execute(text("SELECT COUNT(*) FROM incidents"))
            incident_count = count_result.fetchone()[0]

        checks["database"] = {
            "status": "healthy",
            "pgvector_version": pgvector_version,
            "incident_count": incident_count,
        }
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # ── 2. Redis ──
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=3)
        pong = await r.ping()
        info = await r.info("server")
        await r.aclose()

        checks["redis"] = {
            "status": "healthy" if pong else "unhealthy",
            "redis_version": info.get("redis_version"),
        }
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # ── 3. LLM (Groq) ──
    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None,
        )
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            temperature=0,
            max_tokens=5,
        )
        llm_reply = response.choices[0].message.content.strip()
        checks["llm"] = {
            "status": "healthy",
            "model": settings.OPENAI_MODEL,
            "base_url": settings.OPENAI_BASE_URL,
            "response": llm_reply,
            "tokens_used": response.usage.total_tokens,
        }
    except Exception as e:
        checks["llm"] = {
            "status": "unhealthy",
            "model": settings.OPENAI_MODEL,
            "error": str(e),
        }
        all_healthy = False

    # ── 4. Embeddings (fastembed) ──
    try:
        from app.engine.rag import generate_embedding

        test_embedding = await generate_embedding("health check test")
        checks["embeddings"] = {
            "status": "healthy" if test_embedding else "unhealthy",
            "model": "BAAI/bge-small-en-v1.5",
            "dimensions": len(test_embedding) if test_embedding else 0,
            "engine": "fastembed (local ONNX)",
        }
        if not test_embedding:
            all_healthy = False
    except Exception as e:
        checks["embeddings"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # ── 5. Celery Worker ──
    try:
        from app.worker import celery_app

        inspector = celery_app.control.inspect(timeout=3)
        active_workers = inspector.ping()
        worker_count = len(active_workers) if active_workers else 0
        checks["celery"] = {
            "status": "healthy" if worker_count > 0 else "unhealthy",
            "active_workers": worker_count,
            "workers": list(active_workers.keys()) if active_workers else [],
        }
        if worker_count == 0:
            all_healthy = False
    except Exception as e:
        checks["celery"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # ── 6. Integrations Status ──
    checks["integrations"] = {
        "slack": {
            "status": "configured" if settings.SLACK_BOT_TOKEN else "not_configured",
        },
        "github": {
            "status": "configured" if settings.GITHUB_PAT else "not_configured",
            "org": settings.GITHUB_ORG,
        },
    }

    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": "sentinel-ai",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
    }


@router.get("/debug/test-llm")
async def test_llm():
    """Debug endpoint: test if the LLM (Groq/OpenAI) connection works."""
    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None,
        )
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Say hello in JSON: {\"greeting\": \"...\"}"}],
            temperature=0.1,
            max_tokens=50,
        )
        return {
            "status": "ok",
            "model": settings.OPENAI_MODEL,
            "base_url": settings.OPENAI_BASE_URL,
            "response": response.choices[0].message.content,
        }
    except Exception as e:
        return {
            "status": "error",
            "model": settings.OPENAI_MODEL,
            "base_url": settings.OPENAI_BASE_URL,
            "key_prefix": settings.OPENAI_API_KEY[:10] + "..." if settings.OPENAI_API_KEY else "MISSING",
            "error": str(e),
        }

@router.get("/debug/test-rca")
async def test_rca_agent():
    """Test the RCA agent directly to see why it's failing."""
    from app.agents.rca import generate_rca
    from app.api.alerts import GenericAlert
    import traceback

    alert = GenericAlert(source="test", title="Test Alert", severity="critical")
    investigation = {"symptoms": "Test symptoms", "findings": []}
    
    try:
        rca = await generate_rca(alert, investigation)
        return {"status": "ok", "rca": rca}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@router.get("/debug/test-embedding")
async def test_embedding():
    """Test if the embedding engine (fastembed) is working."""
    from app.engine.rag import generate_embedding
    import traceback

    try:
        text = "Pod CrashLoopBackOff in payment-service namespace production"
        embedding = await generate_embedding(text)
        return {
            "status": "ok" if embedding else "error",
            "model": "BAAI/bge-small-en-v1.5",
            "engine": "fastembed (local ONNX)",
            "dimensions": len(embedding),
            "sample_values": embedding[:5] if embedding else [],
            "input_text": text,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
