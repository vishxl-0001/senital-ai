"""
Phase 2 verification — fake safety mechanisms are now real.

The headline check (from the plan): with a mocked Kubernetes client, a fix that
leaves a pod unhealthy makes the health monitor return `rollback_needed` — it is
no longer always-healthy. Plus: the executor reports failure on a failed K8s
call, Prometheus no longer fabricates metrics, RCA tempers confidence without
metrics, and the remote-agent exec path is a typed whitelist (no shell).
"""

import importlib.util
import pathlib

import pytest

from app.engine.executor import execute_fix
from app.engine.health_monitor import monitor_health_post_fix
from app.engine.k8s_actions import build_structured_action
from app.agents.rca import adjust_confidence_for_metrics
from app.integrations.prometheus import query_prometheus
from app.config import settings


# ── Fake Kubernetes pod objects (mimic the kubernetes client's V1Pod shape) ──

class _Waiting:
    def __init__(self, reason):
        self.reason = reason


class _State:
    def __init__(self, waiting_reason=None):
        self.waiting = _Waiting(waiting_reason) if waiting_reason else None


class _ContainerStatus:
    def __init__(self, ready, restart_count, waiting_reason=None):
        self.ready = ready
        self.restart_count = restart_count
        self.state = _State(waiting_reason)


class _Meta:
    def __init__(self, name):
        self.name = name


class _PodStatus:
    def __init__(self, phase, container_statuses):
        self.phase = phase
        self.container_statuses = container_statuses


class FakePod:
    def __init__(self, name, phase, container_statuses):
        self.metadata = _Meta(name)
        self.status = _PodStatus(phase, container_statuses)


def _healthy_pod():
    return FakePod("payment-service-1", "Running", [_ContainerStatus(ready=True, restart_count=0)])


def _crashlooping_pod():
    return FakePod("payment-service-1", "Running",
                   [_ContainerStatus(ready=False, restart_count=7, waiting_reason="CrashLoopBackOff")])


class FakeV1:
    """Minimal stand-in for CoreV1Api."""
    def __init__(self, pod=None, error=None):
        self._pod = pod
        self._error = error
        self.delete_calls = []

    def read_namespaced_pod(self, name, namespace):
        if self._error:
            raise self._error
        return self._pod

    def delete_namespaced_pod(self, name, namespace):
        self.delete_calls.append((name, namespace))
        if self._error:
            raise self._error
        return {"deleted": name}


HEALTH_CHECK = {"check": "pod-ready", "pod": "payment-service-1",
                "namespace": "production", "wait_seconds": 0, "max_restarts": 3}
FIX_PLAN_WITH_CHECK = {
    "fix_type": "restart_pod",
    "steps": [{"order": 1, "action": "restart pod",
               "command": "kubectl delete pod payment-service-1 -n production"}],
    "health_checks": [HEALTH_CHECK],
}


# ── Item 6: health monitor returns rollback_needed on a broken fix ──────────

async def test_health_monitor_rollback_when_pod_unhealthy():
    v1 = FakeV1(pod=_crashlooping_pod())
    result = await monitor_health_post_fix(
        FIX_PLAN_WITH_CHECK, incident_id="t1",
        duration_seconds=30, check_interval_seconds=0.01, k8s_clients=(v1, None),
    )
    assert result["status"] == "rollback_needed", result


async def test_health_monitor_healthy_when_pod_ready():
    v1 = FakeV1(pod=_healthy_pod())
    result = await monitor_health_post_fix(
        FIX_PLAN_WITH_CHECK, incident_id="t2",
        duration_seconds=1, check_interval_seconds=1, k8s_clients=(v1, None),
    )
    assert result["status"] == "healthy", result


async def test_health_monitor_k8s_error_counts_as_failure():
    # If we can't read pod state, we must NOT optimistically pass.
    v1 = FakeV1(error=Exception("k8s API unreachable"))
    result = await monitor_health_post_fix(
        FIX_PLAN_WITH_CHECK, incident_id="t3",
        duration_seconds=30, check_interval_seconds=0.01, k8s_clients=(v1, None),
    )
    assert result["status"] == "rollback_needed", result


