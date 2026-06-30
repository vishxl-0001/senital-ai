"""baseline schema (matches pre-Alembic production state)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-30

This baseline reflects the schema that init_db() used to create ad-hoc on
startup: five tables (api_keys, incidents, policies, runbooks,
incident_timeline) with a 384-dim pgvector embedding and a nullable tenant_id.

On a FRESH database `alembic upgrade head` creates this, then 0002 applies the
Phase 3 changes. On the EXISTING database (already created by init_db) you run
`alembic stamp 0001_baseline` once, then `alembic upgrade head` to apply 0002.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector must exist before the incidents.rca_embedding column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=500), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_tenant_id"), "api_keys", ["tenant_id"], unique=False)

    op.create_table(
        "incidents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("incident_number", sa.Integer(), autoincrement=True, nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("status", sa.Enum(
            "DETECTED", "INVESTIGATING", "RCA_COMPLETE", "FIX_PROPOSED", "FIX_APPROVED",
            "FIX_EXECUTING", "FIX_MONITORING", "RESOLVED", "FAILED", "ESCALATED",
            name="incidentstatus"), nullable=True),
        sa.Column("severity", sa.Enum(
            "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", name="severity"), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("source_alert_id", sa.String(length=255), nullable=True),
        sa.Column("source_payload", sa.JSON(), nullable=True),
        sa.Column("investigation_summary", sa.Text(), nullable=True),
        sa.Column("logs_collected", sa.JSON(), nullable=True),
        sa.Column("metrics_collected", sa.JSON(), nullable=True),
        sa.Column("deployment_context", sa.JSON(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("rca_evidence", sa.JSON(), nullable=True),
        sa.Column("rca_confidence", sa.Float(), nullable=True),
        sa.Column("rca_embedding", pgvector.sqlalchemy.Vector(dim=384), nullable=True),
        sa.Column("similar_incidents", sa.JSON(), nullable=True),
        sa.Column("fix_plan", sa.JSON(), nullable=True),
        sa.Column("fix_type", sa.String(length=100), nullable=True),
        sa.Column("fix_approval", sa.Enum(
            "AUTO", "MANUAL", "TIMEOUT_AUTO", name="fixapproval"), nullable=True),
        sa.Column("fix_executed_at", sa.DateTime(), nullable=True),
        sa.Column("fix_result", sa.JSON(), nullable=True),
        sa.Column("rollback_plan", sa.JSON(), nullable=True),
        sa.Column("affected_services", sa.JSON(), nullable=True),
        sa.Column("affected_users_estimate", sa.Integer(), nullable=True),
        sa.Column("impact_description", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=True),
        sa.Column("investigation_started_at", sa.DateTime(), nullable=True),
        sa.Column("rca_completed_at", sa.DateTime(), nullable=True),
        sa.Column("fix_started_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("mttr_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incidents_incident_number"), "incidents", ["incident_number"], unique=True)
    op.create_index(op.f("ix_incidents_severity"), "incidents", ["severity"], unique=False)
    op.create_index(op.f("ix_incidents_status"), "incidents", ["status"], unique=False)
    op.create_index(op.f("ix_incidents_tenant_id"), "incidents", ["tenant_id"], unique=False)

    op.create_table(
        "policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("auto_approve", sa.Boolean(), nullable=True),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("approval_timeout_minutes", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_policies_tenant_id"), "policies", ["tenant_id"], unique=False)

    op.create_table(
        "runbooks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_pattern", sa.String(length=500), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("rollback_steps", sa.JSON(), nullable=True),
        sa.Column("success_criteria", sa.JSON(), nullable=True),
        sa.Column("times_used", sa.Integer(), nullable=True),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("avg_fix_time_seconds", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runbooks_tenant_id"), "runbooks", ["tenant_id"], unique=False)

    op.create_table(
        "incident_timeline",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incident_timeline_incident_id"), "incident_timeline", ["incident_id"], unique=False)
    op.create_index(op.f("ix_incident_timeline_tenant_id"), "incident_timeline", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_incident_timeline_tenant_id"), table_name="incident_timeline")
    op.drop_index(op.f("ix_incident_timeline_incident_id"), table_name="incident_timeline")
    op.drop_table("incident_timeline")
    op.drop_index(op.f("ix_runbooks_tenant_id"), table_name="runbooks")
    op.drop_table("runbooks")
    op.drop_index(op.f("ix_policies_tenant_id"), table_name="policies")
    op.drop_table("policies")
    op.drop_index(op.f("ix_incidents_tenant_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_status"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_severity"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_incident_number"), table_name="incidents")
    op.drop_table("incidents")
    op.drop_index(op.f("ix_api_keys_tenant_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_table("api_keys")
