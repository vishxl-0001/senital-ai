"""
Sentinel AI — Per-tenant incident numbering (Phase 3, item 11).

incident_number is sequential within a tenant (ACME-1, ACME-2, ...), so a
customer can't infer the platform's global incident volume from their numbers.

allocate_incident_number() atomically bumps the tenant's counter under a row
lock and returns the new value, creating the Tenant row on first use. It must be
called inside the same transaction/session that inserts the incident so the
allocation and the insert commit together.
"""

import structlog
from sqlalchemy import text

log = structlog.get_logger()


async def allocate_incident_number(db, tenant_id: str) -> int:
    """
    Reserve and return the next incident_number for ``tenant_id``.

    Uses an atomic ``UPDATE ... RETURNING`` (row-locked by Postgres) so
    concurrent alert workers never get the same number. Ensures a Tenant row
    exists first (idempotent insert).
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to allocate an incident number")

    # Ensure the tenant row exists (id == Clerk org_id). Idempotent.
    await db.execute(
        text(
            "INSERT INTO tenants (id, incident_counter, created_at, updated_at) "
            "VALUES (:tid, 0, now(), now()) ON CONFLICT (id) DO NOTHING"
        ),
        {"tid": tenant_id},
    )

    # Atomically increment and return the new value. The UPDATE takes a row lock,
    # serializing concurrent allocations for the same tenant.
    result = await db.execute(
        text(
            "UPDATE tenants SET incident_counter = incident_counter + 1, "
            "updated_at = now() WHERE id = :tid RETURNING incident_counter"
        ),
        {"tid": tenant_id},
    )
    number = result.scalar_one()
    return int(number)


async def get_tenant_slug(db, tenant_id: str) -> str | None:
    """Return the tenant's slug (used to render ACME-1042), or None."""
    row = await db.execute(
        text("SELECT slug FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    )
    return row.scalar_one_or_none()


def format_reference(slug: str | None, tenant_id: str, number: int | None) -> str | None:
    """Human reference like 'ACME-1042'. Falls back to a short tenant prefix."""
    if number is None:
        return None
    prefix = (slug or (tenant_id[:6].upper() if tenant_id else "INC"))
    return f"{prefix}-{number}"
