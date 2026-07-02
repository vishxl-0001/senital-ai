"""
Phase 4 verification — item 13: per-tenant Slack OAuth + encrypted token storage.

Covers:
  - HMAC state sign/verify round-trip; tampered/foreign state rejected.
  - Fernet token encrypt/decrypt round-trip.
  - OAuth callback exchanges the code (mocked) and persists an ENCRYPTED bot
    token + team id on the tenant.
  - get_tenant_slack routes to the tenant's own token + channel, and falls back
    to the global client when the tenant hasn't installed.
"""

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select

from app.models.tenant import Tenant
from app.integrations import slack_oauth, slack_crypto
from app.integrations import slack_bot

TENANT = "org_slack_oauth"


@pytest.fixture(autouse=True)
def _slack_env(monkeypatch):
    """Provide a signing secret + a fresh Fernet key for the crypto paths."""
    monkeypatch.setattr("app.config.settings.SLACK_CLIENT_SECRET", "test-signing-secret")
    monkeypatch.setattr("app.config.settings.SLACK_CLIENT_ID", "123.456")
    monkeypatch.setattr("app.config.settings.SLACK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


# ── State signing ────────────────────────────────────────────────────────────

def test_state_roundtrip():
    state = slack_oauth._sign_state(TENANT)
    assert slack_oauth._verify_state(state) == TENANT


def test_tampered_state_rejected():
    state = slack_oauth._sign_state(TENANT)
    tampered = state[:-2] + ("aa" if not state.endswith("aa") else "bb")
    with pytest.raises(HTTPException):
        slack_oauth._verify_state(tampered)


# ── Token encryption ─────────────────────────────────────────────────────────

def test_token_encrypt_decrypt_roundtrip():
    enc = slack_crypto.encrypt_token("xoxb-super-secret")
    assert enc != "xoxb-super-secret"                 # actually encrypted
    assert slack_crypto.decrypt_token(enc) == "xoxb-super-secret"


# ── OAuth callback persists an encrypted per-tenant token ────────────────────

async def test_callback_stores_encrypted_token(db_session, app_session_maker, monkeypatch):
    async def _fake_exchange(code):
        assert code == "the-code"
        return {"ok": True, "access_token": "xoxb-tenant-token", "team": {"id": "T123"}}
    monkeypatch.setattr(slack_oauth, "_exchange_code", _fake_exchange)

    state = slack_oauth._sign_state(TENANT)
    resp = await slack_oauth.slack_oauth_callback(code="the-code", state=state, error=None)
    assert resp.status_code in (302, 307)             # redirect back to dashboard

    tenant = (await db_session.execute(
        select(Tenant).where(Tenant.id == TENANT)
    )).scalar_one()
    assert tenant.slack_team_id == "T123"
    assert tenant.slack_bot_token and tenant.slack_bot_token != "xoxb-tenant-token"
    assert slack_crypto.decrypt_token(tenant.slack_bot_token) == "xoxb-tenant-token"


async def test_callback_rejects_forged_state(db_session, app_session_maker, monkeypatch):
    async def _fake_exchange(code):
        return {"ok": True, "access_token": "x", "team": {"id": "T"}}
    monkeypatch.setattr(slack_oauth, "_exchange_code", _fake_exchange)

    with pytest.raises(HTTPException):
        await slack_oauth.slack_oauth_callback(code="c", state="not-a-valid-state", error=None)


# ── Per-tenant routing ───────────────────────────────────────────────────────

async def test_routing_uses_tenant_token_and_channel(db_session, app_session_nullpool, monkeypatch):
    token = slack_crypto.encrypt_token("xoxb-acme")
    db_session.add(Tenant(id=TENANT, slack_bot_token=token, slack_channel_id="C_ACME"))
    await db_session.commit()

    client, channel = await slack_bot.get_tenant_slack(TENANT)
    assert channel == "C_ACME"
    assert client is not None and client.token == "xoxb-acme"


async def test_routing_falls_back_without_install(db_session, app_session_nullpool, monkeypatch):
    db_session.add(Tenant(id=TENANT))  # no token, no channel
    await db_session.commit()
    # Global client is None when SLACK_BOT_TOKEN unset -> (None, default channel).
    monkeypatch.setattr("app.config.settings.SLACK_BOT_TOKEN", None)
    monkeypatch.setattr(slack_bot, "_client", None)

    client, channel = await slack_bot.get_tenant_slack(TENANT)
    assert channel == "#incidents"
