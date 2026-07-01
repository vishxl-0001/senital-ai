"""
Phase 5 verification — item 16: audit_log is written on fix execution.

Runs the real execute_fix_task body (Slack-approved) against the test DB with the
K8s executor stubbed to a simulated success, and asserts the audit trail captures:
  - a human 'execute_fix' row with approval_source + approver id (who authorized)
  - an ai 'fix_execution_result' row with before/after status (what happened)
"""

import asyncio

import pytest
from sqlalchemy import select

from app.models.incident import Incident, IncidentStatus, Severity
from app.models.audit import AuditLog
from app.worker import execute_fix_task

TENANT = "org_audit_test"
APPROVER = "U_SLACK_APPROVER"


async def _seed_approved_incident(db_session):
    inc = Incident(
        tenant_id=TENANT, incident_number=1, title="fix me", source="test",
        status=IncidentStatus.FIX_APPROVED, severity=Severity.HIGH,
        fix_type="restart_pod",
        fix_plan={"fix_type": "restart_pod", "steps": [
            {"order": 1, "action": "restart pod", "command": "kubectl delete pod x"}
        ]},
        detected_at=None,
    )
    db_session.add(inc)
    await db_session.commit()
    await db_session.refresh(inc)
    return str(inc.id)


async def test_fix_execution_writes_audit_trail(db_session, app_session_nullpool, monkeypatch):
    iid = await _seed_approved_incident(db_session)

    # Force simulated execution (no real K8s) so execute_fix returns success.
    monkeypatch.setattr("app.engine.executor._get_k8s_clients", lambda: (None, None))

    async def _noop_slack(*a, **k):
        return None
    monkeypatch.setattr("app.integrations.slack_bot.send_incident_to_slack", _noop_slack)

    # Run the task body in a thread — it calls asyncio.run() internally.
    await asyncio.to_thread(execute_fix_task.run, iid, approval_source="slack", approver_id=APPROVER)

    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.tenant_id == TENANT).order_by(AuditLog.created_at)
    )).scalars().all()

    actions = [r.action for r in rows]
    # human approval + per-step ai execution + ai outcome
    assert "execute_fix" in actions
    assert "fix_execution_result" in actions
    assert any(a.startswith("execute_step:") for a in actions)

    approval = next(r for r in rows if r.action == "execute_fix")
    assert approval.actor == "human"
    assert approval.actor_id == APPROVER
    assert approval.approval_source == "slack"
    assert approval.target_id == iid

    outcome = next(r for r in rows if r.action == "fix_execution_result")
    assert outcome.actor == "ai"
    assert outcome.before_state["status"] == "fix_approved"
    assert outcome.after_state["status"] == "resolved"


async def test_audit_rows_are_tenant_scoped(db_session, app_session_nullpool, monkeypatch):
    """Every audit row carries the incident's tenant_id (isolation)."""
    iid = await _seed_approved_incident(db_session)
    monkeypatch.setattr("app.engine.executor._get_k8s_clients", lambda: (None, None))

    async def _noop_slack(*a, **k):
        return None
    monkeypatch.setattr("app.integrations.slack_bot.send_incident_to_slack", _noop_slack)

    await asyncio.to_thread(execute_fix_task.run, iid, approval_source="dashboard")

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert rows, "expected audit rows"
    assert all(r.tenant_id == TENANT for r in rows)
