"""
Sentinel AI — Policies API
Manage auto-fix policies (what AI can do automatically).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.database import get_db
from app.models.incident import Policy
from app.auth.clerk import get_current_tenant

router = APIRouter()


class PolicyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    action_type: str  # "restart_pod", "rollback_deployment", "scale_horizontal", etc.
    auto_approve: bool = False
    conditions: Optional[dict] = {}
    constraints: Optional[dict] = {}
    approval_timeout_minutes: int = 15


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    action_type: Optional[str] = None
    auto_approve: Optional[bool] = None
    conditions: Optional[dict] = None
    constraints: Optional[dict] = None
    approval_timeout_minutes: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_policies(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """List the caller's tenant's auto-fix policies."""
    query = (
        select(Policy)
        .where(Policy.tenant_id == tenant_id)
        .order_by(Policy.created_at)
    )
    result = await db.execute(query)
    policies = result.scalars().all()

    return {
        "policies": [
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "action_type": p.action_type,
                "auto_approve": p.auto_approve,
                "conditions": p.conditions,
                "constraints": p.constraints,
                "approval_timeout_minutes": p.approval_timeout_minutes,
                "enabled": p.enabled,
            }
            for p in policies
        ],
    }


@router.post("")
async def create_policy(
    policy: PolicyCreate,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new auto-fix policy for the caller's tenant."""
    new_policy = Policy(
        tenant_id=tenant_id,
        name=policy.name,
        description=policy.description,
        action_type=policy.action_type,
        auto_approve=policy.auto_approve,
        conditions=policy.conditions,
        constraints=policy.constraints,
        approval_timeout_minutes=policy.approval_timeout_minutes,
    )
    db.add(new_policy)
    await db.commit()

    return {
        "status": "created",
        "id": str(new_policy.id),
        "message": f"Policy '{policy.name}' created",
    }


@router.post("/seed-defaults")
async def seed_default_policies(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """
    Seed default policies for common auto-fix scenarios.
    Run this once during initial setup.
    """
    defaults = [
        Policy(
            tenant_id=tenant_id,
            name="Auto-restart crashed pods",
            description="Automatically restart pods that are in CrashLoopBackOff state",
            action_type="restart_pod",
            auto_approve=True,
            conditions={"error_type": "CrashLoopBackOff"},
            constraints={"max_restarts": 3, "cooldown_minutes": 5},
        ),
        Policy(
            tenant_id=tenant_id,
            name="Auto-scale on high CPU",
            description="Scale up replicas when CPU usage exceeds 85%",
            action_type="scale_horizontal",
            auto_approve=True,
            conditions={"metric": "cpu_usage", "threshold": 85},
            constraints={"max_replicas": 10, "scale_increment": 2},
        ),
        Policy(
            tenant_id=tenant_id,
            name="Rollback bad deployments",
            description="Rollback deployments when error rate spikes after deploy",
            action_type="rollback_deployment",
            auto_approve=False,  # Needs human approval
            conditions={"error_rate_spike": True, "recent_deploy": True},
            constraints={"approval_timeout_minutes": 15},
            approval_timeout_minutes=15,
        ),
        Policy(
            tenant_id=tenant_id,
            name="Clear disk space",
            description="Clean temporary files and old logs when disk usage exceeds 90%",
            action_type="clear_disk",
            auto_approve=True,
            conditions={"metric": "disk_usage", "threshold": 90},
            constraints={"target_dirs": ["/tmp", "/var/log"], "max_clean_gb": 5},
        ),
        Policy(
            tenant_id=tenant_id,
            name="Database operations (always manual)",
            description="Database changes always require human approval",
            action_type="database_operation",
            auto_approve=False,
            conditions={},
            constraints={"require_approval": True, "no_timeout_auto": True},
            approval_timeout_minutes=0,  # Never auto-approve
        ),
    ]

    for policy in defaults:
        db.add(policy)
    await db.commit()

    return {
        "status": "seeded",
        "message": f"Created {len(defaults)} default policies",
        "policies": [p.name for p in defaults],
    }


async def _get_owned_policy(policy_id: UUID, tenant_id: str, db: AsyncSession) -> Policy:
    """Fetch a policy scoped to the caller's tenant, or 404."""
    result = await db.execute(
        select(Policy).where(Policy.id == policy_id, Policy.tenant_id == tenant_id)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.patch("/{policy_id}")
async def update_policy(
    policy_id: UUID,
    updates: PolicyUpdate,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update fields on one of the caller's policies (e.g. toggle enabled)."""
    policy = await _get_owned_policy(policy_id, tenant_id, db)
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    await db.commit()
    return {"status": "updated", "id": str(policy.id)}


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: UUID,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete one of the caller's policies."""
    policy = await _get_owned_policy(policy_id, tenant_id, db)
    await db.delete(policy)
    await db.commit()
    return {"status": "deleted", "id": str(policy_id)}
