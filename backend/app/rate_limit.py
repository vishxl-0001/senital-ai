"""
Rate limiting (Phase 5, item 17).

A single slowapi Limiter shared across routers. The key is per-caller: the
X-API-Key header when present (webhooks / agent poll authenticate with it), else
the client IP (Slack, unauthenticated edges). Limits are configured in settings
and applied per-endpoint via the decorators below.

Disable globally with RATE_LIMIT_ENABLED=false (e.g. in tests).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def _caller_key(request: Request) -> str:
    api_key = request.headers.get("x-api-key")
    if api_key:
        # Don't key on the raw secret; a prefix is enough to bucket per caller.
        return f"key:{api_key[:12]}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_caller_key,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[],
)

# Convenience limit strings, resolved from settings at import time.
WEBHOOK_LIMIT = settings.RATE_LIMIT_WEBHOOK
AGENT_LIMIT = settings.RATE_LIMIT_AGENT
SLACK_LIMIT = settings.RATE_LIMIT_SLACK
