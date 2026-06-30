"""
Sentinel AI — Prometheus Integration
Fetches metrics using PromQL to help the AI diagnose root causes.

Contract: query_prometheus() NEVER fabricates metrics on the default path.
  • {"status": "success", "result": [...]}   real series (possibly empty list)
  • {"status": "no_data", "reason": "..."}    not configured / unreachable / error

Canned sample data is served ONLY for local development, and only when both
APP_ENV=development and PROMETHEUS_ALLOW_MOCK=true (it is logged loudly).
"""

import httpx
import structlog

from app.config import settings

log = structlog.get_logger()


# Dev-only sample series — never used unless explicitly opted in.
_MOCK_SERIES = {
    "cpu": [{"metric": {"__name__": "pod_cpu_usage", "pod": "api-service-abc"}, "value": [0, "0.95"]}],
    "memory": [{"metric": {"__name__": "pod_memory_usage", "pod": "api-service-abc"}, "value": [0, "850000000"]}],
    "error": [{"metric": {"__name__": "http_requests_total", "status": "500"}, "value": [0, "45"]}],
}


def _mock_for(query: str) -> list:
    q = query.lower()
    if "cpu" in q:
        return _MOCK_SERIES["cpu"]
    if "memory" in q:
        return _MOCK_SERIES["memory"]
    if "error" in q or "5xx" in q:
        return _MOCK_SERIES["error"]
    return []


def _mock_enabled() -> bool:
    return settings.APP_ENV == "development" and settings.PROMETHEUS_ALLOW_MOCK


async def query_prometheus(query: str, time_range_minutes: int = 30) -> dict:
    """Execute a PromQL instant query. See module docstring for the return contract."""
    if _mock_enabled():
        log.warning(
            "⚠️ Prometheus MOCK mode — returning fabricated sample metrics (dev only)",
            query=query,
        )
        return {"status": "success", "result": _mock_for(query), "mock": True}

    base_url = settings.PROMETHEUS_URL
    if not base_url:
        log.info("Prometheus not configured — no metrics available", query=query)
        return {"status": "no_data", "reason": "not_configured"}

    log.info("Executing PromQL query", query=query)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/api/v1/query",
                params={"query": query},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("Prometheus query failed", query=query, error=str(e))
        return {"status": "no_data", "reason": "unreachable"}

    if data.get("status") == "success":
        return {"status": "success", "result": data.get("data", {}).get("result", [])}

    log.warning("Prometheus returned non-success status", query=query, prom_status=data.get("status"))
    return {"status": "no_data", "reason": "query_error"}
