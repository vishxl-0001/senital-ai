"""
External mode — vendor webhook adapters.

Each endpoint accepts the vendor's native payload shape, authenticates via
X-API-Key header (or ?api_key= query fallback), translates to GenericAlert and
enqueues process_alert_task. Ignored event types (recoveries, SNS non-ALARM)
still return 200 so vendors don't retry.
"""

import pytest

import app.api.webhooks_vendors as vendors_mod
from app.api.auth import hash_api_key


RAW_KEY = "sentinel_testkey_vendor_0000000000"


class _DelaySpy:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    @property
    def payloads(self):
        return [c[0][0] for c in self.calls]


@pytest.fixture
async def api_key(db_session):
    """Seed an active API key for org_A and return the raw key."""
    from app.models.tenant import ApiKey

    db_session.add(
        ApiKey(
            tenant_id="org_A",
            name="vendor key",
            key_hash=hash_api_key(RAW_KEY),
            prefix=RAW_KEY[:12] + "...",
            is_active=True,
        )
    )
    await db_session.commit()
    return RAW_KEY


@pytest.fixture
def spy(monkeypatch):
    s = _DelaySpy()
    monkeypatch.setattr(vendors_mod, "process_alert_task", s)
    return s


# ── Auth ────────────────────────────────────────────────────────────────────

async def test_missing_key_rejected(client, spy):
    resp = await client.post("/api/v1/webhooks/uptimerobot", json={"alertType": "1"})
    assert resp.status_code == 401
    assert spy.calls == []


async def test_invalid_key_rejected(client, spy):
    resp = await client.post(
        "/api/v1/webhooks/uptimerobot",
        json={"alertType": "1"},
        headers={"X-API-Key": "sentinel_wrong"},
    )
    assert resp.status_code == 401


async def test_query_param_key_fallback(client, api_key, spy):
    """UptimeRobot's free plan can't set headers — ?api_key= must work."""
    resp = await client.post(
        f"/api/v1/webhooks/uptimerobot?api_key={api_key}",
        json={"alertType": "1", "monitorFriendlyName": "api", "monitorURL": "https://x.com"},
    )
    assert resp.status_code == 200
    assert len(spy.calls) == 1
    assert spy.payloads[0]["tenant_id"] == "org_A"


# ── UptimeRobot ─────────────────────────────────────────────────────────────

async def test_uptimerobot_down(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/uptimerobot",
        json={
            "alertType": "1",
            "monitorFriendlyName": "checkout",
            "monitorURL": "https://shop.example.com",
            "alertDetails": "Connection timeout",
        },
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    payload = spy.payloads[0]
    assert payload["source"] == "uptimerobot"
    assert payload["severity"] == "critical"
    assert "checkout" in payload["title"]
    assert payload["tenant_id"] == "org_A"


async def test_uptimerobot_recovery_ignored(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/uptimerobot",
        json={"alertType": "2", "monitorFriendlyName": "checkout"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert spy.calls == []


async def test_uptimerobot_ssl_alert(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/uptimerobot",
        json={"alertType": "3", "monitorFriendlyName": "shop"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert spy.payloads[0]["severity"] == "medium"
    assert "SSL" in spy.payloads[0]["title"]


# ── Sentry ──────────────────────────────────────────────────────────────────

async def test_sentry_issue_new_platform_shape(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/sentry",
        json={
            "action": "created",
            "data": {
                "issue": {
                    "title": "TypeError: cannot read property 'id'",
                    "level": "error",
                    "culprit": "checkout/views.py",
                    "project": {"slug": "shop-backend"},
                }
            },
        },
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    payload = spy.payloads[0]
    assert payload["source"] == "sentry"
    assert payload["severity"] == "high"                # error → high
    assert "TypeError" in payload["title"]
    assert payload["labels"]["service"] == "shop-backend"


async def test_sentry_fatal_maps_to_critical(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/sentry",
        json={"data": {"issue": {"title": "OOM", "level": "fatal"}}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert spy.payloads[0]["severity"] == "critical"


# ── Datadog ─────────────────────────────────────────────────────────────────

async def test_datadog_error_alert(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/datadog",
        json={"alert_type": "error", "title": "CPU high on web-1", "body": "cpu > 95%"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    payload = spy.payloads[0]
    assert payload["source"] == "datadog"
    assert payload["severity"] == "high"
    assert "CPU high" in payload["title"]


async def test_datadog_recovery_ignored(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/datadog",
        json={"alert_type": "success", "title": "CPU recovered"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert spy.calls == []


# ── CloudWatch (SNS) ────────────────────────────────────────────────────────

async def test_cloudwatch_alarm_notification(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/cloudwatch",
        json={
            "Type": "Notification",
            "Message": (
                '{"AlarmName": "disk-full-web1", "NewStateValue": "ALARM",'
                ' "NewStateReason": "Threshold crossed: disk > 85%"}'
            ),
        },
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    payload = spy.payloads[0]
    assert payload["source"] == "cloudwatch"
    assert payload["severity"] == "high"
    assert "disk-full-web1" in payload["title"]
    assert "Threshold crossed" in payload["description"]


async def test_cloudwatch_ok_state_ignored(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/cloudwatch",
        json={
            "Type": "Notification",
            "Message": '{"AlarmName": "disk-full-web1", "NewStateValue": "OK"}',
        },
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert spy.calls == []


async def test_cloudwatch_subscription_confirmation_requires_https(client, api_key, spy):
    resp = await client.post(
        "/api/v1/webhooks/cloudwatch",
        json={"Type": "SubscriptionConfirmation", "SubscribeURL": "http://evil.example.com"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 400
    assert spy.calls == []


async def test_cloudwatch_subscription_confirmation_fetches_url(client, api_key, spy, monkeypatch):
    fetched = []

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def get(self, url):
            fetched.append(url)

    monkeypatch.setattr(vendors_mod.httpx, "AsyncClient", _FakeClient)
    resp = await client.post(
        "/api/v1/webhooks/cloudwatch",
        json={
            "Type": "SubscriptionConfirmation",
            "SubscribeURL": "https://sns.us-east-1.amazonaws.com/confirm?token=abc",
        },
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscription confirmed"
    assert fetched == ["https://sns.us-east-1.amazonaws.com/confirm?token=abc"]
    assert spy.calls == []
