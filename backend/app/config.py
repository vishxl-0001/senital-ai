"""
Sentinel AI — Configuration
Loads all settings from environment variables.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "change-this-in-production"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:sentinel_dev@localhost:5432/sentinel_ai"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # OpenAI / LLM
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: str | None = None

    # Clerk (dashboard auth)
    # The backend verifies Clerk session JWTs server-side and derives tenant_id
    # from the verified `org_id` claim. ISSUER/JWKS are auto-derived from the
    # publishable key when not set explicitly (the publishable key is public).
    CLERK_PUBLISHABLE_KEY: str | None = None
    CLERK_SECRET_KEY: str | None = None
    CLERK_ISSUER: str | None = None
    CLERK_JWKS_URL: str | None = None

    # Slack
    SLACK_BOT_TOKEN: str | None = None
    SLACK_APP_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None
    # Per-tenant Slack OAuth (item 13) — populated once the Slack App exists.
    SLACK_CLIENT_ID: str | None = None
    SLACK_CLIENT_SECRET: str | None = None

    # Base URL of the dashboard, used to build incident links in Slack messages.
    # Configurable so it isn't hardcoded to localhost in production.
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # GitHub
    GITHUB_PAT: str | None = None
    GITHUB_TOKEN: str | None = None
    GITHUB_ORG: str | None = None

    # Monitoring / Prometheus
    # When PROMETHEUS_URL is unset, metric queries return {"status": "no_data"}
    # instead of fabricated numbers. PROMETHEUS_ALLOW_MOCK serves canned sample
    # series for local development ONLY (and only when APP_ENV=development).
    PROMETHEUS_URL: str | None = None
    PROMETHEUS_ALLOW_MOCK: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars like POSTGRES_USER used by Docker only


settings = Settings()
