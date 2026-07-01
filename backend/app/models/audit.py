"""
Sentinel AI — Audit log (Phase 5, item 16).

An append-only record of consequential actions: who (ai / human / system), for
which tenant, what action, the before/after state, when, and — for fixes — how
it was approved (slack / dashboard / auto-policy). Written from the executor
(per K8s mutation) and the worker (per fix approval+execution).
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)

    actor = Column(String(32), nullable=False)          # "ai" | "human" | "system"
    actor_id = Column(String(255), nullable=True)        # e.g. Slack user id, Clerk user id
    action = Column(String(100), nullable=False)         # e.g. "execute_fix", "k8s_restart_pod"

    target_type = Column(String(50), nullable=True)      # e.g. "incident"
    target_id = Column(String(255), index=True, nullable=True)

    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)

    approval_source = Column(String(32), nullable=True)  # "slack" | "dashboard" | "auto" | None

    created_at = Column(DateTime, default=func.now(), nullable=False)
