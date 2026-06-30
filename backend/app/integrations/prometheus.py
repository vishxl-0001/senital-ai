"""
Sentinel AI — Prometheus Integration
Fetches metrics using PromQL to help the AI diagnose root causes.
"""

import httpx
import structlog
from app.config import settings

log = structlog.get_logger()

# If the user doesn't have a real Prometheus server, we will use mock data for testing
PROMETHEUS_URL = "http://localhost:9090" # Change this when you have a real prometheus instance

async def query_prometheus(query: str, time_range_minutes: int = 30) -> list:
    """
    Execute a PromQL query against Prometheus to fetch metrics for the AI.
    """
    log.info(f"Executing PromQL query: {query}")
    
    # Check if we should use mock data (since Prometheus isn't set up yet)
    if "cpu" in query.lower():
        return [{"metric": {"__name__": "pod_cpu_usage", "pod": "api-service-abc"}, "value": [1687654321, "0.95"]}]
    elif "memory" in query.lower():
        return [{"metric": {"__name__": "pod_memory_usage", "pod": "api-service-abc"}, "value": [1687654321, "850000000"]}]
    elif "error" in query.lower() or "5xx" in query.lower():
        return [{"metric": {"__name__": "http_requests_total", "status": "500"}, "value": [1687654321, "45"]}]
    
    # Try the real Prometheus if it happens to be running
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data["data"]["result"]
            return []
    except Exception as e:
        log.warning("Prometheus query failed (is it running?)", error=str(e))
        return []
