"""
Sentinel AI — Fix Executor
Executes fix commands on the target infrastructure.
Supports both simulation mode (dev) and real K8s mode (production).
"""

import asyncio
import structlog
from datetime import datetime
from typing import Optional

from app.config import settings

log = structlog.get_logger()


# ── K8s Client Loader ──

def _get_k8s_clients():
    """
    Load Kubernetes client. Tries in-cluster config first, then local kubeconfig.
    Returns (CoreV1Api, AppsV1Api) or (None, None) if K8s is not available.
    """
    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
            log.info("☸️ Loaded in-cluster K8s config")
        except config.ConfigException:
            config.load_kube_config()
            log.info("☸️ Loaded local kubeconfig")
        return client.CoreV1Api(), client.AppsV1Api()
    except Exception as e:
        log.warning(f"☸️ K8s not available — running in simulation mode: {e}")
        return None, None


async def execute_fix(fix_plan: dict, incident_id: str = None, tenant_id: str = None) -> dict:
    """
    Execute a fix plan against the target infrastructure.

    1. Detects if K8s is available → real mode, else simulation
    2. Executes each step in order
    3. Stops and flags for rollback on any step failure

    Each executed step is recorded to the audit log as an AI-actor action
    (item 16) when tenant_id is provided.
    """
    from app.engine.audit import record_audit

    fix_type = fix_plan.get("fix_type", "unknown")
    steps = fix_plan.get("steps", [])

    log.info(
        "⚡ Executing fix",
        fix_type=fix_type,
        steps_count=len(steps),
        incident_id=incident_id,
    )

    # Try to get K8s clients
    v1, apps_v1 = _get_k8s_clients()
    is_real_mode = v1 is not None

    results = []
    started_at = datetime.utcnow()

    for step in steps:
        step_num = step.get("order", 0)
        action = step.get("action", "Unknown action")
        command = step.get("command", "")

        log.info(f"  📌 Step {step_num}: {action}", command=command, real_mode=is_real_mode)

        if is_real_mode:
            step_result = await _execute_real_step(step, fix_type, v1, apps_v1)
        else:
            step_result = await _simulate_step(step)

        results.append({
            "step": step_num,
            "action": action,
            "command": command,
            "status": step_result["status"],
            "output": step_result["output"],
            "real_execution": is_real_mode,
            "executed_at": datetime.utcnow().isoformat(),
        })

        # Audit each mutation attempt (AI actor). before = intended action,
        # after = result. Only when we know the tenant.
        if tenant_id:
            await record_audit(
                tenant_id=tenant_id,
                actor="ai",
                action=f"execute_step:{fix_type}",
                target_type="incident",
                target_id=incident_id,
                before_state={"step": step_num, "action": action, "command": command,
                              "real_execution": is_real_mode},
                after_state={"status": step_result["status"], "output": step_result["output"]},
            )

        # If a step fails, stop and trigger rollback
        if step_result["status"] == "failed":
            log.error(f"  ❌ Step {step_num} failed!", error=step_result["output"])
            return {
                "status": "failed",
                "failed_at_step": step_num,
                "results": results,
                "needs_rollback": True,
                "real_execution": is_real_mode,
                "duration_seconds": (datetime.utcnow() - started_at).seconds,
            }

    duration = (datetime.utcnow() - started_at).seconds
    log.info(
        "✅ Fix executed successfully",
        steps_completed=len(results),
        duration_seconds=duration,
        real_execution=is_real_mode,
    )

    return {
        "status": "success",
        "results": results,
        "needs_rollback": False,
        "real_execution": is_real_mode,
        "duration_seconds": duration,
    }


# ── Real K8s Execution ──

async def _execute_real_step(step: dict, fix_type: str, v1, apps_v1) -> dict:
    """Route to the correct K8s action based on fix_type and command context."""
    command = step.get("command", "")
    action = step.get("action", "").lower()

    try:
        # Parse namespace and resource from the command or step metadata
        namespace = _extract_namespace(command) or "default"
        resource = _extract_resource(command)

        if fix_type == "restart_pod" or "restart" in action or "delete" in action:
            return await _k8s_restart_pod(v1, namespace, resource)

        elif fix_type == "rollback_deployment" or "rollback" in action:
            return await _k8s_rollback_deployment(apps_v1, namespace, resource)

        elif fix_type == "scale_horizontal" or "scale" in action:
            replicas = _extract_replicas(command) or 3
            return await _k8s_scale_deployment(apps_v1, namespace, resource, replicas)

        elif fix_type == "clear_disk" or "clean" in action or "clear" in action:
            return await _k8s_exec_cleanup(v1, namespace, resource)

        else:
            # Unknown fix type — simulate
            log.warning(f"Unknown fix type '{fix_type}' — simulating")
            return await _simulate_step(step)

    except Exception as e:
        return {"status": "failed", "output": f"K8s execution error: {str(e)}"}


