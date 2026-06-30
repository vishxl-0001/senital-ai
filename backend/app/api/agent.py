"""
Sentinel AI — Agent API
Endpoints for the remote Sentinel Agent running in customer infrastructure.
Agents poll for fixes to execute, and report back results.
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.models.incident import Incident, IncidentStatus
from app.api.auth import get_tenant_from_api_key

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
        if inc.fix_plan and "steps" in inc.fix_plan:
            # We assume the agent just needs a shell command for now
            # In a real system, fix_plan would have a structured list of commands
            steps = inc.fix_plan["steps"]
            command = " && ".join([s["command"] for s in steps if "command" in s])
            
            if command:
                fixes.append({
                    "incident_id": str(inc.id),
                    "command": command
                })
                # Mark as executing so another agent doesn't pick it up
                inc.status = IncidentStatus.FIX_EXECUTING
                
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
