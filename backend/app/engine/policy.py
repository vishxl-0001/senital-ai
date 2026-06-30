"""
Sentinel AI — Policy Engine
Decides whether a fix should be auto-executed or needs human approval.
The "safety brain" of the platform.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Policy

log = structlog.get_logger()


class PolicyDecision:
    """Result of a policy check."""
    def __init__(self, approved: bool, reason: str, policy_name: str = None, timeout_minutes: int = 15):
        self.approved = approved
        self.reason = reason
        self.policy_name = policy_name
        self.timeout_minutes = timeout_minutes


async def check_policy(fix_plan: dict, db: AsyncSession, tenant_id: str = None) -> PolicyDecision:
    """
    Check if a fix plan is approved by policy.

    Returns:
    - approved=True → execute immediately (auto-fix)
    - approved=False → send to Slack for human approval
    """
    fix_type = fix_plan.get("fix_type", "unknown")
    risk_level = fix_plan.get("risk_level", "high")
    recommendation = fix_plan.get("recommendation", "manual_only")

    log.info(
        "🔐 Checking policy",
        fix_type=fix_type,
        risk_level=risk_level,
        ai_recommendation=recommendation,
    )

    # Rule 1: AI says manual_only → always ask human
    if recommendation == "manual_only":
        return PolicyDecision(
            approved=False,
            reason="AI recommended manual-only for this fix",
        )

    # Rule 2: High risk → always ask human
    if risk_level == "high":
        return PolicyDecision(
            approved=False,
            reason=f"Fix has high risk level — requires human approval",
        )

    # Rule 3: Check database policies
    query = select(Policy).where(
        Policy.action_type == fix_type,
        Policy.enabled == True,
    )
    if tenant_id:
        query = query.where(Policy.tenant_id == tenant_id)
        
    result = await db.execute(query)
    policy = result.scalar_one_or_none()

    if policy:
        if policy.auto_approve:
            log.info("✅ Policy auto-approved", policy=policy.name)
            return PolicyDecision(
                approved=True,
                reason=f"Auto-approved by policy: {policy.name}",
                policy_name=policy.name,
            )
        else:
            return PolicyDecision(
                approved=False,
                reason=f"Policy '{policy.name}' requires human approval",
                policy_name=policy.name,
                timeout_minutes=policy.approval_timeout_minutes,
            )

    # Rule 4: No matching policy → default to human approval
    return PolicyDecision(
        approved=False,
        reason="No matching policy found — defaulting to human approval",
    )
