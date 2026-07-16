"""uptime monitors for external-mode URL checks

Revision ID: 0005_uptime_monitors
Revises: 0004_slack_bot_token
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_uptime_monitors"
down_revision: Union[str, None] = "0004_slack_bot_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "uptime_monitors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("expected_status_codes", sa.JSON(), nullable=False, server_default="[200]"),
        sa.Column("keyword", sa.String(length=500), nullable=True),
        sa.Column("latency_threshold_ms", sa.Integer(), nullable=True),
        sa.Column("ssl_check_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ssl_warn_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("failure_threshold", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "status",
            sa.Enum("PENDING", "UP", "DOWN", "PAUSED", name="monitorstatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_response_ms", sa.Integer(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ssl_expires_at", sa.DateTime(), nullable=True),
        sa.Column("ssl_last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("ssl_alerted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "url", name="uq_monitors_tenant_url"),
    )
    op.create_index(op.f("ix_uptime_monitors_tenant_id"), "uptime_monitors", ["tenant_id"])
    op.create_index(op.f("ix_uptime_monitors_status"), "uptime_monitors", ["status"])
    op.create_index(op.f("ix_uptime_monitors_last_checked_at"), "uptime_monitors", ["last_checked_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_uptime_monitors_last_checked_at"), table_name="uptime_monitors")
    op.drop_index(op.f("ix_uptime_monitors_status"), table_name="uptime_monitors")
    op.drop_index(op.f("ix_uptime_monitors_tenant_id"), table_name="uptime_monitors")
    op.drop_table("uptime_monitors")
    sa.Enum(name="monitorstatus").drop(op.get_bind(), checkfirst=True)
