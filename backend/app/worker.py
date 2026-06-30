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
)


@celery_app.task(name="execute_fix_task")
def execute_fix_task(incident_id: str):
    """
    Celery task to execute a fix in the background.
    Since executor is async, we run it in an asyncio loop.
    """
    log.info(f"🚀 Celery started fix execution for incident {incident_id}")
    
    async def _run():
        from app.db.database import async_session
        from sqlalchemy import select
        from app.models.incident import Incident, IncidentStatus
        from app.engine.executor import execute_fix
        from app.integrations.slack_bot import send_incident_to_slack
        
        async with async_session() as db:
            result = await db.execute(
                select(Incident).where(Incident.id == incident_id)
            )
            incident = result.scalar_one_or_none()
            
            if not incident or incident.status != IncidentStatus.FIX_APPROVED:
                log.error(f"Cannot execute fix for {incident_id} - invalid state or not found.")
                return
            
            incident.status = IncidentStatus.FIX_EXECUTING
            incident.fix_started_at = datetime.utcnow()
            await db.commit()
            
            fix_result = await execute_fix(incident.fix_plan, incident_id=incident_id)
            incident.fix_result = fix_result
            
            if fix_result["status"] == "success":
                incident.status = IncidentStatus.RESOLVED
                incident.resolved_at = datetime.utcnow()
                if incident.detected_at:
                    incident.mttr_seconds = (incident.resolved_at - incident.detected_at).seconds
            else:
                incident.status = IncidentStatus.FAILED
            
            await db.commit()
            
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
