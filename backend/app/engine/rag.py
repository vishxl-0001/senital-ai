"""
Sentinel AI — RAG Vector Search Engine
Generates embeddings using fastembed (local ONNX model) and performs semantic search via pgvector.

Uses BAAI/bge-small-en-v1.5 (384-dim) — runs locally, no external API needed.
"""

import asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional

from app.models.incident import Incident

log = structlog.get_logger()

# ── Lazy-loaded Embedding Model ──
_embedding_model = None


def _get_embedding_model():
    """Lazy-load the fastembed model (downloads on first use, cached after)."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from fastembed import TextEmbedding
            _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            log.info("✅ Embedding model loaded: BAAI/bge-small-en-v1.5 (384-dim)")
        except Exception as e:
            log.error("❌ Failed to load embedding model", error=str(e))
            return None
    return _embedding_model


async def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dim vector embedding using fastembed (local ONNX model).
    Runs in a thread executor to avoid blocking the async event loop.
    """
    if not text:
        return []

    try:
        model = _get_embedding_model()
        if model is None:
            return []

        # fastembed is synchronous — run in executor
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: list(model.embed([text]))
        )

        if embeddings:
            result = embeddings[0].tolist()
            log.debug("✅ Embedding generated", dimensions=len(result))
            return result
        return []

    except Exception as e:
        log.error("❌ Failed to generate embedding", error=str(e))
        return []


async def find_similar_incidents(db: Session, embedding: list[float], limit: int = 3, tenant_id: str = None) -> list[dict]:
    """Search pgvector for the most similar past incidents."""
    if not embedding:
        return []

    try:
        # Cosine distance (<=>) — order by most similar
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
