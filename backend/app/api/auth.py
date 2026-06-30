"""
Sentinel AI — Authentication & API Keys
Handles webhook API key verification and dashboard key generation.
"""

from fastapi import APIRouter, Depends, HTTPException, Security, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
import hashlib
import secrets
import string

from app.db.database import get_db
from app.models.tenant import ApiKey

router = APIRouter()

# The header companies will send in their webhooks
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def hash_api_key(api_key: str) -> str:
    """Hash the API key for secure storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()

def generate_raw_api_key() -> str:
    """Generate a new secure API key."""
    alphabet = string.ascii_letters + string.digits
    secret_part = ''.join(secrets.choice(alphabet) for _ in range(32))
    return f"sentinel_{secret_part}"

async def get_tenant_from_api_key(
    api_key: str = Security(API_KEY_HEADER),
    db: AsyncSession = Depends(get_db)
) -> str:
    """Dependency to extract tenant_id from the provided API key."""
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    
    key_hash = hash_api_key(api_key)
    
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    db_api_key = result.scalar_one_or_none()
    
    if not db_api_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API Key")
        
    # Update last used
    db_api_key.last_used_at = func.now()
    await db.commit()
    
    return db_api_key.tenant_id


# --- Dashboard Routes for Managing API Keys ---

@router.post("/keys")
async def create_api_key(
    name: str,
    # In a real app, tenant_id comes from Clerk JWT. 
    # For now, we simulate it via a header or request body for integration.
    tenant_id: str, 
    db: AsyncSession = Depends(get_db)
):
    """Create a new API Key for a tenant (called by the dashboard)."""
    raw_key = generate_raw_api_key()
    key_hash = hash_api_key(raw_key)
    prefix = raw_key[:12] + "..."
    
    new_key = ApiKey(
        tenant_id=tenant_id,
        name=name,
        key_hash=key_hash,
        prefix=prefix
    )
    
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    
    return {
        "id": str(new_key.id),
        "name": new_key.name,
        "api_key": raw_key,  # ONLY RETURNED ONCE!
        "prefix": prefix,
        "tenant_id": tenant_id
    }

@router.get("/keys")
async def list_api_keys(
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """List API keys for a tenant."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(desc(ApiKey.created_at))
    )
    keys = result.scalars().all()
    
    return {
        "api_keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "prefix": k.prefix,
                "is_active": k.is_active,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ]
    }
