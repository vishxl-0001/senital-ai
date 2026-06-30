"""
Sentinel AI — Slack Bot Integration
Real Slack bot using slack_bolt — sends messages, handles button clicks.
"""

import json
import structlog
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from app.config import settings

log = structlog.get_logger()

# ── Slack Client ──
_client = None


def get_slack_client() -> AsyncWebClient:
    """Get or create the Slack client singleton."""
    global _client
    if _client is None and settings.SLACK_BOT_TOKEN:
        _client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    return _client


# ── Build Slack Block Messages ──

def build_incident_blocks(incident_data: dict, is_resolved: bool = False) -> list:
    """Build rich Slack blocks for an incident notification."""
    rca = incident_data.get("rca", {})
    fix_plan = incident_data.get("fix_plan", {})
    incident_id = incident_data.get("id", "")
    severity = incident_data.get("severity", "unknown").upper()
    confidence = rca.get("confidence", 0)
    confidence_pct = int(confidence * 100) if isinstance(confidence, float) else confidence

    # Severity emoji
    sev_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{'✅ Incident Resolved' if is_resolved else '🚨 New Incident Detected'}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Alert:*\n{incident_data.get('title', 'Unknown')}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{sev_emoji} {severity}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🔬 Root Cause:*\n{rca.get('root_cause', 'Investigating...')}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence_pct}%"},
                {"type": "mrkdwn", "text": f"*Category:*\n{rca.get('root_cause_category', 'Unknown')}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🔧 Proposed Fix:*\n{fix_plan.get('fix_summary', 'No fix plan generated')}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Fix Type:*\n`{fix_plan.get('fix_type', 'Unknown')}`"},
                {"type": "mrkdwn", "text": f"*Risk Level:*\n{fix_plan.get('risk_level', 'Unknown')}"},
            ],
        },
    ]

    # Add approval buttons only if not resolved
    if not is_resolved:
        blocks.append(
            {
                "type": "actions",
                "block_id": f"fix_actions_{incident_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve Fix"},
                        "style": "primary",
                        "action_id": "approve_fix",
                        "value": json.dumps({"incident_id": incident_id}),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "style": "danger",
                        "action_id": "reject_fix",
                        "value": json.dumps({"incident_id": incident_id}),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📋 View Details"},
                        "action_id": "view_details",
                        "url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/incidents/{incident_id}",
                    },
                ],
            }
        )
    else:
        # Show resolution context
        fix_result = incident_data.get("fix_result", {})
        duration = fix_result.get("duration_seconds", "N/A")
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"⚡ Auto-resolved in {duration}s | Fix: `{fix_plan.get('fix_type', 'N/A')}`",
                    }
                ],
            }
        )

    return blocks


# ── Send Messages ──

async def send_incident_to_slack(
    incident_data: dict,
    channel: str = "#incidents",
    is_resolved: bool = False,
) -> dict:
    """
    Send a formatted incident report to Slack.
    Falls back to logging if Slack is not configured.
    """
    blocks = build_incident_blocks(incident_data, is_resolved=is_resolved)
    client = get_slack_client()

    if not client:
        # No Slack token configured — log the message instead
        log.warning(
            "📨 Slack not configured — message logged only",
            channel=channel,
            incident_id=incident_data.get("id"),
            title=incident_data.get("title"),
        )
        return {"ok": False, "reason": "slack_not_configured", "blocks": blocks}

    try:
        fallback_text = f"{'✅ Resolved' if is_resolved else '🚨 Incident'}: {incident_data.get('title', 'Unknown')}"
        response = await client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=fallback_text,  # Fallback for notifications
        )
        log.info(
            "📨 Slack message sent",
            channel=channel,
            ts=response.get("ts"),
            incident_id=incident_data.get("id"),
        )
        return {"ok": True, "ts": response.get("ts"), "channel": response.get("channel")}

    except SlackApiError as e:
        log.error("❌ Slack API error", error=str(e), channel=channel)
        return {"ok": False, "error": str(e)}


async def update_slack_message(channel: str, ts: str, incident_data: dict, is_resolved: bool = True):
    """Update an existing Slack message (e.g., after a fix is approved/executed)."""
    client = get_slack_client()
    if not client:
        return

    blocks = build_incident_blocks(incident_data, is_resolved=is_resolved)

    try:
        await client.chat_update(
            channel=channel,
            ts=ts,
            blocks=blocks,
            text=f"✅ Resolved: {incident_data.get('title', 'Unknown')}",
        )
    except SlackApiError as e:
        log.error("❌ Failed to update Slack message", error=str(e))


async def send_slack_notification(channel: str, text: str):
    """Send a simple text message to Slack."""
    client = get_slack_client()
    if not client:
        log.info(f"📨 [Slack not configured] {text}")
        return

    try:
        await client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as e:
        log.error("❌ Slack notification failed", error=str(e))
