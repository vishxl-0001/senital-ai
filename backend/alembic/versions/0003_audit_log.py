"""audit_log table (Phase 5, item 16)

Revision ID: 0003_audit_log
Revises: 0002_phase3_tenancy
Create Date: 2026-06-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_audit_log"
down_revision: Union[str, None] = "0002_phase3_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("approval_source", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_target_id"), "audit_log", ["target_id"], unique=False)
    op.create_index(op.f("ix_audit_log_tenant_id"), "audit_log", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_tenant_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_target_id"), table_name="audit_log")
    op.drop_table("audit_log")
