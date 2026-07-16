"""
External mode — uptime monitors.

Covers: CRUD + tenant isolation + validation, the check engine (mocked httpx),
threshold-gated alert firing, the fingerprint contract that recovery relies on,
incident resolution on recovery, and dispatcher due-selection.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from tests.conftest import auth


class _DelaySpy:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


# ── CRUD API ────────────────────────────────────────────────────────────────

async def test_create_and_list_monitor(client, make_token):
    token = make_token(org_id="org_A")
    resp = await client.post(
        "/api/v1/monitors",
        json={"name": "Main site", "url": "https://example.com"},
        headers=auth(token),
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["status"] == "pending"
    assert created["interval_seconds"] == 60          # default
    assert created["failure_threshold"] == 2          # default

    resp = await client.get("/api/v1/monitors", headers=auth(token))
    assert resp.status_code == 200
    monitors = resp.json()["monitors"]
    assert len(monitors) == 1
    assert monitors[0]["url"] == "https://example.com"


async def test_tenant_isolation(client, make_token):
    token_a = make_token(org_id="org_A")
    token_b = make_token(org_id="org_B")

    resp = await client.post(
        "/api/v1/monitors",
        json={"name": "A's site", "url": "https://a.example.com"},
        headers=auth(token_a),
    )
    monitor_id = resp.json()["id"]

    # B sees an empty list and cannot read/modify/delete A's monitor
    resp = await client.get("/api/v1/monitors", headers=auth(token_b))
    assert resp.json()["monitors"] == []
    for method, path in [
        ("get", f"/api/v1/monitors/{monitor_id}"),
        ("delete", f"/api/v1/monitors/{monitor_id}"),
        ("post", f"/api/v1/monitors/{monitor_id}/pause"),
    ]:
        resp = await getattr(client, method)(path, headers=auth(token_b))
        assert resp.status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",           # non-http scheme
        "https://localhost/x",         # local hostname
        "http://127.0.0.1:8000",       # loopback IP
        "http://192.168.1.10",         # private IP
        "http://redis",                # compose-internal hostname (no dot)
    ],
)
async def test_url_validation_rejects_internal_targets(client, make_token, url):
    token = make_token(org_id="org_A")
    resp = await client.post(
        "/api/v1/monitors", json={"name": "bad", "url": url}, headers=auth(token)
    )
    assert resp.status_code == 422


async def test_interval_below_minimum_rejected(client, make_token):
    token = make_token(org_id="org_A")
    resp = await client.post(
        "/api/v1/monitors",
        json={"name": "too fast", "url": "https://example.com", "interval_seconds": 5},
        headers=auth(token),
    )
    assert resp.status_code == 422


async def test_duplicate_url_conflict(client, make_token):
    token = make_token(org_id="org_A")
    body = {"name": "site", "url": "https://dup.example.com"}
    assert (await client.post("/api/v1/monitors", json=body, headers=auth(token))).status_code == 201
    resp = await client.post("/api/v1/monitors", json=body, headers=auth(token))
    assert resp.status_code == 409


async def test_monitor_cap_enforced(client, make_token, monkeypatch):
    import app.api.monitors as monitors_mod

    monkeypatch.setattr(monitors_mod, "MAX_MONITORS_PER_TENANT", 2)
    token = make_token(org_id="org_A")
    for i in range(2):
        resp = await client.post(
            "/api/v1/monitors",
            json={"name": f"m{i}", "url": f"https://site{i}.example.com"},
            headers=auth(token),
        )
        assert resp.status_code == 201
    resp = await client.post(
        "/api/v1/monitors",
        json={"name": "one too many", "url": "https://site9.example.com"},
        headers=auth(token),
    )
    assert resp.status_code == 400


async def test_pause_and_resume(client, make_token):
    token = make_token(org_id="org_A")
    resp = await client.post(
        "/api/v1/monitors",
        json={"name": "site", "url": "https://example.com"},
        headers=auth(token),
    )
    monitor_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/monitors/{monitor_id}/pause", headers=auth(token))
    assert resp.json()["status"] == "paused"
    assert resp.json()["is_active"] is False

    resp = await client.post(f"/api/v1/monitors/{monitor_id}/resume", headers=auth(token))
    assert resp.json()["status"] == "pending"
    assert resp.json()["is_active"] is True
    assert resp.json()["last_checked_at"] is None  # rechecked on next sweep


# ── Check engine (mocked httpx) ─────────────────────────────────────────────

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_http(monkeypatch, handler):
    """Route app.engine.uptime's httpx.AsyncClient through a MockTransport."""

    class _Factory:
        def __init__(self, **kwargs):
            kwargs.pop("transport", None)
            self._client = _REAL_ASYNC_CLIENT(
                transport=httpx.MockTransport(handler), **kwargs
            )

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *exc):
            await self._client.aclose()

    monkeypatch.setattr("app.engine.uptime.httpx.AsyncClient", _Factory)


