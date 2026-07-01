"""
Audit logging helper (Phase 5, item 16).

record_audit() writes one append-only audit row in its own short transaction, so
callers don't have to thread a DB session through deep code paths (executor
actions, Celery task bodies). Failures to audit are logged but never raise — an
audit hiccup must not abort a remediation.
"""

import structlog

from app.db.database import async_session
from app.models.audit import AuditLog

log = structlog.get_logger()


async def record_audit(
    *,
    tenant_id: str,
    actor: str,                      # "ai" | "human" | "system"
    action: str,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    approval_source: str | None = None,
) -> None:
    if not tenant_id:
        # tenant_id is required for isolation; skip rather than write an orphan row.
        log.warning("audit skipped: missing tenant_id", action=action)
        return
    try:
        async with async_session() as db:
            db.add(AuditLog(
                tenant_id=tenant_id,
                actor=actor,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_state=before_state,
                after_state=after_state,
                approval_source=approval_source,
            ))
            await db.commit()
    except Exception as e:  # never let auditing break the action it records
        log.error("failed to write audit log", action=action, error=str(e))
