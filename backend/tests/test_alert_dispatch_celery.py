"""
Phase 4 verification — item 12: alerts go through Celery, not BackgroundTasks.

Before: api/alerts.py ran the whole investigation pipeline via FastAPI
BackgroundTasks in the web process — a restart mid-investigation dropped it with
no retry. Now each alert is dispatched as a durable Celery task
(process_alert_task), which survives worker restarts (acks_late) and retries.

These tests assert the *dispatch contract*: the endpoints enqueue the task with
the serialized alert (and the right tenant), and the task body runs process_alert.
"""

import pytest

import app.api.alerts as alerts_mod
from app.worker import process_alert_task


class _DelaySpy:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_task_is_durable_config():
    # acks_late + bounded retries => not silently lost on restart.
    assert process_alert_task.acks_late is True
    assert process_alert_task.max_retries == 3


async def test_generic_webhook_enqueues_task(monkeypatch):
    spy = _DelaySpy()
    monkeypatch.setattr(alerts_mod, "process_alert_task", spy)

    alert = alerts_mod.GenericAlert(source="datadog", title="disk full")
    resp = await alerts_mod.receive_generic_alert(alert, tenant_id="org_X")

    assert resp["status"] == "accepted"
    assert len(spy.calls) == 1
    payload = spy.calls[0][0][0]
    assert isinstance(payload, dict)              # JSON-serializable, not a live object
    assert payload["tenant_id"] == "org_X"        # tenant injected server-side
    assert payload["title"] == "disk full"


async def test_test_endpoint_enqueues_task(monkeypatch):
    spy = _DelaySpy()
    monkeypatch.setattr(alerts_mod, "process_alert_task", spy)

    resp = await alerts_mod.send_test_alert(tenant_id="org_Y")

    assert resp["status"] == "accepted"
    assert len(spy.calls) == 1
    assert spy.calls[0][0][0]["tenant_id"] == "org_Y"


def test_task_body_runs_process_alert(monkeypatch):
    """process_alert_task should rebuild the alert and call orchestrator.process_alert."""
    seen = {}

    async def _fake_process_alert(alert):
        seen["tenant_id"] = alert.tenant_id
        seen["title"] = alert.title

    monkeypatch.setattr("app.agents.orchestrator.process_alert", _fake_process_alert)

    # Call the task synchronously (its body runs asyncio.run internally).
    process_alert_task.run({"source": "test", "title": "boom", "tenant_id": "org_Z"})

    assert seen == {"tenant_id": "org_Z", "title": "boom"}
