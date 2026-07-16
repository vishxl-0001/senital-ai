"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Globe, Activity, ArrowLeft, Plus, Pause, Play, Trash2,
  CheckCircle, XCircle, Clock, ShieldCheck,
} from "lucide-react";
import {
  fetchMonitors, createMonitor, deleteMonitor, pauseMonitor, resumeMonitor,
  Monitor,
} from "@/lib/api";

const STATUS_CONFIG: Record<string, { label: string; color: string; dot: string; icon: React.ReactNode }> = {
  up: {
    label: "Up",
    color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]",
    icon: <CheckCircle size={12} />,
  },
  down: {
    label: "Down",
    color: "bg-red-500/10 text-red-400 border-red-500/20",
    dot: "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.6)] animate-pulse",
    icon: <XCircle size={12} />,
  },
  pending: {
    label: "Pending",
    color: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
    dot: "bg-zinc-400",
    icon: <Clock size={12} />,
  },
  paused: {
    label: "Paused",
    color: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    dot: "bg-amber-400",
    icon: <Pause size={12} />,
  },
};

export default function MonitorsPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Add-monitor form state
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [interval, setIntervalSec] = useState(60);
  const [keyword, setKeyword] = useState("");
  const [latencyMs, setLatencyMs] = useState("");

  const loadMonitors = useCallback(async () => {
    try {
      const data = await fetchMonitors();
      setMonitors(data.monitors);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMonitors();
    const timer = setInterval(loadMonitors, 10000);
    return () => clearInterval(timer);
  }, [loadMonitors]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await createMonitor({
        name: name.trim(),
        url: url.trim(),
        interval_seconds: interval,
        keyword: keyword.trim() || null,
        latency_threshold_ms: latencyMs ? Number(latencyMs) : null,
      });
      setName(""); setUrl(""); setKeyword(""); setLatencyMs(""); setIntervalSec(60);
      setShowForm(false);
      await loadMonitors();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handlePauseResume = async (m: Monitor) => {
    try {
      if (m.is_active) await pauseMonitor(m.id);
      else await resumeMonitor(m.id);
      await loadMonitors();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDelete = async (m: Monitor) => {
    if (!confirm(`Delete monitor "${m.name}"? Checks stop immediately.`)) return;
    try {
      await deleteMonitor(m.id);
      await loadMonitors();
    } catch (err: any) {
      setError(err.message);
    }
  };

  function formatTime(dateStr: string | null) {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    return `${Math.floor(diffH / 24)}d ago`;
  }

  function sslDaysLeft(m: Monitor): number | null {
    if (!m.ssl_expires_at) return null;
    return Math.floor((new Date(m.ssl_expires_at).getTime() - Date.now()) / 86400000);
  }

  const upCount = monitors.filter((m) => m.status === "up").length;
  const downCount = monitors.filter((m) => m.status === "down").length;

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
              <Globe size={22} className="text-primary" />
              <h1 className="text-xl font-semibold">Uptime Monitors</h1>
            </div>
            <span className="text-sm text-zinc-500">
              {monitors.length} monitor{monitors.length !== 1 ? "s" : ""}
              {monitors.length > 0 && (
                <>
                  {" · "}
                  <span className="text-emerald-400">{upCount} up</span>
                  {downCount > 0 && (
                    <>
                      {" · "}
                      <span className="text-red-400">{downCount} down</span>
                    </>
                  )}
                </>
              )}
            </span>
          </div>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-2 bg-primary/10 text-primary border border-primary/20 px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/20 transition-colors"
          >
            <Plus size={16} /> Add Monitor
          </button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* Error Banner */}
        {error && (
          <div className="mb-4 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            ⚠️ {error}
          </div>
        )}

        {/* Add Monitor Form */}
        {showForm && (
          <form
            onSubmit={handleCreate}
            className="glass-panel rounded-xl border border-white/10 p-6 mb-6 space-y-4"
          >
            <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">New Monitor</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <input
                type="text"
                placeholder="Name (e.g. Main site)"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={200}
                className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
              />
              <input
                type="url"
                placeholder="https://example.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
                className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
              />
              <select
                value={interval}
                onChange={(e) => setIntervalSec(Number(e.target.value))}
                className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary"
              >
                <option value={30}>Check every 30s</option>
                <option value={60}>Check every 1 min</option>
                <option value={300}>Check every 5 min</option>
              </select>
              <input
                type="text"
                placeholder="Keyword in page (optional — catches error pages served as 200)"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                maxLength={500}
                className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
              />
              <input
                type="number"
                placeholder="Alert if slower than… ms (optional)"
                value={latencyMs}
                onChange={(e) => setLatencyMs(e.target.value)}
                min={1}
                className="bg-surface border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
              />
            </div>
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={submitting}
                className="bg-primary/10 text-primary border border-primary/20 px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/20 transition-colors disabled:opacity-50"
              >
                {submitting ? "Creating…" : "Create Monitor"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="text-zinc-400 hover:text-white px-4 py-2 text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Table */}
        <div className="glass-panel rounded-xl border border-white/10 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/10 text-zinc-400 text-xs uppercase tracking-wider">
                <th className="text-left px-6 py-4 font-medium">Monitor</th>
                <th className="text-left px-4 py-4 font-medium">Status</th>
                <th className="text-left px-4 py-4 font-medium">Response</th>
                <th className="text-left px-4 py-4 font-medium">SSL</th>
                <th className="text-left px-4 py-4 font-medium">Last Check</th>
                <th className="text-right px-6 py-4 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && monitors.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-16 text-zinc-500">
                    <Activity size={24} className="mx-auto mb-2 animate-spin" />
                    Loading monitors...
                  </td>
                </tr>
              ) : monitors.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-16 text-zinc-500">
                    No monitors yet. Add your first URL — checks start within 30 seconds.
                  </td>
                </tr>
              ) : (
                monitors.map((m) => {
                  const stat = STATUS_CONFIG[m.status] || STATUS_CONFIG.pending;
                  const sslDays = sslDaysLeft(m);
                  return (
                    <tr
                      key={m.id}
                      className="border-b border-white/5 hover:bg-white/[0.02] transition-colors"
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${stat.dot}`}></span>
                          <div>
                            <div className="font-medium text-white">{m.name}</div>
                            <div className="text-xs text-zinc-500 mt-0.5 break-all">{m.url}</div>
                            {m.status === "down" && m.last_error && (
                              <div className="text-xs text-red-400 mt-1">{m.last_error}</div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] uppercase tracking-wider font-bold border ${stat.color}`}>
                          {stat.icon} {stat.label}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-sm text-zinc-300 font-mono">
                        {m.last_response_ms != null ? `${m.last_response_ms}ms` : "—"}
                        {m.last_status_code != null && (
                          <span className="text-zinc-500 ml-2 text-xs">{m.last_status_code}</span>
                        )}
                      </td>
                      <td className="px-4 py-4 text-sm">
                        {sslDays == null ? (
                          <span className="text-zinc-600">—</span>
                        ) : (
                          <span
                            className={`inline-flex items-center gap-1 ${
                              sslDays < m.ssl_warn_days ? "text-amber-400" : "text-zinc-400"
                            }`}
                          >
                            <ShieldCheck size={14} /> {sslDays}d
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-4 text-sm text-zinc-500">
                        {formatTime(m.last_checked_at)}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handlePauseResume(m)}
                            title={m.is_active ? "Pause checks" : "Resume checks"}
                            className="text-zinc-500 hover:text-amber-400 transition-colors p-1.5 rounded-md hover:bg-white/5"
                          >
                            {m.is_active ? <Pause size={16} /> : <Play size={16} />}
                          </button>
                          <button
                            onClick={() => handleDelete(m)}
                            title="Delete monitor"
                            className="text-zinc-500 hover:text-red-400 transition-colors p-1.5 rounded-md hover:bg-white/5"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
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
