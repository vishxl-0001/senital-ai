"""
Sentinel AI — Database Models
Core data models for incidents, alerts, and remediation.
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, Float,
    JSON, Enum, ForeignKey, Boolean, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.db.database import Base


# ── Enums ──

class IncidentStatus(str, PyEnum):
    DETECTED = "detected"
    INVESTIGATING = "investigating"
    RCA_COMPLETE = "rca_complete"
    FIX_PROPOSED = "fix_proposed"
    FIX_APPROVED = "fix_approved"
    FIX_EXECUTING = "fix_executing"
    FIX_MONITORING = "fix_monitoring"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


class Severity(str, PyEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FixApproval(str, PyEnum):
    AUTO = "auto"
    MANUAL = "manual"
    TIMEOUT_AUTO = "timeout_auto"  # Auto-approve after timeout


# ── Models ──

class Incident(Base):
    """Core incident record — tracks the full lifecycle."""
    __tablename__ = "incidents"
    # incident_number is sequential PER TENANT (not global), so absolute numbers
    # don't leak platform-wide incident volume.
    __table_args__ = (
        UniqueConstraint("tenant_id", "incident_number", name="uq_incidents_tenant_number"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)  # Clerk Organization ID
    incident_number = Column(Integer, index=True, nullable=False)  # per-tenant; allocated in orchestrator
    title = Column(String(500), nullable=False)
    status = Column(Enum(IncidentStatus), default=IncidentStatus.DETECTED, index=True)
    severity = Column(Enum(Severity), default=Severity.MEDIUM, index=True)

    # Source
    source = Column(String(100))  # "prometheus", "datadog", "manual"
    source_alert_id = Column(String(255))  # Original alert ID from source
    source_payload = Column(JSON)  # Raw alert payload

    # Investigation
    investigation_summary = Column(Text)  # AI investigation findings
    logs_collected = Column(JSON)  # Key log snippets
    metrics_collected = Column(JSON)  # Relevant metric data
    deployment_context = Column(JSON)  # Recent deploys

    # RCA
    root_cause = Column(Text)  # Root cause description
    rca_evidence = Column(JSON)  # Evidence supporting the RCA
    rca_confidence = Column(Float)  # 0.0 to 1.0
    rca_embedding = Column(Vector(1536))  # RAG embedding for semantic search (OpenAI text-embedding-3-small)
    similar_incidents = Column(JSON)  # Past similar incidents

    # Remediation
    fix_plan = Column(JSON)  # Proposed fix steps
    fix_type = Column(String(100))  # "rollback", "restart", "scale", etc.
    fix_approval = Column(Enum(FixApproval))  # How it was approved
    fix_executed_at = Column(DateTime)
    fix_result = Column(JSON)  # Result of fix execution
    rollback_plan = Column(JSON)  # How to undo the fix

    # Impact
    affected_services = Column(JSON)  # List of affected services
    affected_users_estimate = Column(Integer)
    impact_description = Column(Text)

    # Timing
    detected_at = Column(DateTime, default=func.now())
    investigation_started_at = Column(DateTime)
    rca_completed_at = Column(DateTime)
    fix_started_at = Column(DateTime)
    resolved_at = Column(DateTime)
    mttr_seconds = Column(Integer)  # Mean Time To Resolution

    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    timeline = relationship("IncidentTimeline", back_populates="incident", order_by="IncidentTimeline.timestamp")


class IncidentTimeline(Base):
    """Timeline events for an incident — tracks every action taken."""
    __tablename__ = "incident_timeline"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=func.now())
    event_type = Column(String(50))  # "alert", "investigation", "rca", "fix", "rollback"
    title = Column(String(500))
    description = Column(Text)
    data = Column(JSON)  # Additional structured data
    actor = Column(String(100))  # "ai", "human:user@email.com", "system"

    # Relationship
    incident = relationship("Incident", back_populates="timeline")


class Policy(Base):
    """Auto-fix policies — defines what AI can do automatically."""
    __tablename__ = "policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    action_type = Column(String(100), nullable=False)  # "restart_pod", "rollback", "scale", etc.
    auto_approve = Column(Boolean, default=False)  # True = AI fixes without asking
    conditions = Column(JSON)  # When this policy applies
    constraints = Column(JSON)  # Limits (max replicas, cooldown, etc.)
    approval_timeout_minutes = Column(Integer, default=15)  # Auto-approve after timeout
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Runbook(Base):
    """Runbooks — predefined fix procedures for known issues."""
    __tablename__ = "runbooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    trigger_pattern = Column(String(500))  # Pattern that matches RCA to this runbook
    steps = Column(JSON, nullable=False)  # Ordered list of fix steps
    rollback_steps = Column(JSON)  # How to undo
    success_criteria = Column(JSON)  # How to verify fix worked
    times_used = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    avg_fix_time_seconds = Column(Integer)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
