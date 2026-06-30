"""Phase 3: tenants table, non-null tenant_id, per-tenant incident numbering

Revision ID: 0002_phase3_tenancy
Revises: 0001_baseline
Create Date: 2026-06-30

Data-preserving. Existing rows with a NULL tenant_id are assigned to a generated
``legacy`` tenant rather than dropped. incident_number is renumbered per tenant
(sequential by created_at) so absolute numbers no longer leak global volume, and
its uniqueness becomes composite (tenant_id, incident_number).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_phase3_tenancy"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_TENANT_ID = "legacy"
_TENANT_SCOPED = ["incidents", "policies", "runbooks", "incident_timeline"]


def upgrade() -> None:
    # ── 1. tenants table ──
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("slug", sa.String(length=32), nullable=True),
        sa.Column("incident_counter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("slack_approver_ids", sa.JSON(), nullable=True),
        sa.Column("slack_team_id", sa.String(length=64), nullable=True),
        sa.Column("slack_channel_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_slack_team_id"), "tenants", ["slack_team_id"], unique=False)
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)

    conn = op.get_bind()

    # ── 2. Backfill NULL tenant_id -> legacy tenant (no data loss) ──
    has_null = False
    for table in _TENANT_SCOPED:
        n = conn.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")
        ).scalar()
        if n:
            has_null = True

    # Provision a Tenant row for every distinct tenant_id already in use, plus
    # the legacy tenant if any NULLs exist.
    existing_ids = set()
    for table in _TENANT_SCOPED:
        rows = conn.execute(
            sa.text(f"SELECT DISTINCT tenant_id FROM {table} WHERE tenant_id IS NOT NULL")
        ).scalars().all()
        existing_ids.update(rows)
    if has_null:
        existing_ids.add(LEGACY_TENANT_ID)

    for tid in existing_ids:
        name = "Legacy (pre-tenant data)" if tid == LEGACY_TENANT_ID else None
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, name, incident_counter, created_at, updated_at) "
                "VALUES (:id, :name, 0, now(), now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": tid, "name": name},
        )

    if has_null:
        for table in _TENANT_SCOPED:
            conn.execute(
                sa.text(f"UPDATE {table} SET tenant_id = :legacy WHERE tenant_id IS NULL"),
                {"legacy": LEGACY_TENANT_ID},
            )

    # ── 3. tenant_id NOT NULL on all tenant-scoped tables ──
    for table in _TENANT_SCOPED:
        op.alter_column(table, "tenant_id", existing_type=sa.String(length=255), nullable=False)

    # ── 4. Per-tenant incident_number ──
    # Renumber existing incidents sequentially within each tenant, ordered by
    # creation time (fallback to id for stable ordering of NULL created_at).
    op.drop_index(op.f("ix_incidents_incident_number"), table_name="incidents")
    conn.execute(sa.text(
        """
        WITH numbered AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY tenant_id
                       ORDER BY created_at NULLS FIRST, id
                   ) AS rn
            FROM incidents
        )
        UPDATE incidents i
        SET incident_number = numbered.rn
        FROM numbered
        WHERE i.id = numbered.id
        """
    ))
    # Seed each tenant's counter to its current max incident_number.
    conn.execute(sa.text(
        """
        UPDATE tenants t
        SET incident_counter = COALESCE(m.max_num, 0)
        FROM (
            SELECT tenant_id, max(incident_number) AS max_num
            FROM incidents GROUP BY tenant_id
        ) m
        WHERE t.id = m.tenant_id
        """
    ))
    # incident_number is required going forward, unique per tenant.
    op.alter_column("incidents", "incident_number",
                    existing_type=sa.Integer(), nullable=False, autoincrement=False)
    op.create_index(op.f("ix_incidents_incident_number"), "incidents", ["incident_number"], unique=False)
    op.create_unique_constraint(
        "uq_incidents_tenant_number", "incidents", ["tenant_id", "incident_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_incidents_tenant_number", "incidents", type_="unique")
    op.drop_index(op.f("ix_incidents_incident_number"), table_name="incidents")
    op.alter_column("incidents", "incident_number",
                    existing_type=sa.Integer(), nullable=True, autoincrement=True)
    op.create_index(op.f("ix_incidents_incident_number"), "incidents", ["incident_number"], unique=True)

    for table in _TENANT_SCOPED:
        op.alter_column(table, "tenant_id", existing_type=sa.String(length=255), nullable=True)

    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_slack_team_id"), table_name="tenants")
    op.drop_table("tenants")
