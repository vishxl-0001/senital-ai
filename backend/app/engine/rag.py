"""
Sentinel AI — RAG Vector Search Engine
Generates embeddings via the OpenAI Embeddings API and performs semantic
search with pgvector.

We previously used a local ONNX model (fastembed / BAAI/bge-small-en-v1.5)
but that model required ~400 MB of RAM to load, which OOM-killed the Celery
worker on memory-constrained production containers (SIGKILL / WorkerLostError).

Using the OpenAI Embeddings API instead:
  • model  : text-embedding-3-small  (1536-dim, high quality)
  • cost   : ~$0.02 / 1M tokens — negligible for incident volume
  • memory : <1 MB of SDK overhead vs 400 MB for ONNX runtime

The DB column (pgvector) is wide enough; we store whatever dimension we
generate, so swapping the backend here is fully backward-compatible with
new incidents (old rows with 384-dim embeddings are simply not matched
against new 1536-dim rows, which is safe — they return no results).
"""

import structlog
from sqlalchemy import select
from typing import Optional

from app.config import settings
from app.models.incident import Incident

log = structlog.get_logger()


async def generate_embedding(text: str) -> list[float]:
    """
    Generate a 1536-dim vector embedding using the OpenAI Embeddings API.
    Falls back to an empty list on any error so the pipeline never crashes.
    """
    if not text or not settings.OPENAI_API_KEY:
        return []

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None,
        )
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        embedding = response.data[0].embedding
        log.debug("✅ Embedding generated via OpenAI API", dimensions=len(embedding))
        return embedding

    except Exception as e:
        log.error("❌ Failed to generate embedding via OpenAI API", error=str(e))
        return []


async def find_similar_incidents(db, embedding: list[float], limit: int = 3, tenant_id: str = None) -> list[dict]:
    """Search pgvector for the most similar past resolved incidents."""
    if not embedding:
        return []

    try:
        # Cosine distance (<=> ) — order by most similar
        query = select(Incident).filter(
            Incident.rca_embedding.is_not(None)
        )
        if tenant_id:
            query = query.filter(Incident.tenant_id == tenant_id)

        stmt = query.order_by(
            Incident.rca_embedding.cosine_distance(embedding)
        ).limit(limit)

        result = await db.execute(stmt)
        incidents = result.scalars().all()

        similar = []
        for inc in incidents:
            similar.append({
                "id": str(inc.id),
                "title": inc.title,
                "root_cause": inc.root_cause,
                "fix_type": inc.fix_type,
                "severity": inc.severity.value if inc.severity else None,
                "rca_confidence": inc.rca_confidence,
            })

        if similar:
            log.info("🔍 Found similar past incidents", count=len(similar))

        return similar
    except Exception as e:
        log.error("❌ Vector search failed (is pgvector installed?)", error=str(e))
        return []
