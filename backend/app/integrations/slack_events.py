"""
Sentinel AI — Slack Event Handlers
Handles button clicks (Approve/Reject) and slash commands from Slack.
Runs as a separate async handler mounted on FastAPI.
"""

import json
import structlog
from fastapi import APIRouter, Request, Response
from slack_sdk.signature import SignatureVerifier

from app.config import settings

log = structlog.get_logger()
router = APIRouter()

_verifier = None


def get_verifier():
    global _verifier
    if _verifier is None and settings.SLACK_SIGNING_SECRET:
        _verifier = SignatureVerifier(signing_secret=settings.SLACK_SIGNING_SECRET)
    return _verifier


@router.post("/events")
async def slack_events(request: Request):
    """Handle Slack Events API (url_verification + event callbacks)."""
    body = await request.body()
    payload = await request.json()

    # URL verification challenge (Slack sends this when you set up the Events URL)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # Verify signature
    verifier = get_verifier()
    if verifier:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not verifier.is_valid(body.decode(), timestamp, signature):
            log.warning("⚠️ Invalid Slack signature")
            return Response(status_code=403)

    event = payload.get("event", {})
    event_type = event.get("type")

    if event_type == "app_mention":
        # Someone @mentioned the bot
        text = event.get("text", "").lower()
        channel = event.get("channel")
        log.info("🤖 Bot mentioned", channel=channel, text=text)
        # TODO: Handle natural language commands like "@sentinel investigate payment-service"

    return Response(status_code=200)


@router.post("/interactions")
async def slack_interactions(request: Request):
    """
    Handle Slack interactive components — button clicks (Approve/Reject).
    This is where human-in-the-loop approval happens.
    """
    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    action_type = payload.get("type")

    if action_type == "block_actions":
        actions = payload.get("actions", [])
        user = payload.get("user", {}).get("username", "unknown")

        for action in actions:
            action_id = action.get("action_id")
            value = json.loads(action.get("value", "{}"))
            incident_id = value.get("incident_id")

            log.info(
                "🔘 Slack button clicked",
                action=action_id,
                user=user,
                incident_id=incident_id,
            )

            if action_id == "approve_fix":
                await _handle_approve(incident_id, user, payload)
            elif action_id == "reject_fix":
                await _handle_reject(incident_id, user, payload)

    return Response(status_code=200)


async def _handle_approve(incident_id: str, user: str, payload: dict):
    """Handle fix approval from Slack."""
    from app.db.database import async_session
    from sqlalchemy import select
    from app.models.incident import Incident, IncidentStatus
    from app.worker import execute_fix_task

    log.info(f"✅ Fix approved by {user} for incident {incident_id}")

    async with async_session() as db:
        result = await db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        incident = result.scalar_one_or_none()

        if not incident:
            log.error(f"Incident {incident_id} not found")
            return

        if incident.status != IncidentStatus.FIX_PROPOSED:
            log.warning(f"Incident {incident_id} is in {incident.status.value}, cannot approve")
            return

        incident.status = IncidentStatus.FIX_APPROVED
        incident.fix_approval = "manual"
        await db.commit()

    # Trigger fix execution via Celery
    execute_fix_task.delay(incident_id)

    # Update the Slack message to show it was approved
    from app.integrations.slack_bot import send_slack_notification
    channel = payload.get("channel", {}).get("id", "#incidents")
    await send_slack_notification(
        channel,
        f"✅ *Fix approved* by <@{user}> for incident `{incident_id}`. Executing now..."
    )


async def _handle_reject(incident_id: str, user: str, payload: dict):
    """Handle fix rejection from Slack."""
    from app.db.database import async_session
    from sqlalchemy import select
    from app.models.incident import Incident, IncidentStatus

    log.info(f"❌ Fix rejected by {user} for incident {incident_id}")

    async with async_session() as db:
        result = await db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        incident = result.scalar_one_or_none()

        if incident:
            incident.status = IncidentStatus.ESCALATED
            await db.commit()

    from app.integrations.slack_bot import send_slack_notification
    channel = payload.get("channel", {}).get("id", "#incidents")
    await send_slack_notification(
        channel,
        f"❌ *Fix rejected* by <@{user}> for incident `{incident_id}`. Escalated for manual review."
    )
