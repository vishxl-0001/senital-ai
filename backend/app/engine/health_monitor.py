"""
Sentinel AI — Health Monitor
Watches the cluster after a fix is executed to verify it worked.
Auto-triggers rollback if health degrades.

Real checks (in priority order):
  1. Kubernetes pod state — phase Running, all containers Ready, restart count
     within bounds, no CrashLoopBackOff/Error/ImagePull waiting reasons.
  2. Prometheus numeric threshold — when a check carries a `promql` expression.
  3. Simulated fallback — ONLY when neither K8s nor Prometheus is reachable. It
     is logged loudly and flagged `simulated: True`; it never silently fakes a
     real verification.
"""

import asyncio
import structlog
from datetime import datetime

from app.config import settings
from app.engine.executor import _get_k8s_clients
from app.engine.k8s_actions import extract_namespace, extract_resource
from app.integrations.prometheus import query_prometheus

log = structlog.get_logger()

# Default monitoring settings
DEFAULT_MONITOR_DURATION_SECONDS = 120  # 2 minutes
DEFAULT_CHECK_INTERVAL_SECONDS = 15     # Check every 15 seconds
MAX_FAILURES_BEFORE_ROLLBACK = 2        # Rollback after 2 consecutive failures
DEFAULT_MAX_RESTARTS = 5                # Restarts above this = unhealthy

_BAD_WAITING_REASONS = {
    "CrashLoopBackOff", "Error", "ImagePullBackOff",
    "ErrImagePull", "RunContainerError", "CreateContainerError",
}


async def monitor_health_post_fix(
    fix_plan: dict,
    incident_id: str,
    duration_seconds: int = DEFAULT_MONITOR_DURATION_SECONDS,
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS,
    k8s_clients=None,
) -> dict:
    """
    Monitor health after a fix is executed.

    `k8s_clients` (a `(CoreV1Api, AppsV1Api)` tuple) can be injected for tests;
    otherwise it is loaded via the same path executor.py uses.

    Returns:
        {
            "status": "healthy" | "degraded" | "rollback_needed",
            "checks_passed": int,
            "checks_failed": int,
            "results": [...],
        }
    """
    health_checks = fix_plan.get("health_checks", [])

    if not health_checks:
        log.info("⏭️ No health checks defined — skipping monitoring", incident_id=incident_id)
        return {"status": "healthy", "checks_passed": 0, "checks_failed": 0, "results": []}

    v1, _apps_v1 = k8s_clients if k8s_clients is not None else _get_k8s_clients()

    log.info(
        "🏥 Starting post-fix health monitoring",
        incident_id=incident_id,
        duration_seconds=duration_seconds,
        checks_count=len(health_checks),
        k8s_available=v1 is not None,
    )

    results = []
    checks_passed = 0
    checks_failed = 0
    consecutive_failures = 0
    start_time = datetime.utcnow()
    elapsed = 0

    while elapsed < duration_seconds:
        check_round = []

        for check in health_checks:
            wait_seconds = check.get("wait_seconds", 0)
            if elapsed == 0 and wait_seconds > 0:
                log.info(f"  ⏳ Waiting {wait_seconds}s before first check...")
                await asyncio.sleep(wait_seconds)

            result = await _run_health_check(check, v1, fix_plan)
            check_round.append(result)

            if result["passed"]:
                checks_passed += 1
                consecutive_failures = 0
            else:
                checks_failed += 1
                consecutive_failures += 1

        results.append({
            "timestamp": datetime.utcnow().isoformat(),
            "elapsed_seconds": elapsed,
            "checks": check_round,
        })

        if consecutive_failures >= MAX_FAILURES_BEFORE_ROLLBACK:
            log.error(
                "🔴 Health degraded — recommending rollback!",
                incident_id=incident_id,
                consecutive_failures=consecutive_failures,
            )
            return {
                "status": "rollback_needed",
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
                "results": results,
                "reason": f"{consecutive_failures} consecutive health check failures",
            }

        await asyncio.sleep(check_interval_seconds)
        elapsed = (datetime.utcnow() - start_time).seconds

    status = "healthy" if checks_failed == 0 else "degraded"
    log.info(
        f"🏥 Health monitoring complete — {status}",
        incident_id=incident_id,
        passed=checks_passed,
        failed=checks_failed,
    )

    return {
        "status": status,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "results": results,
    }


def _resolve_target(check: dict, fix_plan: dict):
    """Figure out which pod(s)/namespace this check applies to."""
    ns = check.get("namespace") or fix_plan.get("namespace")
    label_selector = check.get("label_selector")
    resource = check.get("pod") or check.get("deployment") or check.get("resource")

    cmd = check.get("command", "") or " ".join(
        s.get("command", "") for s in fix_plan.get("steps", []) or []
    )
    if not ns:
        ns = extract_namespace(cmd) or "default"
    if not resource and not label_selector:
        resource = extract_resource(cmd) or fix_plan.get("resource") or fix_plan.get("target")
    return ns or "default", resource, label_selector


