"""
Sentinel AI — Slack Event Handlers
Handles button clicks (Approve/Reject) and slash commands from Slack.
Runs as a separate async handler mounted on FastAPI.
"""

import json
import structlog
from typing import Optional
from fastapi import APIRouter, Request, Response
from slack_sdk.signature import SignatureVerifier

from app.config import settings
from app.rate_limit import limiter, SLACK_LIMIT

log = structlog.get_logger()
router = APIRouter()

_verifier = None


def get_verifier():
    global _verifier
    if _verifier is None and settings.SLACK_SIGNING_SECRET:
        _verifier = SignatureVerifier(signing_secret=settings.SLACK_SIGNING_SECRET)
    return _verifier


@router.post("/events")
@limiter.limit(SLACK_LIMIT)
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
        # Someone @mentioned the bot. Slack requires a 200 within 3s, so we
        # acknowledge immediately and dispatch any command handling in the
        # background (Slack retries on timeout, which would double-fire).
        team_id = payload.get("team_id")
        text = event.get("text", "")
        channel = event.get("channel")
        log.info("🤖 Bot mentioned", channel=channel, text=text, team_id=team_id)
        await _handle_mention(team_id, channel, text)

    return Response(status_code=200)


# Commands the bot understands from an @mention. Kept intentionally small and
# explicit — this is a control surface over customer infra, so we match known
# verbs rather than free-form LLM interpretation.
def _parse_mention(text: str) -> tuple[str, str]:
    """
    Strip the leading <@BOTID> mention and return (command, argument).
    e.g. "<@U123> investigate payment-service" -> ("investigate", "payment-service")
    """
    import re

    # Remove all <@...> user mentions (the bot's own id leads the text).
    cleaned = re.sub(r"<@[^>]+>", "", text).strip()
    if not cleaned:
        return "", ""
    parts = cleaned.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


async def _resolve_tenant_by_team(team_id: str) -> Optional[str]:
    """Map an installing Slack workspace (team_id) to its tenant_id."""
    if not team_id:
        return None
    from app.db.database import async_session
    from sqlalchemy import select
    from app.models.tenant import Tenant

    async with async_session() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slack_team_id == team_id))
        ).scalar_one_or_none()
        return tenant.id if tenant else None


async def _handle_mention(team_id: str, channel: str, text: str):
    """
    Handle an @mention command. Supported:
      • investigate <service/description>  — open an incident + run the pipeline
      • status                             — summarize open incidents
      • help                               — list commands
    Falls through to a help message for anything unrecognized.
    """
    from app.integrations.slack_bot import send_slack_notification

    command, argument = _parse_mention(text)
    tenant_id = await _resolve_tenant_by_team(team_id)

    if not tenant_id:
        await send_slack_notification(
            channel,
            "⚠️ This Slack workspace isn't linked to a Sentinel organization yet. "
            "Connect it from *Settings → Slack Integration* in the dashboard.",
        )
        return

    if command == "investigate":
        if not argument:
            await send_slack_notification(
                channel,
                "Usage: `@Sentinel investigate <service or description>` — "
                "e.g. `@Sentinel investigate payment-service latency spike`.",
                tenant_id=tenant_id,
            )
            return
        await _trigger_investigation(tenant_id, channel, argument)

    elif command == "status":
        await _send_status(tenant_id, channel)

    elif command in ("help", ""):
        await send_slack_notification(
            channel,
            "*Sentinel commands:*\n"
            "• `@Sentinel investigate <service>` — start an AI investigation\n"
            "• `@Sentinel status` — summarize open incidents\n"
            "• `@Sentinel help` — show this message",
            tenant_id=tenant_id,
        )

    else:
        await send_slack_notification(
            channel,
            f"Sorry, I don't recognize `{command}`. Try `@Sentinel help`.",
            tenant_id=tenant_id,
        )


async def _trigger_investigation(tenant_id: str, channel: str, description: str):
    """Kick off the normal investigation pipeline from a Slack command."""
    from app.api.alerts import GenericAlert
    from app.worker import process_alert_task
    from app.integrations.slack_bot import send_slack_notification

    alert = GenericAlert(
        source="slack",
        tenant_id=tenant_id,
        title=f"Manual investigation: {description[:200]}",
        description=f"Investigation requested from Slack: {description}",
        severity="medium",
        labels={"requested_via": "slack", "raw_request": description},
        raw_payload={"origin": "slack_mention", "channel": channel},
    )
    process_alert_task.delay(alert.model_dump())

    await send_slack_notification(
        channel,
        f"🔍 On it — starting an investigation for *{description}*. "
        f"I'll post the findings here when the analysis completes.",
        tenant_id=tenant_id,
    )


