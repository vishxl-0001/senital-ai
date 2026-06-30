"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ShieldAlert, Activity, Clock, ArrowLeft, Search, Filter,
  ChevronDown, Zap, AlertTriangle, CheckCircle, XCircle, Eye
} from "lucide-react";
import { fetchIncidents, IncidentListItem, sendTestAlert } from "@/lib/api";
import { useIncidentStream } from "@/hooks/useIncidentStream";

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  detected: { label: "Detected", color: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20", icon: <AlertTriangle size={12} /> },
  investigating: { label: "Investigating", color: "bg-blue-500/10 text-blue-400 border-blue-500/20", icon: <Eye size={12} /> },
  rca_complete: { label: "RCA Complete", color: "bg-purple-500/10 text-purple-400 border-purple-500/20", icon: <Activity size={12} /> },
  fix_proposed: { label: "Fix Proposed", color: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20", icon: <Zap size={12} /> },
  fix_approved: { label: "Fix Approved", color: "bg-orange-500/10 text-orange-400 border-orange-500/20", icon: <CheckCircle size={12} /> },
  fix_executing: { label: "Executing", color: "bg-orange-500/10 text-orange-300 border-orange-500/20", icon: <Zap size={12} /> },
  fix_monitoring: { label: "Monitoring", color: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20", icon: <Activity size={12} /> },
  resolved: { label: "Resolved", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", icon: <CheckCircle size={12} /> },
  failed: { label: "Failed", color: "bg-red-500/10 text-red-400 border-red-500/20", icon: <XCircle size={12} /> },
  escalated: { label: "Escalated", color: "bg-rose-500/10 text-rose-400 border-rose-500/20", icon: <AlertTriangle size={12} /> },
};

const SEVERITY_CONFIG: Record<string, { color: string; dot: string }> = {
  critical: { color: "text-red-400", dot: "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.6)]" },
  high: { color: "text-orange-400", dot: "bg-orange-400" },
  medium: { color: "text-yellow-400", dot: "bg-yellow-400" },
  low: { color: "text-green-400", dot: "bg-green-400" },
  info: { color: "text-blue-400", dot: "bg-blue-400" },
};

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<IncidentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");

  const loadIncidents = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchIncidents({
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
        limit: 50,
      });
      setIncidents(data.incidents);
      setError(null);
    } catch (err: any) {
      setError(err.message);
      // Use empty array on error
      setIncidents([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, severityFilter]);

  useEffect(() => {
    loadIncidents();
    // Poll every 10 seconds as a fallback to the live WebSocket stream.
    const interval = setInterval(loadIncidents, 10000);
    return () => clearInterval(interval);
  }, [loadIncidents]);

  // Live updates: patch the matching row in place; if we get an update for an
  // incident we haven't loaded yet (e.g. a brand-new one), refetch the list.
  const { connected: liveConnected } = useIncidentStream(
    useCallback((update) => {
      setIncidents((prev) => {
        const idx = prev.findIndex((inc) => inc.id === update.id);
        if (idx === -1) {
          loadIncidents();
          return prev;
        }
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          ...(update.status ? { status: update.status } : {}),
          ...(update.severity ? { severity: update.severity } : {}),
          ...(update.title ? { title: update.title } : {}),
        };
        return next;
      });
    }, [loadIncidents])
  );

  const filteredIncidents = incidents.filter((inc) =>
    !searchQuery || inc.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleTestAlert = async () => {
    try {
      await sendTestAlert();
      setTimeout(loadIncidents, 2000);
    } catch (err: any) {
      setError(err.message);
    }
  };

  function formatTime(dateStr: string | null) {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    return `${Math.floor(diffH / 24)}d ago`;
  }

  function formatMTTR(seconds: number | null) {
    if (!seconds) return "—";
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-white/10 glass-panel">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-zinc-400 hover:text-white transition-colors">
              <ArrowLeft size={20} />
            </Link>
            <div className="flex items-center gap-2">
              <ShieldAlert size={22} className="text-primary" />
              <h1 className="text-xl font-semibold">Incidents</h1>
            </div>
            <span className="text-sm text-zinc-500">
              {filteredIncidents.length} incident{filteredIncidents.length !== 1 ? "s" : ""}
            </span>
            <span
              className="flex items-center gap-1.5 text-xs text-zinc-500"
              title={liveConnected ? "Live updates connected" : "Reconnecting…"}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  liveConnected
                    ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]"
                    : "bg-zinc-600"
                }`}
              ></span>
              {liveConnected ? "Live" : "Offline"}
            </span>
          </div>
          <button
            onClick={handleTestAlert}
            className="bg-primary/10 text-primary border border-primary/20 px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/20 transition-colors"
          >
            🧪 Send Test Alert
          </button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* Filters */}
        <div className="flex flex-wrap gap-4 mb-6">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input
              type="text"
              placeholder="Search incidents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-surface border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary"
          >
            <option value="">All Statuses</option>
            {Object.entries(STATUS_CONFIG).map(([key, val]) => (
              <option key={key} value={key}>{val.label}</option>
            ))}
          </select>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary"
          >
            <option value="">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="mb-4 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            ⚠️ {error} — Make sure the backend is running on port 8000
          </div>
        )}

        {/* Table */}
        <div className="glass-panel rounded-xl border border-white/10 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/10 text-zinc-400 text-xs uppercase tracking-wider">
                <th className="text-left px-6 py-4 font-medium">Incident</th>
                <th className="text-left px-4 py-4 font-medium">Severity</th>
                <th className="text-left px-4 py-4 font-medium">Status</th>
                <th className="text-left px-4 py-4 font-medium">Fix Type</th>
                <th className="text-left px-4 py-4 font-medium">MTTR</th>
                <th className="text-left px-4 py-4 font-medium">Detected</th>
                <th className="text-right px-6 py-4 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {loading && incidents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-16 text-zinc-500">
                    <Activity size={24} className="mx-auto mb-2 animate-spin" />
                    Loading incidents...
                  </td>
                </tr>
              ) : filteredIncidents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-16 text-zinc-500">
                    No incidents found. Send a test alert to get started!
                  </td>
                </tr>
              ) : (
                filteredIncidents.map((inc) => {
                  const sev = SEVERITY_CONFIG[inc.severity] || SEVERITY_CONFIG.medium;
                  const stat = STATUS_CONFIG[inc.status] || STATUS_CONFIG.detected;
                  return (
                    <tr
                      key={inc.id}
                      className="border-b border-white/5 hover:bg-white/[0.02] transition-colors group"
                    >
                      <td className="px-6 py-4">
                        <Link href={`/incidents/${inc.id}`} className="block">
                          <div className="font-medium text-white group-hover:text-primary transition-colors">
                            {inc.title}
                          </div>
                          <div className="text-xs text-zinc-500 mt-1">
                            {inc.source} • {inc.id.slice(0, 8)}
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${sev.dot}`}></span>
                          <span className={`text-sm capitalize ${sev.color}`}>{inc.severity}</span>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] uppercase tracking-wider font-bold border ${stat.color}`}>
                          {stat.icon} {stat.label}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-sm text-zinc-300">
                        {inc.fix_type ? <code className="bg-white/5 px-2 py-0.5 rounded text-xs">{inc.fix_type}</code> : "—"}
                      </td>
                      <td className="px-4 py-4 text-sm text-zinc-300 font-mono">
                        {formatMTTR(inc.mttr_seconds)}
                      </td>
                      <td className="px-4 py-4 text-sm text-zinc-500">
                        {formatTime(inc.detected_at || inc.created_at)}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <Link
                          href={`/incidents/${inc.id}`}
                          className="text-zinc-500 hover:text-primary transition-colors"
                        >
                          <ArrowLeft size={16} className="rotate-180" />
                        </Link>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
