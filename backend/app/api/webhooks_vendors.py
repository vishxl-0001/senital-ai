"""
Sentinel AI — Vendor Webhook Adapters
Accept native payloads from UptimeRobot, Sentry, Datadog and CloudWatch (SNS),
translate them to GenericAlert and dispatch into the normal pipeline.

Parsing is deliberately lenient (dicts + .get()) — vendor payload shapes drift
and a 422 here means a silently dropped alert on their side. Unknown/ignored
event types still return 200 so vendors don't retry forever.
"""

import json

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.alerts import GenericAlert
from app.api.auth import API_KEY_HEADER, resolve_tenant_from_raw_key
from app.db.database import get_db
from app.rate_limit import limiter, WEBHOOK_LIMIT
from app.worker import process_alert_task

log = structlog.get_logger()
router = APIRouter()


async def get_tenant_from_key_or_query(
    request: Request,
    api_key: str = Security(API_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    X-API-Key header preferred; ``?api_key=`` query fallback for vendors that
    can't set custom headers (e.g. UptimeRobot's free plan). Tradeoff: query
    strings can land in access logs — issue a dedicated key per vendor so it
    can be rotated independently.
    """
    raw_key = api_key or request.query_params.get("api_key")
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key (X-API-Key header or ?api_key= query param)",
        )
    return await resolve_tenant_from_raw_key(raw_key, db)


async def _lenient_json(request: Request) -> dict:
    """Parse the body as JSON regardless of Content-Type (SNS sends text/plain)."""
    body = await request.body()
    if not body:
        return {}
    try:
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _dispatch(tenant_id: str, source: str, title: str, description: str,
              severity: str, labels: dict, raw_payload: dict) -> None:
    alert = GenericAlert(
        source=source,
        title=title,
        tenant_id=tenant_id,
        description=description,
        severity=severity,
        labels=labels,
        raw_payload=raw_payload,
    )
    process_alert_task.delay(alert.model_dump())
    log.info("🚨 Vendor alert dispatched", source=source, title=title)


@router.post("/uptimerobot")
@limiter.limit(WEBHOOK_LIMIT)
async def receive_uptimerobot(
    request: Request,
    tenant_id: str = Depends(get_tenant_from_key_or_query),
):
    """
    UptimeRobot alert contact webhook. alertType: 1=down, 2=up, 3=SSL expiry.
    'Up' events are ignored — Sentinel's own recovery flow only tracks native
    monitors, so foreign recoveries are informational at best.
    """
    payload = await _lenient_json(request)
    # UptimeRobot can also send fields as query params
    get = lambda k, d="": payload.get(k) or request.query_params.get(k, d)  # noqa: E731

    alert_type = str(get("alertType", ""))
    name = get("monitorFriendlyName", "unknown monitor")
    url = get("monitorURL", "")
    details = get("alertDetails", "")

    if alert_type == "2":
        return {"status": "ignored", "reason": "recovery event"}

    if alert_type == "3":
        title = f"UptimeRobot: SSL certificate issue on {name}"
        severity = "medium"
        alertname = "UptimeRobotSSL"
    else:  # "1" or unknown → treat as down
        title = f"UptimeRobot: {name} is DOWN"
        severity = "critical"
        alertname = "UptimeRobotDown"

    _dispatch(
        tenant_id=tenant_id,
        source="uptimerobot",
        title=title,
        description=f"{url} — {details}" if details or url else "UptimeRobot alert",
        severity=severity,
        labels={"alertname": alertname, "service": url or name},
        raw_payload=payload or dict(request.query_params),
    )
    return {"status": "accepted"}


_SENTRY_SEVERITY = {"fatal": "critical", "error": "high", "warning": "medium"}


@router.post("/sentry")
@limiter.limit(WEBHOOK_LIMIT)
async def receive_sentry(
    request: Request,
    tenant_id: str = Depends(get_tenant_from_key_or_query),
):
    """Sentry issue-alert webhook (new integration platform shape or legacy)."""
    payload = await _lenient_json(request)

    issue = payload.get("data", {}).get("issue", {}) if isinstance(payload.get("data"), dict) else {}
    if not issue:
        # Legacy webhook shape: fields at the top level / under "event"
        issue = payload.get("event", payload)

    title = issue.get("title") or payload.get("message") or "Sentry issue"
    level = str(issue.get("level") or payload.get("level") or "error").lower()
    project = ""
    if isinstance(issue.get("project"), dict):
        project = issue["project"].get("slug", "")
    else:
        project = str(payload.get("project", "") or "")

    _dispatch(
        tenant_id=tenant_id,
        source="sentry",
        title=f"Sentry: {title}",
        description=issue.get("culprit") or payload.get("culprit") or payload.get("url") or "",
        severity=_SENTRY_SEVERITY.get(level, "low"),
        labels={"alertname": "SentryIssue", "service": project},
        raw_payload=payload,
    )
    return {"status": "accepted"}


_DATADOG_SEVERITY = {"error": "high", "warning": "medium", "info": "low"}


@router.post("/datadog")
@limiter.limit(WEBHOOK_LIMIT)
async def receive_datadog(
    request: Request,
    tenant_id: str = Depends(get_tenant_from_key_or_query),
):
    """Datadog webhook integration (default payload template)."""
    payload = await _lenient_json(request)

    alert_type = str(payload.get("alert_type", "error")).lower()
    if alert_type == "success":
        return {"status": "ignored", "reason": "recovery event"}

    title = payload.get("title") or payload.get("event_title") or "Datadog alert"

    _dispatch(
        tenant_id=tenant_id,
        source="datadog",
        title=f"Datadog: {title}",
        description=payload.get("body") or payload.get("event_msg") or "",
        severity=_DATADOG_SEVERITY.get(alert_type, "high"),
        labels={
            "alertname": "DatadogAlert",
            "service": str(payload.get("alert_id", "") or payload.get("id", "")),
        },
        raw_payload=payload,
    )
    return {"status": "accepted"}


@router.post("/cloudwatch")
@limiter.limit(WEBHOOK_LIMIT)
async def receive_cloudwatch(
    request: Request,
    tenant_id: str = Depends(get_tenant_from_key_or_query),
):
    """
    AWS CloudWatch alarm via SNS HTTPS subscription. Handles the SNS
    SubscriptionConfirmation handshake, then forwards ALARM-state notifications.
    """
    payload = await _lenient_json(request)
    sns_type = payload.get("Type", "")

    if sns_type == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL", "")
        if subscribe_url.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.get(subscribe_url)
                log.info("✅ Confirmed SNS subscription", topic=payload.get("TopicArn"))
                return {"status": "subscription confirmed"}
            except httpx.HTTPError as e:
                log.error("SNS subscription confirmation failed", error=str(e))
                raise HTTPException(status_code=502, detail="Could not confirm SNS subscription")
        raise HTTPException(status_code=400, detail="Invalid SubscribeURL")

    if sns_type and sns_type != "Notification":
        return {"status": "ignored", "reason": f"SNS type {sns_type}"}

    # SNS wraps the CloudWatch alarm JSON in the Message string; a direct
    # (non-SNS) post of the alarm dict is accepted too.
    message = payload.get("Message")
    if isinstance(message, str):
        try:
            alarm = json.loads(message)
        except json.JSONDecodeError:
            alarm = {"AlarmDescription": message}
    elif isinstance(message, dict):
        alarm = message
    else:
        alarm = payload

    state = alarm.get("NewStateValue", "ALARM")
    if state != "ALARM":
        return {"status": "ignored", "reason": f"state {state}"}

    alarm_name = alarm.get("AlarmName", "CloudWatch alarm")
    _dispatch(
        tenant_id=tenant_id,
        source="cloudwatch",
        title=f"CloudWatch: {alarm_name}",
        description=alarm.get("NewStateReason") or alarm.get("AlarmDescription") or "",
        severity="high",
        labels={"alertname": "CloudWatchAlarm", "service": alarm_name},
        raw_payload=payload,
    )
    return {"status": "accepted"}