def _evaluate_pods(pods, max_restarts: int):
    """Return (healthy, details). A pod is healthy iff Running + all containers
    ready + restarts within bound + no bad waiting reason."""
    if not pods:
        return False, {"error": "no pods found for target"}

    details = []
    healthy = True
    for pod in pods:
        name = getattr(getattr(pod, "metadata", None), "name", "?")
        phase = getattr(getattr(pod, "status", None), "phase", None)
        container_statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []

        ready = all(getattr(cs, "ready", False) for cs in container_statuses) if container_statuses else False
        restarts = sum(getattr(cs, "restart_count", 0) or 0 for cs in container_statuses)

        waiting = []
        for cs in container_statuses:
            state = getattr(cs, "state", None)
            w = getattr(state, "waiting", None) if state else None
            reason = getattr(w, "reason", None) if w else None
            if reason:
                waiting.append(reason)

        bad = any(r in _BAD_WAITING_REASONS for r in waiting)
        pod_ok = (phase == "Running") and ready and (restarts <= max_restarts) and not bad
        healthy = healthy and pod_ok
        details.append({
            "pod": name, "phase": phase, "ready": ready,
            "restarts": restarts, "waiting": waiting, "ok": pod_ok,
        })

    return healthy, {"pods": details}


async def _run_health_check(check: dict, v1, fix_plan: dict) -> dict:
    """Run a single health check against the live cluster (or Prometheus)."""
    name = check.get("check", "health-check")
    max_restarts = int(check.get("max_restarts", DEFAULT_MAX_RESTARTS))
    ns, resource, label_selector = _resolve_target(check, fix_plan)

    # 1) Real Kubernetes pod-state check
    if v1 is not None and (resource or label_selector):
        try:
            loop = asyncio.get_event_loop()
            if label_selector:
                resp = await loop.run_in_executor(
                    None, lambda: v1.list_namespaced_pod(ns, label_selector=label_selector)
                )
                pods = getattr(resp, "items", []) or []
            else:
                pod = await loop.run_in_executor(None, v1.read_namespaced_pod, resource, ns)
                pods = [pod]
            healthy, detail = _evaluate_pods(pods, max_restarts)
            log.info(
                f"  🔍 K8s health check: {name}",
                namespace=ns, target=resource or label_selector, healthy=healthy,
            )
            return {"check": name, "passed": healthy, "simulated": False, "output": detail}
        except Exception as e:
            log.warning(f"  ⚠️ K8s health check error for '{name}' — treating as failed", error=str(e))
            return {"check": name, "passed": False, "simulated": False, "output": f"K8s check error: {e}"}

    # 2) Real Prometheus numeric-threshold check
    promql = check.get("promql")
    prom_enabled = bool(settings.PROMETHEUS_URL) or (
        settings.APP_ENV == "development" and settings.PROMETHEUS_ALLOW_MOCK
    )
    if promql and prom_enabled:
        prom = await query_prometheus(promql)
        if prom.get("status") == "success" and prom.get("result"):
            passed = _evaluate_promql(prom["result"], check)
            log.info(f"  🔍 Prometheus health check: {name}", passed=passed)
            return {"check": name, "passed": passed, "simulated": False, "output": {"prom": prom["result"]}}
        log.warning(f"  ⚠️ Prometheus no_data for health check '{name}' — cannot verify", reason=prom.get("reason"))
        return {"check": name, "passed": False, "simulated": False, "output": "Prometheus no_data — could not verify"}

    # 3) Simulated fallback — neither K8s nor Prometheus reachable. Logged loudly.
    log.warning(
        f"  🧪 SIMULATED health check '{name}' — NOT a real verification "
        "(no K8s/Prometheus available)",
        target=resource or label_selector,
    )
    return {
        "check": name,
        "passed": True,
        "simulated": True,
        "output": f"[SIMULATED] {check.get('success_criteria', '')}",
    }


def _evaluate_promql(result, check: dict) -> bool:
    """Compare the first scalar value to a threshold. Defaults to 'less-than'."""
    try:
        value = float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return False
    threshold = check.get("threshold")
    if threshold is None:
        # No threshold given: presence of data alone isn't 'healthy' or not — be
        # conservative and treat as failing so we don't auto-pass on noise.
        return False
    comparison = (check.get("comparison") or "lt").lower()
    threshold = float(threshold)
    if comparison in ("lt", "less_than", "<"):
        return value < threshold
    if comparison in ("le", "<="):
        return value <= threshold
    if comparison in ("gt", "greater_than", ">"):
        return value > threshold
    if comparison in ("ge", ">="):
        return value >= threshold
    return False