async def _send_status(tenant_id: str, channel: str):
    """Post a one-line summary of the tenant's open incidents."""
    from app.db.database import async_session
    from sqlalchemy import select, func
    from app.models.incident import Incident, IncidentStatus
    from app.integrations.slack_bot import send_slack_notification

    open_statuses = [
        IncidentStatus.DETECTED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RCA_COMPLETE,
        IncidentStatus.FIX_PROPOSED,
        IncidentStatus.FIX_APPROVED,
        IncidentStatus.FIX_EXECUTING,
        IncidentStatus.FIX_MONITORING,
    ]

    async with async_session() as db:
        open_count = (
            await db.execute(
                select(func.count())
                .select_from(Incident)
                .where(
                    Incident.tenant_id == tenant_id,
                    Incident.status.in_(open_statuses),
                )
            )
        ).scalar_one()

        awaiting = (
            await db.execute(
                select(func.count())
                .select_from(Incident)
                .where(
                    Incident.tenant_id == tenant_id,
                    Incident.status == IncidentStatus.FIX_PROPOSED,
                )
            )
        ).scalar_one()

    if open_count == 0:
        msg = "✅ No open incidents right now — all clear."
    else:
        msg = f"📊 *{open_count}* open incident(s)"
        if awaiting:
            msg += f", *{awaiting}* awaiting your approval"
        msg += "."
    await send_slack_notification(channel, msg, tenant_id=tenant_id)


@router.post("/interactions")
@limiter.limit(SLACK_LIMIT)
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
        user_obj = payload.get("user", {})
        user_id = user_obj.get("id", "")
        user_name = user_obj.get("username") or user_obj.get("name") or "unknown"

        for action in actions:
            action_id = action.get("action_id")
            value = json.loads(action.get("value", "{}"))
            incident_id = value.get("incident_id")

            log.info(
                "🔘 Slack button clicked",
                action=action_id,
                user=user_name,
                user_id=user_id,
                incident_id=incident_id,
            )

            if action_id == "approve_fix":
                await _handle_approve(incident_id, user_id, user_name, payload)
            elif action_id == "reject_fix":
                await _handle_reject(incident_id, user_id, payload)

    return Response(status_code=200)


def is_authorized_approver(approver_ids, slack_user_id: str) -> bool:
    """
    Authorize a Slack approver. Fails CLOSED:

    • If no allow-list is configured (NULL / empty list) → reject everyone.
      Slack workspace membership is NOT an authorization boundary — anyone in
      the channel could press Approve and execute a fix on customer infra.
      Tenants must explicitly configure ``slack_approver_ids``; until then,
      approvals go through the Clerk-authenticated dashboard.
    • If an allow-list IS set → only those Slack user IDs may approve.
    """
    if not approver_ids:  # NULL or [] → fail closed, approve via dashboard
        return False
    if not slack_user_id:
        return False
    return slack_user_id in set(approver_ids)


async def _handle_approve(incident_id: str, user_id: str, user_name: str, payload: dict):
    """Handle fix approval from Slack — authorized, tenant-scoped, fail-closed."""
    from app.db.database import async_session
    from sqlalchemy import select
    from app.models.incident import Incident, IncidentStatus
    from app.models.tenant import Tenant
    from app.worker import execute_fix_task
    from app.integrations.slack_bot import send_slack_notification

    channel = payload.get("channel", {}).get("id", "#incidents")

    async with async_session() as db:
        result = await db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        incident = result.scalar_one_or_none()

        if not incident:
            log.error(f"Incident {incident_id} not found")
            return

        # Authorize the clicker against the incident-owning tenant's allow-list.
        tenant = None
        if incident.tenant_id:
            tenant = (
                await db.execute(select(Tenant).where(Tenant.id == incident.tenant_id))
            ).scalar_one_or_none()

        approver_ids = tenant.slack_approver_ids if tenant else None
        if not is_authorized_approver(approver_ids, user_id):
            log.warning(
                "🚫 Unauthorized Slack approval attempt — denied (fail-closed)",
                incident_id=incident_id,
                user=user_name,
                user_id=user_id,
                tenant_id=incident.tenant_id,
            )
            await send_slack_notification(
                channel,
                f"🚫 <@{user_id or user_name}> is not authorized to approve fixes "
                f"for incident `{incident_id}`. Ask an approved approver, or approve "
                f"from the Sentinel dashboard.",
            )
            return

        if incident.status != IncidentStatus.FIX_PROPOSED:
            log.warning(f"Incident {incident_id} is in {incident.status.value}, cannot approve")
            return

        incident.status = IncidentStatus.FIX_APPROVED
        incident.fix_approval = "manual"
        await db.commit()

    log.info(f"✅ Fix approved by {user_name} ({user_id}) for incident {incident_id}")

    # Trigger fix execution via Celery (approved from Slack by user_id).
    execute_fix_task.delay(incident_id, approval_source="slack", approver_id=user_id)

    await send_slack_notification(
        channel,
        f"✅ *Fix approved* by <@{user_id or user_name}> for incident `{incident_id}`. Executing now...",
    )


async def _handle_reject(incident_id: str, user_id: str, payload: dict):
    """Handle fix rejection from Slack."""
    from app.db.database import async_session
    from sqlalchemy import select
    from app.models.incident import Incident, IncidentStatus

    log.info(f"❌ Fix rejected by {user_id} for incident {incident_id}")

    async with async_session() as db:
        result = await db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        incident = result.scalar_one_or_none()

        if incident and incident.status == IncidentStatus.FIX_PROPOSED:
            incident.status = IncidentStatus.ESCALATED
            await db.commit()
        elif incident:
            log.warning(f"Incident {incident_id} in {incident.status.value} — cannot reject")

    from app.integrations.slack_bot import send_slack_notification
    channel = payload.get("channel", {}).get("id", "#incidents")
    await send_slack_notification(
        channel,
        f"❌ *Fix rejected* by <@{user_id}> for incident `{incident_id}`. Escalated for manual review."
    )
