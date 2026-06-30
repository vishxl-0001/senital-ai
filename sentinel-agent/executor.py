"""
Sentinel Agent — Structured action executor (no shell).

The remote agent only ever runs argv lists built here from a *typed* action
received from the SaaS. There is no shell, no string concatenation, and an
explicit whitelist of action types. Namespace/resource names are validated
against the Kubernetes name grammar so they can never inject extra flags or
arguments into the argv list.
"""

import re

# Whitelist — must stay in sync with backend app/engine/k8s_actions.py
ALLOWED_ACTIONS = {
    "restart_pod",
    "rollback_deployment",
    "scale_horizontal",
    "clear_disk",
}

# RFC 1123-ish DNS label/subdomain grammar used by k8s object names.
_K8S_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")

# Fixed (non-parameterized) cleanup command run *inside* the target pod.
_CLEANUP_CMD = (
    "rm -rf /tmp/* 2>/dev/null; "
    "find /var/log -name '*.log' -mtime +7 -delete 2>/dev/null; "
    "echo cleanup-complete"
)


def _valid_name(value) -> bool:
    return isinstance(value, str) and bool(_K8S_NAME_RE.match(value))


def build_argv(action: dict) -> list:
    """
    Translate a typed action into a safe `kubectl` argv list.

    Raises ValueError if the action type isn't whitelisted or the
    namespace/resource/replicas fail validation — the caller must treat that as
    a refusal, not execute anything.
    """
    if not isinstance(action, dict):
        raise ValueError("action must be an object")

    atype = action.get("type")
    if atype not in ALLOWED_ACTIONS:
        raise ValueError(f"disallowed action type: {atype!r}")

    namespace = action.get("namespace") or "default"
    resource = action.get("resource")
    if not _valid_name(namespace):
        raise ValueError(f"invalid namespace: {namespace!r}")
    if not _valid_name(resource):
        raise ValueError(f"invalid resource name: {resource!r}")

    if atype == "restart_pod":
        return ["kubectl", "delete", "pod", resource, "-n", namespace]

    if atype == "rollback_deployment":
        return ["kubectl", "rollout", "undo", f"deployment/{resource}", "-n", namespace]

    if atype == "scale_horizontal":
        replicas = action.get("replicas", 3)
        if not isinstance(replicas, int) or isinstance(replicas, bool) or not (0 <= replicas <= 100):
            raise ValueError(f"invalid replicas: {replicas!r}")
        return ["kubectl", "scale", f"deployment/{resource}",
                f"--replicas={replicas}", "-n", namespace]

    if atype == "clear_disk":
        return ["kubectl", "exec", resource, "-n", namespace, "--", "sh", "-c", _CLEANUP_CMD]

    # Unreachable (atype already validated), kept for defensiveness.
    raise ValueError(f"unhandled action type: {atype!r}")
