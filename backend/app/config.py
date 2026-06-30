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

    # Slack
    SLACK_BOT_TOKEN: str | None = None
    SLACK_APP_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None

    # GitHub
    GITHUB_PAT: str | None = None
    GITHUB_TOKEN: str | None = None
    GITHUB_ORG: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars like POSTGRES_USER used by Docker only


settings = Settings()
