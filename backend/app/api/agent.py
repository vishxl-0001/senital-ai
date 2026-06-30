"""
Sentinel AI — Agent API
Endpoints for the remote Sentinel Agent running in customer infrastructure.
Agents poll for fixes to execute, and report back results.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.database import get_db
from app.models.incident import Incident, IncidentStatus
from app.api.auth import get_tenant_from_api_key
from app.engine.k8s_actions import build_structured_action

log = structlog.get_logger()
router = APIRouter()

class FixReport(BaseModel):
    incident_id: str
    status: str
    output: str

@router.get("/pending-fixes")
async def get_pending_fixes(
    tenant_id: str = Depends(get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Agent polls this to get approved fixes that need execution."""
    # Find incidents that are FIX_APPROVED (or FIX_EXECUTING but not finished)
    query = select(Incident).where(
        Incident.tenant_id == tenant_id,
        Incident.status == IncidentStatus.FIX_APPROVED
    )
    result = await db.execute(query)
    incidents = result.scalars().all()
    
    fixes = []
    for inc in incidents:
        # Hand the agent a structured, whitelisted action — never a free-form
        # shell string. If the fix can't be mapped to an allowed action type,
        # we refuse to dispatch it (leave it for a human) rather than guess.
        action = build_structured_action(inc.fix_plan or {})
        if action:
            fixes.append({
                "incident_id": str(inc.id),
                "action": action,
            })
            # Mark as executing so another agent doesn't pick it up
            inc.status = IncidentStatus.FIX_EXECUTING
        else:
            log.warning(
                "No whitelisted action could be built for incident — not dispatching",
                incident_id=str(inc.id),
                fix_type=(inc.fix_plan or {}).get("fix_type"),
            )

    await db.commit()

    return {"fixes": fixes}


@router.post("/report-fix")
async def report_fix_result(
    report: FixReport,
    tenant_id: str = Depends(get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Agent reports the result of a fix execution."""
    query = select(Incident).where(
        Incident.id == report.incident_id,
        Incident.tenant_id == tenant_id
    )
    result = await db.execute(query)
    incident = result.scalar_one_or_none()
    
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    # Update incident with result
    incident.fix_result = {
        "status": report.status,
        "output": report.output
    }
    
    if report.status == "success":
        incident.status = IncidentStatus.RESOLVED
    else:
        incident.status = IncidentStatus.FAILED
        
    await db.commit()
    
    return {"status": "accepted"}
