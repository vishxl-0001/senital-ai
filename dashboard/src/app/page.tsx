"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { UserButton, OrganizationSwitcher } from "@clerk/nextjs";
import {
  ShieldAlert, Activity, Clock,
  Terminal, Settings, FileText, LayoutDashboard,
  Bell, ArrowRight, Zap, Globe
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from "recharts";
import { fetchStats, DashboardStats } from "@/lib/api";
import { useIncidentStream } from "@/hooks/useIncidentStream";

const STATUS_LABELS: Record<string, string> = {
  detected: "Detected",
  investigating: "Investigating",
  rca_complete: "RCA Complete",
  fix_proposed: "Fix Proposed",
  fix_approved: "Fix Approved",
  fix_executing: "Executing",
  fix_monitoring: "Monitoring",
  resolved: "Resolved",
  failed: "Failed",
  escalated: "Escalated",
};

export default function Dashboard() {
  const [mounted, setMounted] = useState(false);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const data = await fetchStats();
      setStats(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    loadStats();
    const interval = setInterval(loadStats, 10000);
    return () => clearInterval(interval);
  }, [loadStats]);

  // Refresh whenever an incident update streams in.
  const { connected: liveConnected } = useIncidentStream(
    useCallback(() => {
      loadStats();
    }, [loadStats])
  );

  if (!mounted) return null;

  const c = stats?.counters;
  const timeseries = stats?.timeseries ?? [];
  const recent = stats?.recent ?? [];

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">

      {/* Sidebar */}
      <aside className="w-64 border-r border-white/10 glass-panel flex flex-col z-10">
        <div className="h-16 flex items-center px-6 border-b border-white/10">
          <div className="flex items-center gap-2 text-primary font-bold text-xl tracking-tight">
            <ShieldAlert size={24} className="text-primary" />
            <span>Sentinel<span className="text-white">AI</span></span>
          </div>
        </div>

        <nav className="flex-1 py-6 px-4 space-y-2">
          <NavItem icon={<LayoutDashboard size={20} />} label="Dashboard" href="/" active />
          <NavItem
            icon={<Activity size={20} />}
            label="Incidents"
            href="/incidents"
            badge={c?.active ? String(c.active) : undefined}
          />
          <NavItem icon={<Globe size={20} />} label="Monitors" href="/monitors" />
          <NavItem icon={<Terminal size={20} />} label="Policies" href="/policies" />
          <NavItem icon={<FileText size={20} />} label="Runbooks" href="/runbooks" />
          <NavItem icon={<Settings size={20} />} label="Settings" href="/settings" />
        </nav>

        <div className="p-4 border-t border-white/10 space-y-2">
          {/* Tenant context: the backend scopes all data to the active Clerk
              organization and returns 403 without one. */}
          <OrganizationSwitcher
            hidePersonal
            appearance={{
              elements: {
                rootBox: "w-full",
                organizationSwitcherTrigger:
                  "w-full justify-start text-zinc-300 hover:bg-white/5 rounded-lg px-2 py-2",
              },
            }}
          />
          <div className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/5 transition-colors cursor-pointer">
            <UserButton />
            <div className="flex flex-col text-sm">
              <span className="font-medium">My Account</span>
              <span className="text-zinc-500 text-xs">Manage</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden relative">

        {/* Header */}
        <header className="h-16 flex items-center justify-between px-8 border-b border-white/10 glass-panel z-10">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-semibold">Overview</h1>
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
          <div className="flex items-center gap-6">
            <button className="relative text-zinc-400 hover:text-white transition-colors">
              <Bell size={20} />
              {c?.awaiting_approval ? (
                <span className="absolute -top-1 -right-1 w-2 h-2 bg-danger rounded-full shadow-[0_0_8px_rgba(225,29,72,0.8)]"></span>
              ) : null}
            </button>
          </div>
        </header>

        {/* Scrollable Area */}
        <div className="flex-1 overflow-auto p-8 z-0">

          {error && (
            <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              ⚠️ {error?.includes("403")
                ? "No active organization — pick or create one with the organization switcher in the sidebar."
                : `${error} — Make sure the backend is running on port 8000`}
            </div>
          )}

          {/* Top Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <MetricCard
              title="Mean Time To Resolve"
              value={formatMTTR(c?.avg_mttr_seconds ?? null)}
              subtitle="Across resolved incidents"
              icon={<Clock size={20} className="text-blue-400" />}
            />
            <MetricCard
              title="Resolved"
              value={c ? String(c.resolved) : "—"}
              subtitle={c ? `${c.total} total incidents` : ""}
              icon={<Zap size={20} className="text-yellow-400" />}
            />
            <MetricCard
              title="Open Incidents"
              value={c ? String(c.active) : "—"}
              subtitle={c?.active ? "Requires attention" : "All clear"}
              danger={!!c?.active}
              icon={<Activity size={20} className="text-danger" />}
            />
            <MetricCard
              title="Awaiting Approval"
              value={c ? String(c.awaiting_approval) : "—"}
              subtitle={c?.awaiting_approval ? "Pending human review" : "None pending"}
              danger={!!c?.awaiting_approval}
              icon={<ShieldAlert size={20} className="text-success" />}
            />
          </div>

          {/* Charts & Lists Row */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-8">

            {/* Main Chart */}
            <div className="xl:col-span-2 glass-panel rounded-xl p-6 border border-white/10">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium">Incident Volume (24h)</h2>
              </div>
              <div className="h-72 w-full">
                {timeseries.every((b) => b.incidents === 0 && b.resolved === 0) ? (
                  <div className="h-full flex items-center justify-center text-zinc-500 text-sm">
                    No incident activity in the last 24 hours.
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={timeseries} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <defs>
                        <linearGradient id="colorIncidents" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="var(--color-danger)" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="var(--color-danger)" stopOpacity={0}/>
                        </linearGradient>
                        <linearGradient id="colorResolved" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="var(--color-primary)" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="var(--color-primary)" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                      <XAxis dataKey="time" stroke="#52525b" fontSize={12} tickLine={false} axisLine={false} />
                      <YAxis stroke="#52525b" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#18181b', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '8px' }}
                        itemStyle={{ color: '#fff' }}
                      />
                      <Area type="monotone" dataKey="incidents" stroke="var(--color-danger)" fillOpacity={1} fill="url(#colorIncidents)" strokeWidth={2} />
                      <Area type="monotone" dataKey="resolved" stroke="var(--color-primary)" fillOpacity={1} fill="url(#colorResolved)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            {/* Recent Activity List */}
            <div className="glass-panel rounded-xl border border-white/10 flex flex-col">
              <div className="p-6 border-b border-white/10 flex items-center justify-between">
                <h2 className="text-lg font-medium">Recent Activity</h2>
                <Link href="/incidents" className="text-sm text-primary hover:text-primary/80 transition-colors">View All</Link>
              </div>
              <div className="flex-1 overflow-auto p-2">
                {recent.length === 0 ? (
                  <div className="p-8 text-center text-zinc-500 text-sm">
                    No incidents yet. Send a test alert from the Incidents page.
                  </div>
                ) : (
                  recent.map((inc) => (
                    <Link
                      key={inc.id}
                      href={`/incidents/${inc.id}`}
                      className="block p-4 rounded-lg hover:bg-white/5 transition-colors group cursor-pointer border border-transparent hover:border-white/5"
                    >
                      <div className="flex justify-between items-start mb-2">
                        <span className="text-sm font-bold text-zinc-300">
                          {inc.incident_reference || inc.id.slice(0, 8)}
                        </span>
                        <span className="text-xs text-zinc-500">{formatTime(inc.created_at)}</span>
                      </div>
                      <h3 className="font-medium text-white mb-3 text-sm truncate">{inc.title}</h3>
                      <div className="flex items-center justify-between">
                        <StatusBadge status={inc.status} />
                        <div className="flex items-center text-xs text-zinc-400 group-hover:text-primary transition-colors">
                          {inc.fix_type ? <span className="mr-1">{inc.fix_type}</span> : null}
                          <ArrowRight size={14} />
                        </div>
                      </div>
                    </Link>
                  ))
                )}
              </div>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}

// ── Helpers ──

function formatMTTR(seconds: number | null) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

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

// ── Subcomponents ──

function NavItem({ icon, label, href = "#", active = false, badge }: { icon: React.ReactNode, label: string, href?: string, active?: boolean, badge?: string }) {
  return (
    <Link href={href} className={`flex items-center justify-between px-4 py-3 rounded-xl transition-all duration-200 ${
      active
        ? "bg-primary/10 text-primary border border-primary/20"
        : "text-zinc-400 hover:text-white hover:bg-white/5 border border-transparent"
    }`}>
      <div className="flex items-center gap-3">
        {icon}
        <span className="font-medium">{label}</span>
      </div>
      {badge && (
        <span className="bg-danger text-white text-xs font-bold px-2 py-0.5 rounded-full shadow-[0_0_10px_rgba(225,29,72,0.5)]">
          {badge}
        </span>
      )}
    </Link>
  );
}

function MetricCard({ title, value, subtitle, danger, icon }: { title: string, value: string, subtitle?: string, danger?: boolean, icon: React.ReactNode }) {
  return (
    <div className="glass-panel rounded-xl p-6 border border-white/10 relative overflow-hidden group">
      <div className="absolute top-0 right-0 p-6 opacity-20 group-hover:opacity-40 transition-opacity group-hover:scale-110 duration-500">
        {icon}
      </div>
      <h3 className="text-sm text-zinc-400 font-medium mb-2">{title}</h3>
      <div className="text-3xl font-bold text-white mb-2 tracking-tight">{value}</div>
      <div className={`text-xs font-medium ${danger ? 'text-danger' : 'text-zinc-500'}`}>
        {subtitle}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    resolved: "bg-success/10 text-success border-success/20",
    fix_proposed: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    fix_approved: "bg-orange-500/10 text-orange-400 border-orange-500/20",
    fix_executing: "bg-orange-500/10 text-orange-300 border-orange-500/20",
    fix_monitoring: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    investigating: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    escalated: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    failed: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  const colorClass = map[status] || "bg-zinc-800 text-zinc-300 border-zinc-700";
  return (
    <span className={`px-2 py-1 rounded-md text-[10px] uppercase tracking-wider font-bold border ${colorClass}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}