def _stub_monitor(**overrides):
    base = dict(
        id=uuid.uuid4(),
        tenant_id="org_A",
        name="site",
        url="https://example.com",
        timeout_seconds=5,
        expected_status_codes=[200],
        keyword=None,
        latency_threshold_ms=None,
        consecutive_failures=2,
        failure_threshold=2,
        ssl_expires_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_check_ok(monkeypatch):
    from app.engine.uptime import perform_http_check

    _patch_http(monkeypatch, lambda req: httpx.Response(200, text="hello world"))
    result = await perform_http_check(_stub_monitor())
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["response_ms"] is not None


async def test_check_bad_status(monkeypatch):
    from app.engine.uptime import perform_http_check

    _patch_http(monkeypatch, lambda req: httpx.Response(500, text="oops"))
    result = await perform_http_check(_stub_monitor())
    assert result["ok"] is False
    assert result["severity"] == "critical"
    assert "unexpected status 500" in result["failure_reason"]


async def test_check_keyword_missing(monkeypatch):
    from app.engine.uptime import perform_http_check

    # 200 page WITHOUT the keyword = effectively down (error page served as 200)
    _patch_http(monkeypatch, lambda req: httpx.Response(200, text="database error"))
    result = await perform_http_check(_stub_monitor(keyword="Welcome"))
    assert result["ok"] is False
    assert result["severity"] == "critical"
    assert "keyword" in result["failure_reason"]


async def test_check_slow_response(monkeypatch):
    import time as time_mod
    from app.engine.uptime import perform_http_check

    def _slow(req):
        time_mod.sleep(0.02)  # ~20ms, well over the 1ms threshold
        return httpx.Response(200, text="ok")

    _patch_http(monkeypatch, _slow)
    result = await perform_http_check(_stub_monitor(latency_threshold_ms=1))
    assert result["ok"] is False
    assert result["severity"] == "medium"  # slow is not the same as down
    assert "slow" in result["failure_reason"]


async def test_check_connection_error(monkeypatch):
    from app.engine.uptime import perform_http_check

    def _raise(req):
        raise httpx.ConnectError("connection refused")

    _patch_http(monkeypatch, _raise)
    result = await perform_http_check(_stub_monitor())
    assert result["ok"] is False
    assert result["severity"] == "critical"
    assert "connection error" in result["failure_reason"]


# ── Fingerprint contract (recovery correctness) ─────────────────────────────

def test_down_alert_fingerprint_matches_uptime_fingerprint():
    """
    uptime_fingerprint(monitor) MUST equal the dedup fingerprint of the DOWN
    alert we dispatch — it's how recovery finds the open incident to resolve.
    """
    from app.api.alerts import GenericAlert
    from app.engine.dedup import generate_fingerprint
    from app.engine.uptime import build_down_alert, uptime_fingerprint

    monitor = _stub_monitor()
    check = {"failure_reason": "unexpected status 500", "status_code": 500,
             "response_ms": 12, "severity": "critical"}
    alert = GenericAlert(**build_down_alert(monitor, check))
    assert generate_fingerprint(alert) == uptime_fingerprint(monitor)


def test_ssl_alert_severity_scales_with_days():
    from app.engine.uptime import build_ssl_alert

    monitor = _stub_monitor(ssl_expires_at=datetime.utcnow() + timedelta(days=2))
    assert build_ssl_alert(monitor, 2)["severity"] == "high"
    assert build_ssl_alert(monitor, 10)["severity"] == "medium"


# ── Check task: threshold-gated firing ──────────────────────────────────────

async def _seed_monitor(maker, **overrides):
    from app.models.monitor import UptimeMonitor

    fields = dict(
        tenant_id="org_A",
        name="site",
        url="http://example.com",  # http => SSL check skipped
        failure_threshold=2,
        ssl_check_enabled=False,
    )
    fields.update(overrides)
    async with maker() as db:
        monitor = UptimeMonitor(**fields)
        db.add(monitor)
        await db.commit()
        await db.refresh(monitor)
        return monitor.id


async def test_alert_fires_exactly_once_at_threshold(app_session_nullpool, monkeypatch):
    import app.worker as worker

    monitor_id = await _seed_monitor(app_session_nullpool)

    async def _failing_check(monitor):
        return {"ok": False, "failure_reason": "unexpected status 500",
                "status_code": 500, "response_ms": 10, "severity": "critical"}

    monkeypatch.setattr("app.engine.uptime.perform_http_check", _failing_check)
    spy = _DelaySpy()
    monkeypatch.setattr(worker, "process_alert_task", spy)

    # failure 1/2 — below threshold, no alert
    await asyncio.to_thread(worker.check_monitor_task.run, str(monitor_id))
    assert len(spy.calls) == 0

    # failure 2/2 — threshold reached, alert fires once
    await asyncio.to_thread(worker.check_monitor_task.run, str(monitor_id))
    assert len(spy.calls) == 1
    payload = spy.calls[0][0][0]
    assert payload["tenant_id"] == "org_A"
    assert payload["source"] == "uptime"
    assert payload["severity"] == "critical"

    # failure 3 — already down, must NOT re-fire
    await asyncio.to_thread(worker.check_monitor_task.run, str(monitor_id))
    assert len(spy.calls) == 1

    from sqlalchemy import select
    from app.models.monitor import UptimeMonitor, MonitorStatus

    async with app_session_nullpool() as db:
        monitor = (
            await db.execute(select(UptimeMonitor).where(UptimeMonitor.id == monitor_id))
        ).scalar_one()
        assert monitor.status == MonitorStatus.DOWN
        assert monitor.consecutive_failures == 3


async def test_recovery_resolves_incident(app_session_nullpool, monkeypatch):
    import app.worker as worker
    from sqlalchemy import select
    from app.models.incident import Incident, IncidentStatus, IncidentTimeline
    from app.models.monitor import UptimeMonitor, MonitorStatus
    from app.engine.uptime import uptime_fingerprint

    monitor_id = await _seed_monitor(
        app_session_nullpool,
        status=MonitorStatus.DOWN,
        consecutive_failures=2,
    )

    # Seed the open incident the DOWN alert would have created
    async with app_session_nullpool() as db:
        monitor = (
            await db.execute(select(UptimeMonitor).where(UptimeMonitor.id == monitor_id))
        ).scalar_one()
        incident = Incident(
            tenant_id="org_A",
            incident_number=1,
            title=f"Monitor down: {monitor.name}",
            status=IncidentStatus.DETECTED,
            source="uptime",
            source_alert_id=uptime_fingerprint(monitor),
            detected_at=datetime.utcnow() - timedelta(minutes=5),
        )
        db.add(incident)
        await db.commit()
        incident_id = incident.id

    async def _ok_check(monitor):
        return {"ok": True, "failure_reason": None, "status_code": 200,
                "response_ms": 42, "severity": "info"}

    slack_calls = []

    async def _fake_slack(channel, text, tenant_id=None):
        slack_calls.append({"text": text, "tenant_id": tenant_id})

    monkeypatch.setattr("app.engine.uptime.perform_http_check", _ok_check)
    monkeypatch.setattr("app.integrations.slack_bot.send_slack_notification", _fake_slack)

    await asyncio.to_thread(worker.check_monitor_task.run, str(monitor_id))

    async with app_session_nullpool() as db:
        incident = (
            await db.execute(select(Incident).where(Incident.id == incident_id))
        ).scalar_one()
        assert incident.status == IncidentStatus.RESOLVED
        assert incident.resolved_at is not None
        assert incident.mttr_seconds is not None

        timeline = (
            await db.execute(
                select(IncidentTimeline).where(IncidentTimeline.incident_id == incident_id)
            )
        ).scalars().all()
        assert any(t.title == "Monitor recovered" for t in timeline)

        monitor = (
            await db.execute(select(UptimeMonitor).where(UptimeMonitor.id == monitor_id))
        ).scalar_one()
        assert monitor.status == MonitorStatus.UP
        assert monitor.consecutive_failures == 0

    assert len(slack_calls) == 1
    assert "Recovered" in slack_calls[0]["text"]
    assert slack_calls[0]["tenant_id"] == "org_A"


# ── Dispatcher due-selection ────────────────────────────────────────────────

async def test_dispatcher_selects_due_monitors(app_session_nullpool, monkeypatch):
    import app.worker as worker

    now = datetime.utcnow()
    never_checked = await _seed_monitor(
        app_session_nullpool, url="http://a.example.com")
    checked_recently = await _seed_monitor(
        app_session_nullpool, url="http://b.example.com",
        last_checked_at=now - timedelta(seconds=10), interval_seconds=60)
    overdue = await _seed_monitor(
        app_session_nullpool, url="http://c.example.com",
        last_checked_at=now - timedelta(seconds=120), interval_seconds=60)
    inactive = await _seed_monitor(
        app_session_nullpool, url="http://d.example.com", is_active=False)

    spy = _DelaySpy()
    monkeypatch.setattr(worker, "check_monitor_task", spy)

    await asyncio.to_thread(worker.check_due_monitors.run)

    dispatched = {call[0][0] for call in spy.calls}
    assert dispatched == {str(never_checked), str(overdue)}
    assert str(checked_recently) not in dispatched
    assert str(inactive) not in dispatched