async def test_health_monitor_simulated_fallback_is_flagged():
    # No K8s client at all and no promql → simulated, but explicitly marked.
    plan = {"health_checks": [{"check": "noop", "wait_seconds": 0,
                               "success_criteria": "ok"}]}
    result = await monitor_health_post_fix(
        plan, incident_id="t4",
        duration_seconds=1, check_interval_seconds=1, k8s_clients=(None, None),
    )
    last_check = result["results"][-1]["checks"][-1]
    assert last_check["simulated"] is True


# ── Item 6/executor: a failed K8s mutation is reported as failed ────────────

async def test_executor_failed_restart_reports_failure(monkeypatch):
    v1 = FakeV1(error=Exception("pod delete denied"))
    monkeypatch.setattr("app.engine.executor._get_k8s_clients", lambda: (v1, object()))
    result = await execute_fix(FIX_PLAN_WITH_CHECK, incident_id="t5")
    assert result["status"] == "failed", result
    assert result["needs_rollback"] is True
    assert result["real_execution"] is True


# ── Item 7: Prometheus returns no_data instead of fabricated metrics ────────

async def test_prometheus_no_data_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "PROMETHEUS_URL", None)
    monkeypatch.setattr(settings, "PROMETHEUS_ALLOW_MOCK", False)
    out = await query_prometheus("rate(container_cpu_usage[5m])")
    assert out == {"status": "no_data", "reason": "not_configured"}
    # And crucially: no fabricated "0.95" cpu value anywhere.
    assert "result" not in out


async def test_prometheus_mock_only_in_dev_optin(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "PROMETHEUS_ALLOW_MOCK", True)
    out = await query_prometheus("cpu usage")
    assert out["status"] == "success" and out.get("mock") is True


# ── Item 7: RCA tempers confidence without live metrics ─────────────────────

def test_rca_confidence_penalized_without_metrics():
    capped = adjust_confidence_for_metrics({"confidence": 0.95, "evidence": []}, metrics_available=False)
    assert capped["confidence"] <= 0.6
    assert any("metrics" in e["description"].lower() for e in capped["evidence"])


def test_rca_confidence_untouched_with_metrics():
    kept = adjust_confidence_for_metrics({"confidence": 0.95, "evidence": []}, metrics_available=True)
    assert kept["confidence"] == 0.95


# ── Item 8: SaaS emits structured typed actions, not shell strings ──────────

def test_build_structured_action_restart():
    action = build_structured_action({
        "fix_type": "restart_pod",
        "steps": [{"action": "restart", "command": "kubectl delete pod payment-service-1 -n production"}],
    })
    assert action == {"type": "restart_pod", "namespace": "production", "resource": "payment-service-1"}


def test_build_structured_action_scale_extracts_replicas():
    action = build_structured_action({
        "fix_type": "scale_horizontal",
        "steps": [{"action": "scale", "command": "kubectl scale deployment/api --replicas=5 -n prod"}],
    })
    assert action["type"] == "scale_horizontal" and action["replicas"] == 5


def test_build_structured_action_rejects_unmappable():
    assert build_structured_action({"fix_type": "send_email", "steps": []}) is None


# ── Item 8: remote agent executes a whitelist of argv lists (no shell) ──────

def _load_agent_executor():
    path = pathlib.Path(__file__).resolve().parents[2] / "sentinel-agent" / "executor.py"
    spec = importlib.util.spec_from_file_location("sentinel_agent_executor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_build_argv_whitelisted():
    ex = _load_agent_executor()
    argv = ex.build_argv({"type": "restart_pod", "namespace": "production", "resource": "payment-service-1"})
    assert argv == ["kubectl", "delete", "pod", "payment-service-1", "-n", "production"]
    # No shell metacharacters in any token.
    assert all("&&" not in a and ";" not in a and "|" not in a for a in argv)


def test_agent_build_argv_rejects_unknown_type():
    ex = _load_agent_executor()
    with pytest.raises(ValueError):
        ex.build_argv({"type": "rm_rf_everything", "namespace": "x", "resource": "y"})


def test_agent_build_argv_rejects_injection_in_resource():
    ex = _load_agent_executor()
    # A resource crafted to inject a flag/command must be refused, not argv-built.
    with pytest.raises(ValueError):
        ex.build_argv({"type": "restart_pod", "namespace": "prod", "resource": "x -n kube-system --all"})
    with pytest.raises(ValueError):
        ex.build_argv({"type": "scale_horizontal", "namespace": "prod",
                       "resource": "api", "replicas": "5; rm -rf /"})
