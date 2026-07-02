"""
Per-tenant Slack OAuth install flow (Phase 4, item 13).

  GET /api/v1/slack/oauth/install   (Clerk-authenticated)
      Returns the Slack authorize URL for the caller's tenant. The dashboard
      redirects the browser there. `state` is an HMAC-signed, short-lived token
      binding the install to the tenant so the callback can't be forged.

  GET /api/v1/slack/oauth/callback   (hit by Slack's redirect)
      Verifies state, exchanges the code for a bot token via oauth.v2.access,
      and stores it (encrypted) + team id on the tenant, then bounces the user
      back to the dashboard.
"""

import base64
import hashlib
import hmac
import time
import urllib.parse

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.db.database import async_session
from app.auth.clerk import get_current_tenant
from app.models.tenant import Tenant
from app.integrations.slack_crypto import encrypt_token

log = structlog.get_logger()
router = APIRouter()

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_ACCESS_URL = "https://slack.com/api/oauth.v2.access"
STATE_TTL_SECONDS = 600  # 10 minutes


def _redirect_uri() -> str:
    return f"{settings.BACKEND_BASE_URL.rstrip('/')}/api/v1/slack/oauth/callback"


def _sign_state(tenant_id: str) -> str:
    """HMAC-signed, timestamped state binding the install to a tenant."""
    ts = str(int(time.time()))
    msg = f"{tenant_id}:{ts}"
    sig = hmac.new(settings.SLACK_CLIENT_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}:{sig}".encode()).decode()


def _verify_state(state: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
        tenant_id, ts, sig = raw.rsplit(":", 2)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    expected = hmac.new(
        settings.SLACK_CLIENT_SECRET.encode(), f"{tenant_id}:{ts}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=400, detail="OAuth state signature mismatch")
    if int(time.time()) - int(ts) > STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired")
    return tenant_id


async def _exchange_code(code: str) -> dict:
    """Exchange an OAuth code for a bot token. Isolated for testability."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(SLACK_ACCESS_URL, data={
            "client_id": settings.SLACK_CLIENT_ID,
            "client_secret": settings.SLACK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": _redirect_uri(),
        })
    return resp.json()


@router.get("/oauth/install")
async def slack_oauth_install(tenant_id: str = Depends(get_current_tenant)):
    """Return the Slack authorize URL for this tenant (dashboard redirects to it)."""
    if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Slack OAuth is not configured")
    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": settings.SLACK_OAUTH_SCOPES,
        "redirect_uri": _redirect_uri(),
        "state": _sign_state(tenant_id),
    }
    return {"authorize_url": f"{SLACK_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"}


@router.get("/oauth/callback")
async def slack_oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Slack redirects here after the user approves the install."""
    if error:
        return RedirectResponse(f"{settings.FRONTEND_BASE_URL.rstrip('/')}/settings?slack=denied")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state")

    tenant_id = _verify_state(state)
    data = await _exchange_code(code)

    if not data.get("ok"):
        log.error("Slack OAuth exchange failed", error=data.get("error"), tenant_id=tenant_id)
        return RedirectResponse(f"{settings.FRONTEND_BASE_URL.rstrip('/')}/settings?slack=error")

    bot_token = data.get("access_token")
    team_id = (data.get("team") or {}).get("id")
    # If the incoming-webhook scope was granted, capture the chosen channel.
    channel_id = (data.get("incoming_webhook") or {}).get("channel_id")

    async with async_session() as db:
        tenant = (await db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(id=tenant_id)
            db.add(tenant)
        tenant.slack_bot_token = encrypt_token(bot_token)
        tenant.slack_team_id = team_id
        if channel_id:
            tenant.slack_channel_id = channel_id
        await db.commit()

    log.info("Slack workspace connected", tenant_id=tenant_id, team_id=team_id)
    return RedirectResponse(f"{settings.FRONTEND_BASE_URL.rstrip('/')}/settings?slack=connected")
