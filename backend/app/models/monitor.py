"""
Sentinel AI — Uptime Monitor Model
Per-tenant URLs checked periodically from the SaaS side (external mode).
"""

import uuid
import enum
from sqlalchemy import (
    Column, String, DateTime, Integer, Boolean, JSON, Enum,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class MonitorStatus(str, enum.Enum):
    PENDING = "pending"  # never checked yet
    UP = "up"
    DOWN = "down"
    PAUSED = "paused"


class UptimeMonitor(Base):
    """
    A URL checked every ``interval_seconds`` by the uptime checker.

    Live check state (status, last_*, consecutive_failures) is kept on the same
    row — at the current scale (≤ MAX_MONITORS_PER_TENANT per tenant) a separate
    results table buys nothing. A failure only raises an alert once
    ``consecutive_failures`` reaches ``failure_threshold``, so a single network
    blip doesn't page anyone.
    """
    __tablename__ = "uptime_monitors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "url", name="uq_monitors_tenant_url"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), index=True, nullable=False)  # Clerk org_id
    name = Column(String(200), nullable=False)
    url = Column(String(2000), nullable=False)

    # Check configuration
    interval_seconds = Column(Integer, nullable=False, default=60)
    timeout_seconds = Column(Integer, nullable=False, default=10)
    expected_status_codes = Column(JSON, nullable=False, default=lambda: [200])
    keyword = Column(String(500), nullable=True)  # must appear in response body
    latency_threshold_ms = Column(Integer, nullable=True)
    ssl_check_enabled = Column(Boolean, nullable=False, default=True)
    ssl_warn_days = Column(Integer, nullable=False, default=14)
    failure_threshold = Column(Integer, nullable=False, default=2)
    is_active = Column(Boolean, nullable=False, default=True)

    # Live check state
    status = Column(
        Enum(MonitorStatus), nullable=False,
        default=MonitorStatus.PENDING, index=True,
    )
    last_checked_at = Column(DateTime, nullable=True, index=True)
    last_response_ms = Column(Integer, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(String(500), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    ssl_expires_at = Column(DateTime, nullable=True)
    ssl_last_checked_at = Column(DateTime, nullable=True)
    # De-spams SSL warnings: re-alert at most weekly while the cert is expiring.
    ssl_alerted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
