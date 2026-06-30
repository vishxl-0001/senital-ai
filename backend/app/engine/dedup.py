"""
Sentinel AI — Alert Deduplication Engine
Prevents the same alert from creating multiple incidents.
Uses fingerprinting based on alert labels + time window.
"""

import hashlib
import json
import structlog
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident, IncidentStatus

log = structlog.get_logger()

# Time window: alerts with same fingerprint within this window are considered duplicates
DEDUP_WINDOW_MINUTES = 30


def generate_fingerprint(alert) -> str:
    """
    Generate a unique fingerprint for an alert.
    Same alert type + same service + same namespace = same fingerprint.
    """
    key_parts = {
        "source": alert.source,
        "title": alert.title,
        # Include relevant labels for grouping
        "alertname": alert.labels.get("alertname", ""),
        "namespace": alert.labels.get("namespace", ""),
        "service": alert.labels.get("service", ""),
        "pod": alert.labels.get("pod", ""),
    }
    # Remove empty values
    key_parts = {k: v for k, v in key_parts.items() if v}
    fingerprint_str = json.dumps(key_parts, sort_keys=True)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


async def is_duplicate(alert, db: AsyncSession) -> tuple[bool, Incident | None]:
    """
    Check if an alert is a duplicate of an existing open incident.

    Returns:
        (is_duplicate: bool, existing_incident: Incident | None)
    """
    fingerprint = generate_fingerprint(alert)
    cutoff_time = datetime.utcnow() - timedelta(minutes=DEDUP_WINDOW_MINUTES)

    # Look for an existing incident with the same fingerprint that's still open
    open_statuses = [
        IncidentStatus.DETECTED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RCA_COMPLETE,
        IncidentStatus.FIX_PROPOSED,
        IncidentStatus.FIX_APPROVED,
        IncidentStatus.FIX_EXECUTING,
        IncidentStatus.FIX_MONITORING,
    ]

    result = await db.execute(
        select(Incident)
        .where(
            Incident.source_alert_id == fingerprint,
            Incident.status.in_(open_statuses),
            Incident.created_at >= cutoff_time,
        )
        .order_by(Incident.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()

    if existing:
        log.info(
            "🔁 Duplicate alert detected — skipping",
            fingerprint=fingerprint,
            existing_incident_id=str(existing.id),
            existing_status=existing.status.value,
        )
        return True, existing

    return False, None
