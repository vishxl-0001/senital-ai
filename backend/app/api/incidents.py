"""
Sentinel AI — Incidents API
CRUD operations for incidents + status tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional
from uuid import UUID

from app.db.database import get_db
from app.models.incident import Incident, IncidentStatus

router = APIRouter()

@router.get("")
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    """List all incidents with optional filtering."""
    query = select(Incident).order_by(desc(Incident.created_at))

    if tenant_id:
        query = query.where(Incident.tenant_id == tenant_id)

    if status:
        query = query.where(Incident.status == status)
    if severity:
        query = query.where(Incident.severity == severity)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    incidents = result.scalars().all()

    return {
        "incidents": [
            {
                "id": str(inc.id),
                "incident_number": inc.incident_number,
                "title": inc.title,
                "status": inc.status.value if inc.status else None,
                "severity": inc.severity.value if inc.severity else None,
                "source": inc.source,
                "root_cause": inc.root_cause,
                "rca_confidence": inc.rca_confidence,
                "fix_type": inc.fix_type,
                "mttr_seconds": inc.mttr_seconds,
                "detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
                "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
                "created_at": inc.created_at.isoformat() if inc.created_at else None,
            }
            for inc in incidents
        ],
        "total": len(incidents),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{incident_id}")
async def get_incident(
    incident_id: UUID,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    """Get full incident details including timeline."""
    query = select(Incident).where(Incident.id == incident_id)
    if tenant_id:
        query = query.where(Incident.tenant_id == tenant_id)
        
    result = await db.execute(query)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return {
        "id": str(incident.id),
        "incident_number": incident.incident_number,
        "title": incident.title,
        "status": incident.status.value if incident.status else None,
        "severity": incident.severity.value if incident.severity else None,
        "source": incident.source,
        "investigation_summary": incident.investigation_summary,
        "root_cause": incident.root_cause,
        "rca_evidence": incident.rca_evidence,
        "rca_confidence": incident.rca_confidence,
        "fix_plan": incident.fix_plan,
        "fix_type": incident.fix_type,
        "fix_result": incident.fix_result,
        "fix_approval": incident.fix_approval.value if incident.fix_approval else None,
        "rollback_plan": incident.rollback_plan,
        "affected_services": incident.affected_services,
        "impact_description": incident.impact_description,
        "similar_incidents": incident.similar_incidents,
        "logs_collected": incident.logs_collected,
        "metrics_collected": incident.metrics_collected,
        "deployment_context": incident.deployment_context,
        "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
        "investigation_started_at": incident.investigation_started_at.isoformat() if incident.investigation_started_at else None,
        "rca_completed_at": incident.rca_completed_at.isoformat() if incident.rca_completed_at else None,
        "fix_started_at": incident.fix_started_at.isoformat() if incident.fix_started_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "mttr_seconds": incident.mttr_seconds,
    }


@router.post("/{incident_id}/approve-fix")
async def approve_fix(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Manually approve a proposed fix (human-in-the-loop)."""
    result = await db.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.status != IncidentStatus.FIX_PROPOSED:
        raise HTTPException(
            status_code=400,
            detail=f"Incident is in '{incident.status.value}' state, not 'fix_proposed'",
        )

    incident.status = IncidentStatus.FIX_APPROVED
    incident.fix_approval = "manual"
    await db.commit()

    # Trigger fix execution via Celery task
    from app.worker import execute_fix_task
    execute_fix_task.delay(str(incident.id))

    return {
        "status": "approved",
        "message": f"Fix approved for incident {incident_id}. Executing...",
    }
