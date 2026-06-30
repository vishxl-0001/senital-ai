"""
Sentinel AI — Structured K8s actions (shared helpers).

Turns a loosely-typed fix_plan into a *structured, typed* action so the remote
agent never has to interpret a free-form shell string. The whitelist here is the
single source of truth for what the platform is allowed to do to a cluster.

Used by:
  • app/api/agent.py        — builds the action the remote agent will execute
  • app/engine/health_monitor.py — reuses the namespace/resource extractors
"""

from typing import Optional

# The only action types the platform may dispatch to a cluster. Anything that
# can't be mapped to one of these is refused rather than executed.
ALLOWED_ACTION_TYPES = {
    "restart_pod",
    "rollback_deployment",
    "scale_horizontal",
    "clear_disk",
}


def extract_namespace(command: str) -> Optional[str]:
    """Extract namespace from a kubectl command string (`-n`/`--namespace`)."""
    parts = (command or "").split()
    for i, part in enumerate(parts):
        if part in ("-n", "--namespace") and i + 1 < len(parts):
            return parts[i + 1]
    return None


def extract_resource(command: str) -> Optional[str]:
    """Extract resource name from a kubectl command string."""
    parts = (command or "").split()

    # Drop the namespace flag AND its value so the value isn't mistaken for the
    # resource name (e.g. "... -n production" must not return "production").
    cleaned = []
    skip = False
    for part in parts:
        if skip:
            skip = False
            continue
        if part in ("-n", "--namespace"):
            skip = True
            continue
        cleaned.append(part)

    # Patterns like "deployment/name" or "pod/name"
    for part in cleaned:
        if "/" in part and not part.startswith("-"):
            return part.split("/")[-1]
    # Fallback: last non-flag, non-verb token
    verbs = {"kubectl", "get", "delete", "scale", "rollout", "undo", "exec",
             "pod", "pods", "deployment", "deploy", "deployments", "svc", "service"}
    for part in reversed(cleaned):
        if not part.startswith("-") and part not in verbs:
            return part
    return None


def extract_replicas(command: str) -> Optional[int]:
    """Extract replica count from a kubectl scale command."""
    parts = (command or "").split()
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


def normalize_action_type(fix_type: Optional[str], action_text: str = "") -> Optional[str]:
    """Map a fix_type / action description to one of the whitelisted action types."""
    ft = (fix_type or "").lower().strip()
    a = (action_text or "").lower()
    if ft in ALLOWED_ACTION_TYPES:
        return ft
    if ft in ("restart", "restart_pods") or "restart" in a or "delete pod" in a:
        return "restart_pod"
    if "rollback" in ft or "rollback" in a:
        return "rollback_deployment"
    if "scale" in ft or "scale" in a:
        return "scale_horizontal"
    if "disk" in ft or "clean" in a or "clear" in a or "cleanup" in a:
        return "clear_disk"
    return None


def build_structured_action(fix_plan: dict) -> Optional[dict]:
    """
    Derive a single structured action from a fix_plan, or None if the plan can't
    be safely mapped to a whitelisted action (caller should then NOT dispatch it).
    """
    fix_plan = fix_plan or {}
    steps = fix_plan.get("steps", []) or []
    commands = " ".join(s.get("command", "") for s in steps)
    action_text = " ".join(s.get("action", "") for s in steps)

    atype = normalize_action_type(fix_plan.get("fix_type"), action_text)
    if atype is None:
        return None

    namespace = fix_plan.get("namespace") or extract_namespace(commands) or "default"
    resource = (
        fix_plan.get("resource")
        or fix_plan.get("target")
        or extract_resource(commands)
    )
    if not resource:
        return None

    action = {"type": atype, "namespace": namespace, "resource": resource}
    if atype == "scale_horizontal":
        action["replicas"] = fix_plan.get("replicas") or extract_replicas(commands) or 3
    return action
