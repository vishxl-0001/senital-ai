"""
Sentinel AI — Alert Webhook Receiver
Receives alerts from Prometheus AlertManager, Datadog, etc.
This is the ENTRY POINT for all incidents.
"""

from fastapi import APIRouter, BackgroundTasks, Request, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import structlog

from app.agents.orchestrator import process_alert
from app.api.auth import get_tenant_from_api_key

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
async def receive_prometheus_alert(
    payload: AlertManagerPayload,
    background_tasks: BackgroundTasks,
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
        background_tasks.add_task(process_alert, normalized)

    return {
        "status": "accepted",
        "alerts_received": len(firing_alerts),
        "message": f"Processing {len(firing_alerts)} alert(s)",
    }


@router.post("/webhook/generic")
async def receive_generic_alert(
    alert: GenericAlert,
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(process_alert, alert)

    return {
        "status": "accepted",
        "message": f"Processing alert: {alert.title}",
    }


@router.post("/test")
async def send_test_alert(background_tasks: BackgroundTasks):
    """
    Send a test alert to verify the pipeline works end-to-end.
    Simulates a pod CrashLoopBackOff alert.
    """
    test_alert = GenericAlert(
        source="test",
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

    background_tasks.add_task(process_alert, test_alert)

    return {
        "status": "accepted",
        "message": "🧪 Test alert sent! Check Slack for the investigation results.",
    }
