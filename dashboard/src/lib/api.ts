/**
 * Sentinel AI — API Client
 * Connects the dashboard to the backend API.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

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

  const res = await fetch(`${API_BASE}/api/v1/incidents?${query}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.status}`);
  return res.json();
}

export async function fetchIncident(id: string): Promise<Incident> {
  const res = await fetch(`${API_BASE}/api/v1/incidents/${id}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch incident: ${res.status}`);
  return res.json();
}

export async function approveFix(id: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/incidents/${id}/approve-fix`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to approve fix: ${res.status}`);
  return res.json();
}

// ── Policies API ──

export async function fetchPolicies(): Promise<{ policies: any[] }> {
  const res = await fetch(`${API_BASE}/api/v1/policies`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to fetch policies: ${res.status}`);
  return res.json();
}

export async function seedDefaultPolicies(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/policies/seed-defaults`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to seed policies: ${res.status}`);
  return res.json();
}

// ── Alerts API ──

export async function sendTestAlert(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/alerts/test`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to send test alert: ${res.status}`);
  return res.json();
}

// ── Health ──

export async function checkHealth(): Promise<any> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Backend unhealthy: ${res.status}`);
  return res.json();
}
