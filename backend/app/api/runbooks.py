"""
Sentinel AI — Runbooks API
Manage predefined fix procedures for known issues. Tenant-scoped.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.database import get_db
from app.models.incident import Runbook
from app.auth.clerk import get_current_tenant

router = APIRouter()


class RunbookStep(BaseModel):
    action: str
    description: Optional[str] = None


class RunbookCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_pattern: Optional[str] = None
    steps: list[dict]
    rollback_steps: Optional[list[dict]] = None
    success_criteria: Optional[dict] = None
    enabled: bool = True


class RunbookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_pattern: Optional[str] = None
    steps: Optional[list[dict]] = None
    rollback_steps: Optional[list[dict]] = None
    success_criteria: Optional[dict] = None
    enabled: Optional[bool] = None


def _serialize(rb: Runbook) -> dict:
    return {
        "id": str(rb.id),
        "name": rb.name,
        "description": rb.description,
        "trigger_pattern": rb.trigger_pattern,
        "steps": rb.steps or [],
        "rollback_steps": rb.rollback_steps,
        "success_criteria": rb.success_criteria,
        "times_used": rb.times_used,
        "success_rate": rb.success_rate,
        "avg_fix_time_seconds": rb.avg_fix_time_seconds,
        "enabled": rb.enabled,
        "created_at": rb.created_at.isoformat() if rb.created_at else None,
    }


@router.get("")
async def list_runbooks(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's tenant's runbooks."""
    result = await db.execute(
        select(Runbook)
        .where(Runbook.tenant_id == tenant_id)
        .order_by(Runbook.created_at)
    )
    return {"runbooks": [_serialize(rb) for rb in result.scalars().all()]}


@router.post("")
async def create_runbook(
    runbook: RunbookCreate,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a runbook for the caller's tenant."""
    rb = Runbook(
        tenant_id=tenant_id,
        name=runbook.name,
        description=runbook.description,
        trigger_pattern=runbook.trigger_pattern,
        steps=runbook.steps,
        rollback_steps=runbook.rollback_steps,
        success_criteria=runbook.success_criteria,
        enabled=runbook.enabled,
    )
    db.add(rb)
    await db.commit()
    await db.refresh(rb)
    return _serialize(rb)


@router.patch("/{runbook_id}")
async def update_runbook(
    runbook_id: UUID,
    patch: RunbookUpdate,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update a runbook (partial), scoped to the caller's tenant."""
    result = await db.execute(
        select(Runbook).where(
            Runbook.id == runbook_id,
            Runbook.tenant_id == tenant_id,
        )
    )
    rb = result.scalar_one_or_none()
    if not rb:
        raise HTTPException(status_code=404, detail="Runbook not found")

    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(rb, field, value)
    await db.commit()
    await db.refresh(rb)
    return _serialize(rb)


@router.delete("/{runbook_id}")
async def delete_runbook(
    runbook_id: UUID,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a runbook, scoped to the caller's tenant."""
    result = await db.execute(
        select(Runbook).where(
            Runbook.id == runbook_id,
            Runbook.tenant_id == tenant_id,
        )
    )
    rb = result.scalar_one_or_none()
    if not rb:
        raise HTTPException(status_code=404, detail="Runbook not found")

    await db.delete(rb)
    await db.commit()
    return {"status": "deleted", "id": str(runbook_id)}
