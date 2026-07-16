"""
Sentinel AI — Celery Worker
Async task processing for long-running AI investigations.
"""

from celery import Celery
import asyncio
from datetime import datetime
import structlog

from app.config import settings

log = structlog.get_logger()

celery_app = Celery(
    "sentinel_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 min max per task
    task_soft_time_limit=240,  # Soft limit at 4 min
    # Durability: if a worker dies mid-task the message is redelivered instead
    # of acked-on-receipt, so an investigation is never silently lost on restart.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Uptime checker (external mode): one dispatcher sweep every 30s finds due
# monitors and fans out one check_monitor_task per monitor. Requires a beat
# process (`celery -A app.worker.celery_app beat`) — see docker-compose.
celery_app.conf.beat_schedule = {
    "check-due-monitors": {
        "task": "check_due_monitors",
        "schedule": 30.0,
    },
}


@celery_app.task(
    name="process_alert_task",
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def process_alert_task(self, alert_data: dict):
    """
    Run the full investigation pipeline for one alert as a durable Celery task.

    Previously this ran via FastAPI BackgroundTasks in the web process: a restart
    mid-investigation killed it with no retry, and an alert burst spawned unbounded
    coroutines in one process. As a Celery task it survives restarts (acks_late)
    retries transient failures, and is bounded by worker concurrency.

    `alert_data` is the JSON-serialized GenericAlert (process_alert manages its
    own DB session internally, mirroring execute_fix_task).
    """
    log.info(f"🚀 Celery started investigation for alert: {alert_data.get('title')}")

    async def _run():
        from app.api.alerts import GenericAlert
        from app.agents.orchestrator import process_alert

        alert = GenericAlert(**alert_data)
        await process_alert(alert)

    asyncio.run(_run())


@celery_app.task(name="execute_fix_task")
def execute_fix_task(incident_id: str, approval_source: str = "unknown", approver_id: str = None):
    """
    Celery task to execute a fix in the background.
    Since executor is async, we run it in an asyncio loop.

    approval_source records HOW the fix was authorized ("slack" | "dashboard" |
    "auto") and approver_id who authorized it — both written to the audit log.
    """
    log.info(f"🚀 Celery started fix execution for incident {incident_id}")

    async def _run():
        from app.db.database import async_session
        from sqlalchemy import select
        from app.models.incident import Incident, IncidentStatus
        from app.engine.executor import execute_fix
        from app.engine.audit import record_audit
        from app.integrations.slack_bot import send_incident_to_slack

        async with async_session() as db:
            result = await db.execute(
                select(Incident).where(Incident.id == incident_id)
            )
            incident = result.scalar_one_or_none()

            if not incident or incident.status != IncidentStatus.FIX_APPROVED:
                log.error(f"Cannot execute fix for {incident_id} - invalid state or not found.")
                return

            tenant_id = incident.tenant_id
            status_before = incident.status.value

            # Audit the approved execution (human-authorized) before mutating infra.
            await record_audit(
                tenant_id=tenant_id,
                actor="human",
                actor_id=approver_id,
                action="execute_fix",
                target_type="incident",
                target_id=incident_id,
                before_state={"status": status_before, "fix_type": incident.fix_type},
                after_state=None,
                approval_source=approval_source,
            )

            incident.status = IncidentStatus.FIX_EXECUTING
            incident.fix_started_at = datetime.utcnow()
            await db.commit()

            fix_result = await execute_fix(incident.fix_plan, incident_id=incident_id, tenant_id=tenant_id)
            incident.fix_result = fix_result
            
            if fix_result["status"] == "success":
                incident.status = IncidentStatus.RESOLVED
                incident.resolved_at = datetime.utcnow()
                if incident.detected_at:
                    incident.mttr_seconds = (incident.resolved_at - incident.detected_at).seconds
            else:
                incident.status = IncidentStatus.FAILED

            await db.commit()

            # Audit the execution outcome (AI actor performed the remediation).
            await record_audit(
                tenant_id=tenant_id,
                actor="ai",
                action="fix_execution_result",
                target_type="incident",
                target_id=incident_id,
                before_state={"status": status_before},
                after_state={"status": incident.status.value,
                             "result": fix_result.get("status"),
                             "needs_rollback": fix_result.get("needs_rollback")},
                approval_source=approval_source,
            )

            incident_data = {
                "id": str(incident.id),
                "title": incident.title,
                "severity": incident.severity.value if incident.severity else "unknown",
                "rca": {"root_cause": incident.root_cause, "confidence": incident.rca_confidence},
                "fix_plan": incident.fix_plan,
            }
            
            log.info(f"✅ Fix execution completed. Result: {fix_result['status']}")
            await send_incident_to_slack(incident_data, tenant_id=tenant_id)

    asyncio.run(_run())


# ── Uptime checker tasks (external mode) ──

# Dispatcher skips monitors touched within this many seconds, so two
# overlapping beat sweeps can't double-check the same monitor.
DISPATCH_GUARD_SECONDS = 25


@celery_app.task(name="check_due_monitors")
def check_due_monitors():
    """
    Beat-driven sweep: find active monitors whose interval has elapsed and fan
    out one check_monitor_task per monitor. Due-filtering happens in Python —
    even thousands of monitors is a trivial scan, and it keeps the query
    portable.
    """
    from datetime import timedelta

    async def _run():
        from sqlalchemy import select
        from app.db.database import async_session
        from app.models.monitor import UptimeMonitor

        now = datetime.utcnow()
        guard = timedelta(seconds=DISPATCH_GUARD_SECONDS)
        async with async_session() as db:
            result = await db.execute(
                select(
                    UptimeMonitor.id,
                    UptimeMonitor.interval_seconds,
                    UptimeMonitor.last_checked_at,
                ).where(UptimeMonitor.is_active == True)  # noqa: E712
            )
            due = [
                str(monitor_id)
                for monitor_id, interval, last in result.all()
                if (last is None or now >= last + timedelta(seconds=interval))
                and (last is None or now - last >= guard)
            ]
        for monitor_id in due:
            check_monitor_task.delay(monitor_id)
        if due:
            log.info(f"⏱️ Dispatched {len(due)} uptime check(s)")

    asyncio.run(_run())


@celery_app.task(
    name="check_monitor_task",
    bind=True,
    acks_late=True,
    max_retries=0,  # a failed check simply runs again next interval
    time_limit=60,
    soft_time_limit=45,
)
def check_monitor_task(self, monitor_id: str):
    """
    Run one uptime check: HTTP (status/keyword/latency) plus a once-daily SSL
    expiry check. Alerts fire through the normal pipeline exactly once, when
    consecutive_failures reaches the monitor's failure_threshold; recovery
    resolves the open incident directly (no AI needed).
    """
    from datetime import timedelta

    async def _run():
        from sqlalchemy import select
        from urllib.parse import urlparse
        from app.db.database import async_session
        from app.models.monitor import UptimeMonitor, MonitorStatus
        from app.engine.uptime import (
            perform_http_check,
            get_ssl_expiry,
            build_down_alert,
            build_ssl_alert,
            resolve_uptime_incident,
        )

        async with async_session() as db:
            result = await db.execute(
                select(UptimeMonitor).where(UptimeMonitor.id == monitor_id)
            )
            monitor = result.scalar_one_or_none()
            if not monitor or not monitor.is_active:
                return

            # Claim the slot immediately so an overlapping sweep skips us.
            monitor.last_checked_at = datetime.utcnow()
            await db.commit()

            was_down = monitor.status == MonitorStatus.DOWN
            check = await perform_http_check(monitor)

            if check["ok"]:
                monitor.status = MonitorStatus.UP
                monitor.consecutive_failures = 0
                monitor.last_response_ms = check["response_ms"]
                monitor.last_status_code = check["status_code"]
                monitor.last_error = None
                await db.commit()
                if was_down:
                    await resolve_uptime_incident(db, monitor)
            else:
                monitor.consecutive_failures += 1
                monitor.last_error = check["failure_reason"]
                monitor.last_status_code = check.get("status_code")
                monitor.last_response_ms = check.get("response_ms")
                if monitor.consecutive_failures >= monitor.failure_threshold:
                    monitor.status = MonitorStatus.DOWN
                    fire = monitor.consecutive_failures == monitor.failure_threshold
                    await db.commit()
                    if fire:  # fire exactly once per outage
                        process_alert_task.delay(build_down_alert(monitor, check))
                else:
                    await db.commit()

            # SSL expiry: https only, at most once per day per monitor.
            if (
                monitor.ssl_check_enabled
                and monitor.url.startswith("https://")
                and (
                    monitor.ssl_last_checked_at is None
                    or datetime.utcnow() - monitor.ssl_last_checked_at > timedelta(days=1)
                )
            ):
                hostname = urlparse(monitor.url).hostname
                port = urlparse(monitor.url).port or 443
                expires = await asyncio.to_thread(get_ssl_expiry, hostname, port)
                monitor.ssl_last_checked_at = datetime.utcnow()
                if expires:
                    monitor.ssl_expires_at = expires
                    days_remaining = (expires - datetime.utcnow()).days
                    if days_remaining < monitor.ssl_warn_days and (
                        monitor.ssl_alerted_at is None
                        or datetime.utcnow() - monitor.ssl_alerted_at > timedelta(days=7)
                    ):
                        monitor.ssl_alerted_at = datetime.utcnow()
                        process_alert_task.delay(build_ssl_alert(monitor, days_remaining))
                await db.commit()

    asyncio.run(_run())
