"""
Sentinel AI — Main Application
FastAPI entry point with all routes mounted.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

import logging

from app.config import settings
from app.db.database import init_db
from app.api import alerts, incidents, policies, runbooks, health, websockets, auth, agent, monitors, webhooks_vendors
from app.integrations.slack_events import router as slack_router
from app.integrations.slack_oauth import router as slack_oauth_router

# ── Structured Logging ──
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.LOG_LEVEL)  # Convert "INFO" -> 20
    ),
)

log = structlog.get_logger()


# ── App Lifecycle ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    log.info("🛡️ Sentinel AI starting up", env=settings.APP_ENV)
    await init_db()
    log.info("✅ Database initialized")
    yield
    log.info("🛡️ Sentinel AI shutting down")


# ── Create App ──
app = FastAPI(
    title="Sentinel AI",
    description="Autonomous SRE Platform — Detect. Diagnose. Fix.",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Rate limiting (item 17) ──
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from app.rate_limit import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS (allow dashboard to connect) ──
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    # Production Azure domain — required for Slack callbacks and dashboard API calls
    "https://sentinel-ai-vishxl.centralindia.cloudapp.azure.com",
    settings.FRONTEND_BASE_URL,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(CORS_ORIGINS)),  # deduplicate
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Routes ──
app.include_router(health.router, tags=["Health"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(incidents.router, prefix="/api/v1/incidents", tags=["Incidents"])
app.include_router(policies.router, prefix="/api/v1/policies", tags=["Policies"])
app.include_router(runbooks.router, prefix="/api/v1/runbooks", tags=["Runbooks"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])
app.include_router(monitors.router, prefix="/api/v1/monitors", tags=["Monitors"])
app.include_router(webhooks_vendors.router, prefix="/api/v1/webhooks", tags=["Vendor Webhooks"])
app.include_router(slack_router, prefix="/api/v1/slack", tags=["Slack"])
app.include_router(slack_oauth_router, prefix="/api/v1/slack", tags=["Slack"])
app.include_router(websockets.router, tags=["WebSockets"])


@app.get("/")
async def root():
    return {
        "name": "Sentinel AI",
        "version": "0.1.0",
        "status": "operational",
        "description": "Autonomous SRE Platform — Detect. Diagnose. Fix.",
    }
