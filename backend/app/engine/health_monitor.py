"""
Sentinel AI — Health Monitor
Watches metrics after a fix is executed to verify it worked.
Auto-triggers rollback if health degrades.
"""

import asyncio
import structlog
from datetime import datetime

log = structlog.get_logger()

# Default monitoring settings
DEFAULT_MONITOR_DURATION_SECONDS = 120  # 2 minutes
DEFAULT_CHECK_INTERVAL_SECONDS = 15    # Check every 15 seconds
MAX_FAILURES_BEFORE_ROLLBACK = 2       # Rollback after 2 consecutive failures


async def monitor_health_post_fix(
    fix_plan: dict,
    incident_id: str,
    duration_seconds: int = DEFAULT_MONITOR_DURATION_SECONDS,
) -> dict:
    """
    Monitor health after a fix is executed.
    
    Runs health checks defined in the fix plan for a specified duration.
    If health degrades, returns rollback recommendation.
    
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

    log.info(
        "🏥 Starting post-fix health monitoring",
        incident_id=incident_id,
        duration_seconds=duration_seconds,
        checks_count=len(health_checks),
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
            check_name = check.get("check", "Unknown check")
            wait_seconds = check.get("wait_seconds", 0)

            # Wait before first check if specified
            if elapsed == 0 and wait_seconds > 0:
                log.info(f"  ⏳ Waiting {wait_seconds}s before first check...")
                await asyncio.sleep(wait_seconds)

            # Run the health check (simulation for now)
            result = await _run_health_check(check)
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

        # Check if we need to rollback
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

        # Wait before next round
        await asyncio.sleep(DEFAULT_CHECK_INTERVAL_SECONDS)
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


async def _run_health_check(check: dict) -> dict:
    """
    Run a single health check.
    
    In production, this will:
    - Query Prometheus for metrics
    - Check K8s pod status
    - Verify HTTP endpoint responses
    
    For now, simulates a passing check.
    """
    check_name = check.get("check", "Unknown")
    success_criteria = check.get("success_criteria", "")
    command = check.get("command", "")

    # TODO: Replace with real checks:
    # - Parse `command` field to run kubectl/promql queries
    # - Compare results against `success_criteria`

    log.info(f"  🔍 Health check: {check_name}", command=command)

    # Simulation: checks always pass for now
    return {
        "check": check_name,
        "command": command,
        "passed": True,
        "output": f"[SIMULATION] {success_criteria}",
    }
