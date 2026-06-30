"""
Sentinel AI — Production Remote Execution & Monitoring Agent
Runs inside the CUSTOMER'S infrastructure (e.g., as a Kubernetes Deployment or DaemonSet).

Capabilities:
1. Monitors Kubernetes logs & events for anomalies.
2. Forwards alerts securely to the Sentinel AI SaaS.
3. Polls the SaaS for approved fixes (RCA fixes), executes them locally, and reports back.
"""

import time
import requests
import subprocess
import os
import json
import logging
from datetime import datetime

from executor import build_argv

# ── Configuration ──
SENTINEL_SAAS_URL = os.environ.get("SENTINEL_SAAS_URL", "http://localhost:8000")
API_KEY = os.environ.get("SENTINEL_AGENT_KEY", "your-organization-api-key")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "15"))
MONITOR_INTERVAL = int(os.environ.get("MONITOR_INTERVAL", "30"))
CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "production-cluster")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sentinel-agent")


def run_cmd(args: list, timeout: int = 30) -> str:
    """Run an argv list (NO shell) and return stdout, or '' on failure."""
    try:
        result = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


class LogConfigMonitor:
    """Monitors local infrastructure (e.g. Kubernetes) for issues and configs."""
    
    def __init__(self):
        self.last_check = time.time()
        # Track seen errors to avoid spamming the SaaS
        self.seen_errors = set()
        
    def check_for_anomalies(self):
        """Scan logs and configs for errors or misconfigurations."""
        logger.info("🔍 Scanning cluster for anomalies...")
        
        # In a real environment, this would use the kubernetes python client.
        # Here we use kubectl as an example if available, or simulate if not.
        kubectl_available = run_cmd(["which", "kubectl"])
        
        if kubectl_available:
            self._check_k8s_pods()
        else:
            self._simulate_check()

    def _check_k8s_pods(self):
        """Check for pods in CrashLoopBackOff or Error states."""
        output = run_cmd(["kubectl", "get", "pods", "-A",
                          "--field-selector=status.phase!=Running", "-o", "json"])
        if not output:
            return
            
        try:
            pods = json.loads(output)
            for pod in pods.get("items", []):
                name = pod["metadata"]["name"]
                namespace = pod["metadata"]["namespace"]
                status = pod["status"]["phase"]
                
                # Deduplicate alerts
                alert_key = f"{namespace}/{name}/{status}"
                if alert_key in self.seen_errors:
                    continue
                    
                self.seen_errors.add(alert_key)
                
                # Fetch logs for the failing pod
                logs = run_cmd(["kubectl", "logs", name, "-n", namespace, "--tail=50"])
                
                self.send_alert(
                    title=f"Pod Failure: {name} in {namespace}",
                    description=f"Pod is in {status} state. Logs indicate a crash or configuration error.",
                    severity="critical",
                    labels={"pod": name, "namespace": namespace, "cluster": CLUSTER_NAME},
                    raw_payload={"logs": logs, "pod_spec": pod}
                )
        except Exception as e:
            logger.error(f"Failed to parse k8s pods: {e}")
            
    def _simulate_check(self):
        """Simulate a check if kubectl is not available (for testing)."""
        # We can occasionally simulate an error if a specific file exists, 
        # or just wait for the SaaS to trigger something.
        if os.path.exists("/tmp/simulate_error"):
            if "test-error" not in self.seen_errors:
                self.seen_errors.add("test-error")
                self.send_alert(
                    title="Simulated OOMKilled Error",
                    description="The payment-service container exceeded its memory limit and was OOMKilled.",
                    severity="high",
                    labels={"service": "payment-service", "cluster": CLUSTER_NAME},
                    raw_payload={"exit_code": 137, "reason": "OOMKilled"}
                )
                os.remove("/tmp/simulate_error")
                
    def send_alert(self, title, description, severity, labels, raw_payload):
        """Forward detected anomaly to the SaaS via generic webhook."""
        payload = {
            "source": f"sentinel-agent-{CLUSTER_NAME}",
            "title": title,
            "description": description,
            "severity": severity,
            "labels": labels,
            "raw_payload": raw_payload
        }
        try:
            res = requests.post(f"{SENTINEL_SAAS_URL}/api/v1/alerts/webhook/generic", json=payload, headers=HEADERS)
            if res.status_code == 200:
                logger.info(f"🚨 Sent alert to SaaS: {title}")
            else:
                logger.error(f"Failed to send alert. Status: {res.status_code}, Body: {res.text}")
        except Exception as e:
            logger.error(f"Connection to SaaS failed: {e}")


def poll_for_fixes():
    """Poll the SaaS for any fixes that have been 'approved' by the customer."""
    try:
        response = requests.get(f"{SENTINEL_SAAS_URL}/api/v1/agent/pending-fixes", headers=HEADERS)
        if response.status_code == 200:
            fixes = response.json().get("fixes", [])
            for fix in fixes:
                execute_fix(fix)
        elif response.status_code == 401:
            logger.error("Unauthorized: Invalid API Key")
    except requests.exceptions.ConnectionError:
        logger.warning(f"Could not connect to {SENTINEL_SAAS_URL}. Retrying later.")
    except Exception as e:
        logger.error(f"Failed to poll Sentinel SaaS: {e}")

def execute_fix(fix_data):
    """Execute a structured, whitelisted fix action locally (no shell)."""
    incident_id = fix_data["incident_id"]
    action = fix_data.get("action") or {}

    # Build the argv from the typed action. A disallowed type or an invalid
    # namespace/resource is REFUSED — we never fall back to a shell string.
    try:
        argv = build_argv(action)
    except ValueError as e:
        logger.error(f"🚫 Refusing unsafe/unknown fix for {incident_id}: {e}")
        report_results(incident_id, "failed", f"Rejected by agent allowlist: {e}")
        return

    logger.info(f"⚙️ Executing {action.get('type')} for incident {incident_id}: {argv}")

    try:
        result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=120)

        status = "success" if result.returncode == 0 else "failed"
        output = result.stdout if result.returncode == 0 else result.stderr

        report_results(incident_id, status, output)

    except subprocess.TimeoutExpired:
        logger.error(f"Fix execution timed out for {incident_id}")
        report_results(incident_id, "failed", "Command execution timed out after 120s")
    except Exception as e:
        logger.error(f"Fix execution failed: {e}")
        report_results(incident_id, "failed", str(e))

def report_results(incident_id, status, output):
    """Send the execution results back to the SaaS."""
    payload = {
        "incident_id": incident_id,
        "status": status,
        "output": output[:2000] # Truncate output if too long
    }
    try:
        requests.post(f"{SENTINEL_SAAS_URL}/api/v1/agent/report-fix", json=payload, headers=HEADERS)
        logger.info(f"📊 Results reported for {incident_id} ({status})")
    except Exception as e:
        logger.error(f"Failed to report results: {e}")

if __name__ == "__main__":
    logger.info(f"🛡️ Sentinel Production Agent Started.")
    logger.info(f"📍 Target SaaS: {SENTINEL_SAAS_URL}")
    logger.info(f"🏢 Cluster Name: {CLUSTER_NAME}")
    
    monitor = LogConfigMonitor()
    last_monitor_time = 0
    
    while True:
        current_time = time.time()
        
        # 1. Poll for pending execution tasks
        poll_for_fixes()
        
        # 2. Periodically monitor logs/configs
        if current_time - last_monitor_time > MONITOR_INTERVAL:
            monitor.check_for_anomalies()
            last_monitor_time = current_time
            
        time.sleep(POLL_INTERVAL)
