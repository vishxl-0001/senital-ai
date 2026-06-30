"""
Sentinel AI — Tenant & API Key Models
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Tenant(Base):
    """
    A customer organization (1:1 with a Clerk Organization).

    ``id`` IS the Clerk ``org_id`` (the same value used as ``tenant_id`` across
    incidents/policies/api_keys), so settings can be looked up directly by the
    verified org_id without a join table.

    ``slack_approver_ids`` is the allow-list of Slack user IDs permitted to
    approve fixes from Slack. Authorization fails CLOSED: if this is empty/unset,
    Slack approvals are rejected (approve via the authenticated dashboard
    instead). Slack routing fields are populated in Phase 4 (per-tenant OAuth).
    """
    __tablename__ = "tenants"

    id = Column(String(255), primary_key=True)  # Clerk org_id == tenant_id
    name = Column(String(255), nullable=True)

    # Slack approval authorization (Phase 2, item 9)
    slack_approver_ids = Column(JSON, nullable=True)  # list[str] of Slack user IDs

    # Per-tenant Slack routing — populated in Phase 4 (item 13)
    slack_team_id = Column(String(64), nullable=True, index=True)
    slack_channel_id = Column(String(64), nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


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

