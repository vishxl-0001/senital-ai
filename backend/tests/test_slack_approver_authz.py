"""
Phase 2 verification — item 9: Slack 'Approve fix' authorization (fail-closed).

Before: _handle_approve ran execute_fix_task.delay() for ANY workspace member.
Now: only Slack user IDs on the incident-owning tenant's allow-list may approve;
an unconfigured/empty allow-list rejects the approval (fail closed). The fix task
must NOT fire and the incident status must NOT change for an unauthorized click.
"""

import pytest

from app.integrations import slack_events
from app.integrations.slack_events import is_authorized_approver, _handle_approve
from app.models.incident import Incident, IncidentStatus, Severity
from app.models.tenant import Tenant

ORG = "org_phase2_item9"
APPROVER = "U_APPROVER"
RANDOM_USER = "U_RANDOM"


# ── Pure authorization function ─────────────────────────────────────────────

def test_authz_fails_closed_when_no_list():
    assert is_authorized_approver(None, APPROVER) is False
    assert is_authorized_approver([], APPROVER) is False


def test_authz_allows_listed_user_only():
    assert is_authorized_approver([APPROVER], APPROVER) is True
    assert is_authorized_approver([APPROVER], RANDOM_USER) is False
    assert is_authorized_approver([APPROVER], "") is False


# ── End-to-end handler behavior (real test DB, mocked side-effects) ─────────

class _Spy:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


async def _seed(db_session, tenant_id, approver_ids):
    db_session.add(Tenant(id=tenant_id, name="ACME", slack_approver_ids=approver_ids))
    inc = Incident(
        tenant_id=tenant_id, title="needs approval", source="test",
        status=IncidentStatus.FIX_PROPOSED, severity=Severity.HIGH,
    )
    db_session.add(inc)
    await db_session.commit()
    await db_session.refresh(inc)
    return str(inc.id)


def _patch_side_effects(monkeypatch):
    """Mock the Celery dispatch and Slack notification; return the task spy."""
    spy = _Spy()
    monkeypatch.setattr("app.worker.execute_fix_task", spy)

    async def _noop_notify(*a, **k):
        return None
    monkeypatch.setattr("app.integrations.slack_bot.send_slack_notification", _noop_notify)
    return spy


async def _status_of(db_session, incident_id):
    from sqlalchemy import select
    db_session.expire_all()
    inc = (await db_session.execute(
        select(Incident).where(Incident.id == incident_id)
    )).scalar_one()
    return inc.status


async def test_unauthorized_click_does_not_execute(db_session, app_session_maker, monkeypatch):
    spy = _patch_side_effects(monkeypatch)
    iid = await _seed(db_session, ORG, approver_ids=[APPROVER])

    await _handle_approve(iid, RANDOM_USER, "random", {"channel": {"id": "C1"}})

    assert spy.calls == [], "unauthorized approval must NOT dispatch the fix task"
    assert await _status_of(db_session, iid) == IncidentStatus.FIX_PROPOSED


async def test_no_approver_list_fails_closed(db_session, app_session_maker, monkeypatch):
    spy = _patch_side_effects(monkeypatch)
    iid = await _seed(db_session, ORG, approver_ids=None)  # unconfigured

    await _handle_approve(iid, APPROVER, "alice", {"channel": {"id": "C1"}})

    assert spy.calls == [], "with no allow-list, approval must fail closed"
    assert await _status_of(db_session, iid) == IncidentStatus.FIX_PROPOSED


async def test_authorized_click_executes(db_session, app_session_maker, monkeypatch):
    spy = _patch_side_effects(monkeypatch)
    iid = await _seed(db_session, ORG, approver_ids=[APPROVER])

    await _handle_approve(iid, APPROVER, "alice", {"channel": {"id": "C1"}})

    assert len(spy.calls) == 1, "authorized approval must dispatch the fix task once"
    assert spy.calls[0][0] == (iid,)
    assert await _status_of(db_session, iid) == IncidentStatus.FIX_APPROVED
