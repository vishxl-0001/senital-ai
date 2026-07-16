"""
Sentinel AI — Uptime Check Engine (external mode)

Pure check/alert-building logic for uptime monitors, kept free of Celery
imports so it can be unit-tested directly. The Celery tasks in app.worker
drive these functions.

Contract that recovery depends on: ``uptime_fingerprint(monitor)`` MUST equal
``generate_fingerprint(GenericAlert(**build_down_alert(monitor, ...)))`` —
that fingerprint is stored on the Incident as ``source_alert_id`` and is how
a recovered monitor finds its open incident to resolve.
"""

import ssl
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.dedup import generate_fingerprint

log = structlog.get_logger()

USER_AGENT = "SentinelAI-Uptime/1.0"


# ── HTTP check ──

async def perform_http_check(monitor) -> dict:
    """
    Run one HTTP check against the monitor's URL.

    Returns {"ok", "failure_reason", "response_ms", "status_code", "severity"}.
    """
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=monitor.timeout_seconds
        ) as client:
            resp = await client.get(monitor.url, headers={"User-Agent": USER_AGENT})
        elapsed_ms = int((time.monotonic() - start) * 1000)
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "failure_reason": f"connection error: {type(e).__name__}",
            "response_ms": None,
            "status_code": None,
            "severity": "critical",
        }

    expected = monitor.expected_status_codes or [200]
    if resp.status_code not in expected:
        return {
            "ok": False,
            "failure_reason": f"unexpected status {resp.status_code} (expected {expected})",
            "response_ms": elapsed_ms,
            "status_code": resp.status_code,
            "severity": "critical",
        }

    if monitor.keyword and monitor.keyword not in resp.text:
        # Wrong content on a 200 page = effectively down (WP white-screen, error pages).
        return {
            "ok": False,
            "failure_reason": f"keyword '{monitor.keyword}' not found in response body",
            "response_ms": elapsed_ms,
            "status_code": resp.status_code,
            "severity": "critical",
        }

    if monitor.latency_threshold_ms and elapsed_ms > monitor.latency_threshold_ms:
        return {
            "ok": False,
            "failure_reason": f"slow response: {elapsed_ms}ms > {monitor.latency_threshold_ms}ms threshold",
            "response_ms": elapsed_ms,
            "status_code": resp.status_code,
            "severity": "medium",
        }

    return {
        "ok": True,
        "failure_reason": None,
        "response_ms": elapsed_ms,
        "status_code": resp.status_code,
        "severity": "info",
    }


# ── SSL expiry check ──

def get_ssl_expiry(hostname: str, port: int = 443, timeout: float = 10.0) -> datetime | None:
    """
    Blocking TLS handshake returning the cert's notAfter as naive UTC datetime.
    Call via asyncio.to_thread from async code. Returns None on any failure
    (unreachable, no TLS, parse error) — an unreachable host is the HTTP
    check's problem, not the SSL check's.
    """
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls:
                cert = tls.getpeercert()
        not_after = cert.get("notAfter")
        if not not_after:
            return None
        return datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
    except Exception as e:
        log.warning("SSL expiry check failed", hostname=hostname, error=str(e))
        return None


# ── Alert builders ──

def _down_alert_identity(monitor) -> dict:
    """Fields that define the dedup fingerprint for a DOWN alert."""
    return {
        "source": "uptime",
        "title": f"Monitor down: {monitor.name}",
        "labels": {
            "alertname": "MonitorDown",
            # monitor id in `service` makes the fingerprint unique per monitor
            "service": str(monitor.id),
        },
    }


def uptime_fingerprint(monitor) -> str:
    """The dedup fingerprint a DOWN alert for this monitor produces."""

    class _Stub:
        pass

    identity = _down_alert_identity(monitor)
    stub = _Stub()
    stub.source = identity["source"]
    stub.title = identity["title"]
    stub.labels = identity["labels"]
    return generate_fingerprint(stub)


