"""
Sentinel AI — Alert Webhook Receiver
Receives alerts from Prometheus AlertManager, Datadog, etc.
This is the ENTRY POINT for all incidents.
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import structlog

from app.worker import process_alert_task
from app.api.auth import get_tenant_from_api_key
from app.auth.clerk import get_current_tenant
from app.rate_limit import limiter, WEBHOOK_LIMIT

log = structlog.get_logger()
router = APIRouter()


# ── Pydantic Schemas ──

class PrometheusAlert(BaseModel):
    """Schema for Prometheus AlertManager webhook payload."""
    status: str  # "firing" or "resolved"
    labels: dict
    annotations: dict
    startsAt: str
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None


class AlertManagerPayload(BaseModel):
    """Full AlertManager webhook payload."""
    version: str = "4"
    groupKey: Optional[str] = None
    status: str  # "firing" or "resolved"
    receiver: Optional[str] = None
    alerts: list[PrometheusAlert]


class GenericAlert(BaseModel):
    """Generic alert format — normalized from any source."""
    source: str  # "prometheus", "datadog", "manual", etc.
    title: str
    tenant_id: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = "medium"
    labels: Optional[dict] = {}
    raw_payload: Optional[dict] = {}


# ── Routes ──

@router.post("/webhook/prometheus")
@limiter.limit(WEBHOOK_LIMIT)
async def receive_prometheus_alert(
    request: Request,
    payload: AlertManagerPayload,
    tenant_id: str = Depends(get_tenant_from_api_key),
):
    """
    Receive alerts from Prometheus AlertManager.
    This is the main entry point — triggers the full investigation pipeline.
    """
    firing_alerts = [a for a in payload.alerts if a.status == "firing"]

    if not firing_alerts:
        return {"status": "ok", "message": "No firing alerts, skipping"}

    log.info(
        "🚨 Alert received from Prometheus",
        count=len(firing_alerts),
        group_key=payload.groupKey,
    )

    # Process each firing alert in the background
    for alert in firing_alerts:
        normalized = GenericAlert(
            source="prometheus",
            title=alert.annotations.get("summary", alert.labels.get("alertname", "Unknown Alert")),
            tenant_id=tenant_id,
            description=alert.annotations.get("description", ""),
            severity=alert.labels.get("severity", "medium"),
            labels=alert.labels,
            raw_payload=alert.model_dump(),
        )
        # Durable dispatch to Celery (survives restarts, bounded concurrency).
        process_alert_task.delay(normalized.model_dump())

    return {
        "status": "accepted",
        "alerts_received": len(firing_alerts),
        "message": f"Processing {len(firing_alerts)} alert(s)",
    }


@router.post("/webhook/generic")
@limiter.limit(WEBHOOK_LIMIT)
async def receive_generic_alert(
    request: Request,
    alert: GenericAlert,
    tenant_id: str = Depends(get_tenant_from_api_key),
):
    """
    Receive alerts from any source in a normalized format.
    Use this for custom integrations.
    """
    log.info(
        "🚨 Generic alert received",
        source=alert.source,
        title=alert.title,
        severity=alert.severity,
    )

    alert.tenant_id = tenant_id
    process_alert_task.delay(alert.model_dump())

    return {
        "status": "accepted",
        "message": f"Processing alert: {alert.title}",
    }


@router.post("/test")
@limiter.limit(WEBHOOK_LIMIT)
async def send_test_alert(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Send a test alert to verify the pipeline works end-to-end.
    Simulates a pod CrashLoopBackOff alert.

    Authenticated via the dashboard Clerk session — the resulting incident is
    attributed to the caller's tenant (previously this was unauthenticated and
    triggered the full investigation+remediation pipeline anonymously).
    """
    test_alert = GenericAlert(
        source="test",
        tenant_id=tenant_id,
        title="Pod CrashLoopBackOff: payment-service",
        description="Pod payment-service-7d4f8b6c5-x9k2l is in CrashLoopBackOff state. Container has restarted 5 times in the last 10 minutes.",
        severity="critical",
        labels={
            "alertname": "KubePodCrashLooping",
            "namespace": "production",
            "pod": "payment-service-7d4f8b6c5-x9k2l",
            "container": "payment-service",
            "service": "payment-service",
        },
        raw_payload={
            "test": True,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    process_alert_task.delay(test_alert.model_dump())

    return {
        "status": "accepted",
        "message": "🧪 Test alert sent! Check Slack for the investigation results.",
    }