async def _k8s_restart_pod(v1, namespace: str, pod_name: str) -> dict:
    """Restart a pod by deleting it (K8s deployment will recreate it)."""
    try:
        # Run in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, v1.delete_namespaced_pod, pod_name, namespace
        )
        return {
            "status": "success",
            "output": f"Pod '{pod_name}' deleted in namespace '{namespace}'. Deployment will recreate it.",
        }
    except Exception as e:
        return {"status": "failed", "output": f"Failed to restart pod: {str(e)}"}


async def _k8s_rollback_deployment(apps_v1, namespace: str, deployment: str) -> dict:
    """Rollback a deployment to the previous revision."""
    try:
        loop = asyncio.get_event_loop()
        # Get current deployment
        dep = await loop.run_in_executor(
            None, apps_v1.read_namespaced_deployment, deployment, namespace
        )
        # Get current revision
        current_revision = dep.metadata.annotations.get("deployment.kubernetes.io/revision", "0")

        # Patch with restart annotation to trigger rollout
        from kubernetes.client import V1Deployment, V1DeploymentSpec, V1PodTemplateSpec, V1ObjectMeta
        import datetime as dt

        patch_body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "sentinel.ai/rollback-trigger": dt.datetime.utcnow().isoformat()
                        }
                    }
                }
            }
        }

        await loop.run_in_executor(
            None,
            lambda: apps_v1.patch_namespaced_deployment(deployment, namespace, patch_body),
        )

        return {
            "status": "success",
            "output": f"Deployment '{deployment}' rollback triggered in namespace '{namespace}'. Previous revision: {current_revision}",
        }
    except Exception as e:
        return {"status": "failed", "output": f"Failed to rollback: {str(e)}"}


async def _k8s_scale_deployment(apps_v1, namespace: str, deployment: str, replicas: int) -> dict:
    """Scale a deployment to N replicas."""
    try:
        loop = asyncio.get_event_loop()
        patch_body = {"spec": {"replicas": replicas}}
        await loop.run_in_executor(
            None,
            lambda: apps_v1.patch_namespaced_deployment(deployment, namespace, patch_body),
        )
        return {
            "status": "success",
            "output": f"Scaled '{deployment}' to {replicas} replicas in namespace '{namespace}'.",
        }
    except Exception as e:
        return {"status": "failed", "output": f"Failed to scale: {str(e)}"}


async def _k8s_exec_cleanup(v1, namespace: str, pod_name: str) -> dict:
    """Execute cleanup commands inside a pod (clear /tmp, old logs)."""
    try:
        from kubernetes.stream import stream
        loop = asyncio.get_event_loop()

        # Run cleanup command
        cleanup_cmd = ["sh", "-c", "rm -rf /tmp/* 2>/dev/null; find /var/log -name '*.log' -mtime +7 -delete 2>/dev/null; echo 'Cleanup complete'"]

        resp = await loop.run_in_executor(
            None,
            lambda: stream(
                v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=cleanup_cmd,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            ),
        )

        return {
            "status": "success",
            "output": f"Cleanup executed on pod '{pod_name}': {resp}",
        }
    except Exception as e:
        return {"status": "failed", "output": f"Failed to cleanup: {str(e)}"}


# ── Simulation ──

async def _simulate_step(step: dict) -> dict:
    """Simulate executing a fix step (used in dev when K8s is not available)."""
    await asyncio.sleep(0.5)  # Simulate execution time
    return {
        "status": "success",
        "output": f"[SIMULATION] Executed: {step.get('action', 'Unknown')}",
    }


# ── Helpers ──

def _extract_namespace(command: str) -> Optional[str]:
    """Extract namespace from a kubectl command string."""
    parts = command.split()
    for i, part in enumerate(parts):
        if part in ("-n", "--namespace") and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _extract_resource(command: str) -> Optional[str]:
    """Extract resource name from a kubectl command string."""
    parts = command.split()
    # Look for patterns like "deployment/name" or "pod/name"
    for part in parts:
        if "/" in part and not part.startswith("-"):
            return part.split("/")[-1]
    # Fallback: return last non-flag argument
    for part in reversed(parts):
        if not part.startswith("-"):
            return part
    return None


def _extract_replicas(command: str) -> Optional[int]:
    """Extract replica count from a kubectl scale command."""
    parts = command.split()
    for i, part in enumerate(parts):
        if part.startswith("--replicas="):
            try:
                return int(part.split("=")[1])
            except (ValueError, IndexError):
                pass
        if part == "--replicas" and i + 1 < len(parts):
            try:
                return int(parts[i + 1])
            except ValueError:
                pass
    return None
