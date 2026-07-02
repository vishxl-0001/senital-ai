"""per-tenant encrypted Slack bot token (Phase 4, item 13)

Revision ID: 0004_slack_bot_token
Revises: 0003_audit_log
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_slack_bot_token"
down_revision: Union[str, None] = "0003_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("slack_bot_token", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "slack_bot_token")
