"""
Sentinel AI — Uptime Monitors API
CRUD for external-mode uptime monitors (checked by the Celery uptime tasks).
"""

from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.database import get_db
from app.models.monitor import UptimeMonitor, MonitorStatus
from app.auth.clerk import get_current_tenant

router = APIRouter()

MAX_MONITORS_PER_TENANT = 50

# Cheap SSRF mitigation: the checker runs inside the compose network next to
# Postgres/Redis, so refuse obvious internal targets (literal private IPs and
# local hostnames). Full DNS-rebinding protection (resolve + verify at request
# time) is future work.
_BLOCKED_HOSTNAMES = {"localhost", "postgres", "redis", "backend", "dashboard"}


def _validate_url(v: str) -> str:
    import ipaddress

    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL must be http(s):// with a hostname")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTNAMES or "." not in host:
        raise ValueError("URL points to an internal/private address")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return v  # a regular hostname
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        raise ValueError("URL points to an internal/private address")
    return v


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=2000)
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    expected_status_codes: list[int] = Field(default=[200])
    keyword: Optional[str] = Field(default=None, max_length=500)
    latency_threshold_ms: Optional[int] = Field(default=None, ge=1)
    ssl_check_enabled: bool = True
    ssl_warn_days: int = Field(default=14, ge=1, le=90)
    failure_threshold: int = Field(default=2, ge=1, le=10)

    @field_validator("url")
    @classmethod
    def _url_http_only(cls, v: str) -> str:
        return _validate_url(v)


class MonitorUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    url: Optional[str] = Field(default=None, max_length=2000)
    interval_seconds: Optional[int] = Field(default=None, ge=30, le=3600)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=60)
    expected_status_codes: Optional[list[int]] = None
    keyword: Optional[str] = Field(default=None, max_length=500)
    latency_threshold_ms: Optional[int] = Field(default=None, ge=1)
    ssl_check_enabled: Optional[bool] = None
    ssl_warn_days: Optional[int] = Field(default=None, ge=1, le=90)
    failure_threshold: Optional[int] = Field(default=None, ge=1, le=10)

    @field_validator("url")
    @classmethod
    def _url_http_only(cls, v: Optional[str]) -> Optional[str]:
        return _validate_url(v) if v is not None else v


def _serialize(m: UptimeMonitor) -> dict:
    return {
        "id": str(m.id),
        "name": m.name,
        "url": m.url,
        "interval_seconds": m.interval_seconds,
        "timeout_seconds": m.timeout_seconds,
        "expected_status_codes": m.expected_status_codes,
        "keyword": m.keyword,
        "latency_threshold_ms": m.latency_threshold_ms,
        "ssl_check_enabled": m.ssl_check_enabled,
        "ssl_warn_days": m.ssl_warn_days,
        "failure_threshold": m.failure_threshold,
        "is_active": m.is_active,
        "status": m.status.value if m.status else None,
        "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
        "last_response_ms": m.last_response_ms,
        "last_status_code": m.last_status_code,
        "last_error": m.last_error,
        "consecutive_failures": m.consecutive_failures,
        "ssl_expires_at": m.ssl_expires_at.isoformat() if m.ssl_expires_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _get_owned_monitor(db: AsyncSession, tenant_id: str, monitor_id: UUID) -> UptimeMonitor:
    result = await db.execute(
        select(UptimeMonitor).where(
            UptimeMonitor.id == monitor_id,
            UptimeMonitor.tenant_id == tenant_id,
        )
    )
    monitor = result.scalar_one_or_none()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


@router.get("")
async def list_monitors(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all monitors for the caller's tenant."""
    result = await db.execute(
        select(UptimeMonitor)
        .where(UptimeMonitor.tenant_id == tenant_id)
        .order_by(desc(UptimeMonitor.created_at))
    )
    return {"monitors": [_serialize(m) for m in result.scalars().all()]}


@router.post("", status_code=201)
async def create_monitor(
    payload: MonitorCreate,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a monitor; the next beat sweep (≤30s) starts checking it."""
    count = (
        await db.execute(
            select(func.count())
            .select_from(UptimeMonitor)
            .where(UptimeMonitor.tenant_id == tenant_id)
        )
    ).scalar_one()
    if count >= MAX_MONITORS_PER_TENANT:
        raise HTTPException(
            status_code=400,
            detail=f"Monitor limit reached ({MAX_MONITORS_PER_TENANT} per organization)",
        )

    monitor = UptimeMonitor(tenant_id=tenant_id, **payload.model_dump())
    db.add(monitor)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A monitor for this URL already exists")
    await db.refresh(monitor)
    return _serialize(monitor)


@router.get("/{monitor_id}")
async def get_monitor(
    monitor_id: UUID,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    monitor = await _get_owned_monitor(db, tenant_id, monitor_id)
    return _serialize(monitor)


@router.patch("/{monitor_id}")
async def update_monitor(
    monitor_id: UUID,
    payload: MonitorUpdate,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    monitor = await _get_owned_monitor(db, tenant_id, monitor_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(monitor, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A monitor for this URL already exists")
    await db.refresh(monitor)
    return _serialize(monitor)


@router.delete("/{monitor_id}", status_code=204)
async def delete_monitor(
    monitor_id: UUID,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    monitor = await _get_owned_monitor(db, tenant_id, monitor_id)
    await db.delete(monitor)
    await db.commit()


@router.post("/{monitor_id}/pause")
async def pause_monitor(
    monitor_id: UUID,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    monitor = await _get_owned_monitor(db, tenant_id, monitor_id)
    monitor.is_active = False
    monitor.status = MonitorStatus.PAUSED
    await db.commit()
    await db.refresh(monitor)
    return _serialize(monitor)


@router.post("/{monitor_id}/resume")
async def resume_monitor(
    monitor_id: UUID,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    monitor = await _get_owned_monitor(db, tenant_id, monitor_id)
    monitor.is_active = True
    monitor.status = MonitorStatus.PENDING
    monitor.consecutive_failures = 0
    monitor.last_checked_at = None  # picked up by the next sweep
    await db.commit()
    await db.refresh(monitor)
    return _serialize(monitor)
