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
            await send_incident_to_slack(incident_data, channel="#incidents")

    asyncio.run(_run())
