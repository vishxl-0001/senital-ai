"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { UserButton, OrganizationSwitcher } from "@clerk/nextjs";
import {
  ShieldAlert, Activity, Terminal, Settings, FileText,
  LayoutDashboard, Globe, Plus, Zap, ShieldCheck, Loader2, Sparkles, Trash2, Power
} from "lucide-react";
import {
  fetchPolicies, createPolicy, seedDefaultPolicies, updatePolicy, deletePolicy, Policy
} from "@/lib/api";

const ACTION_TYPES = [
  { value: "restart_pod", label: "Restart Pod" },
  { value: "rollback_deployment", label: "Rollback Deployment" },
  { value: "scale_horizontal", label: "Scale Horizontally" },
  { value: "clear_disk", label: "Clear Disk" },
  { value: "database_operation", label: "Database Operation" },
];

export default function PoliciesPage() {
  const [mounted, setMounted] = useState(false);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // New policy form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [actionType, setActionType] = useState(ACTION_TYPES[0].value);
  const [autoApprove, setAutoApprove] = useState(false);
  const [timeout, setTimeoutMin] = useState(15);

  const loadPolicies = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchPolicies();
      setPolicies(data.policies || []);
      setError(null);
    } catch (err: any) {
      setError(err.message);
      setPolicies([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    loadPolicies();
  }, [loadPolicies]);

  const handleSeed = async () => {
    setSeeding(true);
    try {
      await seedDefaultPolicies();
      await loadPolicies();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSeeding(false);
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      await createPolicy({
        name,
        description: description || undefined,
        action_type: actionType,
        auto_approve: autoApprove,
        approval_timeout_minutes: timeout,
      });
      setName("");
      setDescription("");
      setAutoApprove(false);
      setTimeoutMin(15);
      setShowForm(false);
      await loadPolicies();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleToggle = async (p: Policy) => {
    // Optimistic flip; revert on failure.
    setPolicies((prev) => prev.map((x) => (x.id === p.id ? { ...x, enabled: !x.enabled } : x)));
    try {
      await updatePolicy(p.id, { enabled: !p.enabled });
    } catch (err: any) {
      setError(err.message);
      setPolicies((prev) => prev.map((x) => (x.id === p.id ? { ...x, enabled: p.enabled } : x)));
    }
  };

  const handleDelete = async (id: string) => {
    const prev = policies;
    setPolicies((cur) => cur.filter((x) => x.id !== id));
    try {
      await deletePolicy(id);
    } catch (err: any) {
      setError(err.message);
      setPolicies(prev);
    }
  };

  if (!mounted) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar active="Policies" />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        <header className="h-16 flex items-center justify-between px-8 border-b border-white/10 glass-panel z-10">
          <div className="flex items-center gap-3">
            <Terminal size={22} className="text-primary" />
            <h1 className="text-xl font-semibold">Auto-Fix Policies</h1>
            <span className="text-sm text-zinc-500">
              {policies.length} polic{policies.length !== 1 ? "ies" : "y"}
            </span>
          </div>
          <button
            onClick={() => setShowForm((s) => !s)}
            className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
          >
            <Plus size={16} /> New Policy
          </button>
        </header>

        <div className="flex-1 overflow-auto p-8 z-0">
          <div className="max-w-4xl mx-auto space-y-6">

            <p className="text-sm text-zinc-400">
              Policies decide what Sentinel can fix automatically vs. what needs human approval.
              An <span className="text-success font-medium">auto-approve</span> policy lets the AI
              act without waiting; otherwise a fix is proposed and held for review.
            </p>

            {error && (
              <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                ⚠️ {error?.includes("403")
                  ? "No active organization — pick or create one with the organization switcher in the sidebar."
                  : `${error} — Make sure the backend is running on port 8000`}
              </div>
            )}

            {/* Create form */}
            {showForm && (
              <div className="glass-panel rounded-xl p-6 border border-primary/20 space-y-4">
                <h2 className="text-lg font-medium">Create Policy</h2>
                <input
                  type="text"
                  placeholder="Policy name (e.g. Auto-restart crashed pods)"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-surface border border-white/10 rounded-md px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
                />
                <textarea
                  placeholder="Description (optional)"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="w-full bg-surface border border-white/10 rounded-md px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors resize-none"
                />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Action Type</label>
                    <select
                      value={actionType}
                      onChange={(e) => setActionType(e.target.value)}
                      className="w-full bg-surface border border-white/10 rounded-md px-4 py-2 text-sm focus:outline-none focus:border-primary"
                    >
                      {ACTION_TYPES.map((a) => (
                        <option key={a.value} value={a.value}>{a.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">
                      Approval timeout (minutes)
                    </label>
                    <input
                      type="number"
                      min={0}
                      value={timeout}
                      onChange={(e) => setTimeoutMin(Number(e.target.value))}
                      className="w-full bg-surface border border-white/10 rounded-md px-4 py-2 text-sm focus:outline-none focus:border-primary"
                    />
                  </div>
                </div>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoApprove}
                    onChange={(e) => setAutoApprove(e.target.checked)}
                    className="w-4 h-4 accent-primary"
                  />
                  <span className="text-sm text-zinc-300">
                    Auto-approve — let the AI execute this fix without human review
                  </span>
                </label>
                <div className="flex gap-3">
                  <button
                    onClick={handleCreate}
                    disabled={creating || !name.trim()}
                    className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
                  >
                    {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                    Create
                  </button>
                  <button
                    onClick={() => setShowForm(false)}
                    className="text-zinc-400 hover:text-white px-4 py-2 rounded-md text-sm transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Policy list */}
            {loading && policies.length === 0 ? (
              <div className="text-center py-16 text-zinc-500">
                <Activity size={24} className="mx-auto mb-2 animate-spin" />
                Loading policies...
              </div>
            ) : policies.length === 0 ? (
              <div className="glass-panel rounded-xl border border-white/10 p-12 text-center">
                <ShieldCheck size={40} className="mx-auto mb-4 text-zinc-600" />
                <h3 className="text-lg font-medium mb-2">No policies yet</h3>
                <p className="text-sm text-zinc-500 mb-6 max-w-md mx-auto">
                  Seed a sensible starter set (auto-restart, auto-scale, rollback, disk cleanup,
                  and manual DB ops) or create your own.
                </p>
                <button
                  onClick={handleSeed}
                  disabled={seeding}
                  className="bg-primary/10 text-primary border border-primary/20 px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-primary/20 transition-colors inline-flex items-center gap-2 disabled:opacity-50"
                >
                  {seeding ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                  Seed Default Policies
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {policies.map((p) => (
                  <div
                    key={p.id}
                    className={`glass-panel rounded-xl border border-white/10 p-5 flex items-start justify-between gap-4 ${
                      !p.enabled ? "opacity-60" : ""
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-medium text-white">{p.name}</h3>
                        {p.auto_approve ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] uppercase tracking-wider font-bold border bg-success/10 text-success border-success/20">
                            <Zap size={10} /> Auto
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] uppercase tracking-wider font-bold border bg-yellow-500/10 text-yellow-400 border-yellow-500/20">
                            <ShieldCheck size={10} /> Manual
                          </span>
                        )}
                        {!p.enabled && (
                          <span className="px-2 py-0.5 rounded-md text-[10px] uppercase tracking-wider font-bold border bg-zinc-700/40 text-zinc-400 border-zinc-600/40">
                            Disabled
                          </span>
                        )}
                      </div>
                      {p.description && (
                        <p className="text-sm text-zinc-400 mb-2">{p.description}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
                        <code className="bg-white/5 px-2 py-0.5 rounded">{p.action_type}</code>
                        {!p.auto_approve && (
                          <span>Timeout: {p.approval_timeout_minutes}m</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => handleToggle(p)}
                        title={p.enabled ? "Disable policy" : "Enable policy"}
                        className={`p-2 rounded transition-colors ${
                          p.enabled
                            ? "text-success hover:bg-success/10"
                            : "text-zinc-500 hover:text-white hover:bg-white/5"
                        }`}
                      >
                        <Power size={16} />
                      </button>
                      <button
                        onClick={() => handleDelete(p.id)}
                        title="Delete policy"
                        className="p-2 text-zinc-500 hover:text-danger hover:bg-danger/10 rounded transition-colors"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// ── Shared Sidebar ──

function Sidebar({ active }: { active: string }) {
  const items = [
    { icon: <LayoutDashboard size={20} />, label: "Dashboard", href: "/" },
    { icon: <Activity size={20} />, label: "Incidents", href: "/incidents" },
    { icon: <Globe size={20} />, label: "Monitors", href: "/monitors" },
    { icon: <Terminal size={20} />, label: "Policies", href: "/policies" },
    { icon: <FileText size={20} />, label: "Runbooks", href: "/runbooks" },
    { icon: <Settings size={20} />, label: "Settings", href: "/settings" },
  ];
  return (
    <aside className="w-64 border-r border-white/10 glass-panel flex flex-col z-10">
      <div className="h-16 flex items-center px-6 border-b border-white/10">
        <div className="flex items-center gap-2 text-primary font-bold text-xl tracking-tight">
          <ShieldAlert size={24} className="text-primary" />
          <span>Sentinel<span className="text-white">AI</span></span>
        </div>
      </div>
      <nav className="flex-1 py-6 px-4 space-y-2">
        {items.map((it) => (
          <Link
            key={it.label}
            href={it.href}
            className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 ${
              it.label === active
                ? "bg-primary/10 text-primary border border-primary/20"
                : "text-zinc-400 hover:text-white hover:bg-white/5 border border-transparent"
            }`}
          >
            {it.icon}
            <span className="font-medium">{it.label}</span>
          </Link>
        ))}
      </nav>
      <div className="p-4 border-t border-white/10 space-y-2">
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
  );
}
