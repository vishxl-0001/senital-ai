"""
Sentinel AI — Tenant & API Key Models
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base

class ApiKey(Base):
    """API Keys for incoming webhooks and external integrations."""
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    key_hash = Column(String(500), nullable=False, unique=True, index=True)
    prefix = Column(String(20), nullable=False)  # For UI display, e.g. "sentinel_abc12..."
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    last_used_at = Column(DateTime, nullable=True)

