/**
 * Sentinel AI — API Client
 * Connects the dashboard to the backend API.
 *
 * Every backend call is authenticated with the caller's Clerk session token
 * (sent as `Authorization: Bearer <token>`). The backend verifies the JWT
 * server-side and derives tenant_id from the verified `org_id` claim — the
 * client never sends tenant_id / X-Tenant-Id / org_id.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

/**
 * Get the current Clerk session token from Clerk's browser singleton.
 * Lets these helpers stay plain async functions (no React hooks). All callers
 * are client components that fetch after mount — by which point Clerk is loaded
 * and, thanks to middleware, the user is authenticated.
 */
async function getSessionToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  const clerk = (window as unknown as { Clerk?: { session?: { getToken: () => Promise<string | null> } } }).Clerk;
  try {
    return (await clerk?.session?.getToken()) ?? null;
  } catch {
    return null;
  }
}

/** fetch() wrapper that attaches the Clerk session token. */
async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = await getSessionToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

export interface Incident {
  id: string;
  incident_number: number | null;
  title: string;
  status: string;
  severity: string;
  source: string;
  investigation_summary: string | null;
  root_cause: string | null;
  rca_evidence: any[] | null;
  rca_confidence: number | null;
  fix_plan: any | null;
  fix_type: string | null;
  fix_result: any | null;
  fix_approval: string | null;
  rollback_plan: any | null;
  affected_services: string[] | null;
  impact_description: string | null;
  similar_incidents: any[] | null;
  logs_collected: any | null;
  metrics_collected: any | null;
  deployment_context: any | null;
  detected_at: string | null;
  investigation_started_at: string | null;
  rca_completed_at: string | null;
  fix_started_at: string | null;
  resolved_at: string | null;
  mttr_seconds: number | null;
  created_at: string | null;
}

export interface IncidentListItem {
  id: string;
  incident_number: number | null;
  title: string;
  status: string;
  severity: string;
  source: string;
  root_cause: string | null;
  rca_confidence: number | null;
  fix_type: string | null;
  mttr_seconds: number | null;
  detected_at: string | null;
  resolved_at: string | null;
  created_at: string | null;
}

// ── Incidents API ──

export async function fetchIncidents(params?: {
  status?: string;
  severity?: string;
  limit?: number;
  offset?: number;
}): Promise<{ incidents: IncidentListItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.severity) query.set("severity", params.severity);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));

  const res = await authedFetch(`${API_BASE}/api/v1/incidents?${query}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.status}`);
  return res.json();
}

export async function fetchIncident(id: string): Promise<Incident> {
  const res = await authedFetch(`${API_BASE}/api/v1/incidents/${id}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch incident: ${res.status}`);
  return res.json();
}

export async function approveFix(id: string): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/v1/incidents/${id}/approve-fix`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to approve fix: ${res.status}`);
  return res.json();
}

// ── Policies API ──

export async function fetchPolicies(): Promise<{ policies: any[] }> {
  const res = await authedFetch(`${API_BASE}/api/v1/policies`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch policies: ${res.status}`);
  return res.json();
}

export async function seedDefaultPolicies(): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/v1/policies/seed-defaults`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to seed policies: ${res.status}`);
  return res.json();
}

// ── Alerts API ──

export async function sendTestAlert(): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/v1/alerts/test`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to send test alert: ${res.status}`);
  return res.json();
}

// ── API Keys (auth) ──
// These hit the dashboard-protected /api/v1/auth/keys routes, which derive the
// tenant from the verified Clerk session — the client must NOT send tenant_id.

export interface ApiKeyItem {
  id: string;
  name: string;
  prefix: string;
  is_active: boolean;
  created_at: string | null;
  last_used_at: string | null;
}

export async function listApiKeys(): Promise<{ api_keys: ApiKeyItem[] }> {
  const res = await authedFetch(`${API_BASE}/api/v1/auth/keys`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch API keys: ${res.status}`);
  return res.json();
}

export async function createApiKey(
  name: string
): Promise<{ id: string; name: string; api_key: string; prefix: string; tenant_id: string }> {
  const res = await authedFetch(
    `${API_BASE}/api/v1/auth/keys?name=${encodeURIComponent(name)}`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error(`Failed to create API key: ${res.status}`);
  return res.json();
}

// ── Slack OAuth (item 13) ──

export async function getSlackInstallUrl(): Promise<{ authorize_url: string }> {
  const res = await authedFetch(`${API_BASE}/api/v1/slack/oauth/install`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to get Slack install URL: ${res.status}`);
  return res.json();
}

// ── Uptime Monitors API ──

export interface Monitor {
  id: string;
  name: string;
  url: string;
  interval_seconds: number;
  timeout_seconds: number;
  expected_status_codes: number[];
  keyword: string | null;
  latency_threshold_ms: number | null;
  ssl_check_enabled: boolean;
  ssl_warn_days: number;
  failure_threshold: number;
  is_active: boolean;
  status: "pending" | "up" | "down" | "paused";
  last_checked_at: string | null;
  last_response_ms: number | null;
  last_status_code: number | null;
  last_error: string | null;
  consecutive_failures: number;
  ssl_expires_at: string | null;
  created_at: string | null;
}

export interface MonitorCreateInput {
  name: string;
  url: string;
  interval_seconds?: number;
  timeout_seconds?: number;
  keyword?: string | null;
  latency_threshold_ms?: number | null;
  ssl_check_enabled?: boolean;
  failure_threshold?: number;
}

export async function fetchMonitors(): Promise<{ monitors: Monitor[] }> {
  const res = await authedFetch(`${API_BASE}/api/v1/monitors`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch monitors: ${res.status}`);
  return res.json();
}

export async function createMonitor(data: MonitorCreateInput): Promise<Monitor> {
  const res = await authedFetch(`${API_BASE}/api/v1/monitors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `Failed to create monitor: ${res.status}`);
  }
  return res.json();
}

export async function deleteMonitor(id: string): Promise<void> {
  const res = await authedFetch(`${API_BASE}/api/v1/monitors/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete monitor: ${res.status}`);
}

export async function pauseMonitor(id: string): Promise<Monitor> {
  const res = await authedFetch(`${API_BASE}/api/v1/monitors/${id}/pause`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to pause monitor: ${res.status}`);
  return res.json();
}

export async function resumeMonitor(id: string): Promise<Monitor> {
  const res = await authedFetch(`${API_BASE}/api/v1/monitors/${id}/resume`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to resume monitor: ${res.status}`);
  return res.json();
}

// ── Health ──

export async function checkHealth(): Promise<any> {
  const res = await authedFetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Backend unhealthy: ${res.status}`);
  return res.json();
}