def build_down_alert(monitor, check_result: dict) -> dict:
    """GenericAlert-shaped dict for a monitor that crossed its failure threshold."""
    identity = _down_alert_identity(monitor)
    return {
        "source": identity["source"],
        "title": identity["title"],
        "tenant_id": monitor.tenant_id,
        "description": (
            f"Uptime monitor '{monitor.name}' ({monitor.url}) failed "
            f"{monitor.consecutive_failures} consecutive check(s). "
            f"Latest failure: {check_result.get('failure_reason')}"
        ),
        "severity": check_result.get("severity", "critical"),
        "labels": {
            **identity["labels"],
            "monitor_id": str(monitor.id),
            "url": monitor.url,
        },
        "raw_payload": {
            "monitor_id": str(monitor.id),
            "monitor_name": monitor.name,
            "url": monitor.url,
            "failure_reason": check_result.get("failure_reason"),
            "status_code": check_result.get("status_code"),
            "response_ms": check_result.get("response_ms"),
            "consecutive_failures": monitor.consecutive_failures,
            "failure_threshold": monitor.failure_threshold,
            "checked_at": datetime.utcnow().isoformat(),
        },
    }


def build_ssl_alert(monitor, days_remaining: int) -> dict:
    """GenericAlert-shaped dict for an expiring SSL certificate."""
    return {
        "source": "uptime",
        "title": f"SSL certificate expiring: {monitor.name}",
        "tenant_id": monitor.tenant_id,
        "description": (
            f"The SSL certificate for {monitor.url} expires in {days_remaining} day(s) "
            f"({monitor.ssl_expires_at.isoformat() if monitor.ssl_expires_at else 'unknown'}). "
            "Renew it before users see certificate errors."
        ),
        "severity": "high" if days_remaining < 3 else "medium",
        "labels": {
            "alertname": "SSLCertExpiring",
            "service": str(monitor.id),
            "monitor_id": str(monitor.id),
            "url": monitor.url,
        },
        "raw_payload": {
            "monitor_id": str(monitor.id),
            "url": monitor.url,
            "days_remaining": days_remaining,
            "expires_at": monitor.ssl_expires_at.isoformat() if monitor.ssl_expires_at else None,
        },
    }


# ── Recovery ──

async def resolve_uptime_incident(db: AsyncSession, monitor) -> bool:
    """
    A previously-down monitor is responding again: resolve its open incident,
    record a timeline event, and send a Slack recovery message.

    Resolving is deterministic — no AI pipeline needed. Edge case: if the down
    incident is still mid-investigation, the orchestrator's later status writes
    can overwrite RESOLVED (last-write-wins). Accepted for v1: the pipeline
    finishes in ~1 minute and dedup keeps a re-fire from creating duplicates.
    """
    from app.models.incident import Incident, IncidentStatus, IncidentTimeline
    from app.integrations.slack_bot import send_slack_notification

    open_statuses = [
        IncidentStatus.DETECTED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RCA_COMPLETE,
        IncidentStatus.FIX_PROPOSED,
        IncidentStatus.FIX_APPROVED,
        IncidentStatus.FIX_EXECUTING,
        IncidentStatus.FIX_MONITORING,
    ]

    fingerprint = uptime_fingerprint(monitor)
    result = await db.execute(
        select(Incident)
        .where(
            Incident.tenant_id == monitor.tenant_id,
            Incident.source_alert_id == fingerprint,
            Incident.status.in_(open_statuses),
        )
        .order_by(Incident.created_at.desc())
        .limit(1)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        return False

    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = datetime.utcnow()
    downtime_seconds = None
    if incident.detected_at:
        downtime_seconds = int((incident.resolved_at - incident.detected_at).total_seconds())
        incident.mttr_seconds = downtime_seconds

    db.add(
        IncidentTimeline(
            incident_id=incident.id,
            tenant_id=monitor.tenant_id,
            event_type="fix",
            title="Monitor recovered",
            description=f"{monitor.name} ({monitor.url}) is responding again",
            data={"response_ms": monitor.last_response_ms},
            actor="system",
        )
    )
    await db.commit()

    if downtime_seconds is not None:
        downtime_text = f" Downtime: {downtime_seconds // 60}m {downtime_seconds % 60}s."
    else:
        downtime_text = ""
    await send_slack_notification(
        channel=None,
        text=f"✅ *Recovered:* {monitor.name} ({monitor.url}) is back up.{downtime_text}",
        tenant_id=monitor.tenant_id,
    )
    log.info(
        "✅ Uptime monitor recovered — incident resolved",
        monitor_id=str(monitor.id),
        incident_id=str(incident.id),
    )
    return True
