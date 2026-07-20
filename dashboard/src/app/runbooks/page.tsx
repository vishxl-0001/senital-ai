"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { UserButton, OrganizationSwitcher } from "@clerk/nextjs";
import {
  ShieldAlert, Activity, Terminal, Settings, FileText,
  LayoutDashboard, Globe, Plus, Loader2, Trash2, BookOpen, X
} from "lucide-react";
import {
  fetchRunbooks, createRunbook, deleteRunbook, Runbook
} from "@/lib/api";

export default function RunbooksPage() {
  const [mounted, setMounted] = useState(false);
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [trigger, setTrigger] = useState("");
  const [steps, setSteps] = useState<string[]>([""]);

  const loadRunbooks = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchRunbooks();
      setRunbooks(data.runbooks || []);
      setError(null);
    } catch (err: any) {
      setError(err.message);
      setRunbooks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    loadRunbooks();
  }, [loadRunbooks]);

  const resetForm = () => {
    setName("");
    setDescription("");
    setTrigger("");
    setSteps([""]);
    setShowForm(false);
  };

  const handleCreate = async () => {
    const cleanSteps = steps.map((s) => s.trim()).filter(Boolean);
    if (!name.trim() || cleanSteps.length === 0) return;
    setCreating(true);
    try {
      await createRunbook({
        name,
        description: description || undefined,
        trigger_pattern: trigger || undefined,
        steps: cleanSteps.map((action) => ({ action })),
      });
      resetForm();
      await loadRunbooks();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteRunbook(id);
      setRunbooks((prev) => prev.filter((r) => r.id !== id));
    } catch (err: any) {
      setError(err.message);
    }
  };

  const updateStep = (i: number, value: string) => {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? value : s)));
  };
  const addStep = () => setSteps((prev) => [...prev, ""]);
  const removeStep = (i: number) =>
    setSteps((prev) => (prev.length > 1 ? prev.filter((_, idx) => idx !== i) : prev));

  if (!mounted) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar active="Runbooks" />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        <header className="h-16 flex items-center justify-between px-8 border-b border-white/10 glass-panel z-10">
          <div className="flex items-center gap-3">
            <FileText size={22} className="text-primary" />
            <h1 className="text-xl font-semibold">Runbooks</h1>
            <span className="text-sm text-zinc-500">
              {runbooks.length} runbook{runbooks.length !== 1 ? "s" : ""}
            </span>
          </div>
          <button
            onClick={() => setShowForm((s) => !s)}
            className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
          >
            <Plus size={16} /> New Runbook
          </button>
        </header>

        <div className="flex-1 overflow-auto p-8 z-0">
          <div className="max-w-4xl mx-auto space-y-6">

            <p className="text-sm text-zinc-400">
              Runbooks capture your team's known-good fix procedures. Give each one a trigger
              pattern (matched against the AI's root-cause analysis) and an ordered list of steps.
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
                <h2 className="text-lg font-medium">Create Runbook</h2>
                <input
                  type="text"
                  placeholder="Name (e.g. Recover payment-service)"
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
                <input
                  type="text"
                  placeholder="Trigger pattern (optional, e.g. CrashLoopBackOff)"
                  value={trigger}
                  onChange={(e) => setTrigger(e.target.value)}
                  className="w-full bg-surface border border-white/10 rounded-md px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
                />
                <div>
                  <label className="text-xs text-zinc-500 mb-2 block">Steps (ordered)</label>
                  <div className="space-y-2">
                    {steps.map((step, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-xs text-zinc-500 w-5 text-right">{i + 1}.</span>
                        <input
                          type="text"
                          placeholder={`Step ${i + 1} (e.g. kubectl rollout restart deploy/payment-service)`}
                          value={step}
                          onChange={(e) => updateStep(i, e.target.value)}
                          className="flex-1 bg-surface border border-white/10 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:border-primary transition-colors"
                        />
                        <button
                          onClick={() => removeStep(i)}
                          disabled={steps.length === 1}
                          className="p-2 text-zinc-500 hover:text-danger disabled:opacity-30 transition-colors"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={addStep}
                    className="mt-2 text-xs text-primary hover:text-primary/80 transition-colors inline-flex items-center gap-1"
                  >
                    <Plus size={14} /> Add step
                  </button>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={handleCreate}
                    disabled={creating || !name.trim() || steps.every((s) => !s.trim())}
                    className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
                  >
                    {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                    Create
                  </button>
                  <button
                    onClick={resetForm}
                    className="text-zinc-400 hover:text-white px-4 py-2 rounded-md text-sm transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Runbook list */}
            {loading && runbooks.length === 0 ? (
              <div className="text-center py-16 text-zinc-500">
                <Activity size={24} className="mx-auto mb-2 animate-spin" />
                Loading runbooks...
              </div>
            ) : runbooks.length === 0 ? (
              <div className="glass-panel rounded-xl border border-white/10 p-12 text-center">
                <BookOpen size={40} className="mx-auto mb-4 text-zinc-600" />
                <h3 className="text-lg font-medium mb-2">No runbooks yet</h3>
                <p className="text-sm text-zinc-500 max-w-md mx-auto">
                  Create your first runbook to document a repeatable fix procedure.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {runbooks.map((rb) => (
                  <div
                    key={rb.id}
                    className="glass-panel rounded-xl border border-white/10 p-5"
                  >
                    <div className="flex items-start justify-between gap-4 mb-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-1">
                          <h3 className="font-medium text-white">{rb.name}</h3>
                          {!rb.enabled && (
                            <span className="px-2 py-0.5 rounded-md text-[10px] uppercase tracking-wider font-bold border bg-zinc-700/40 text-zinc-400 border-zinc-600/40">
                              Disabled
                            </span>
                          )}
                        </div>
                        {rb.description && (
                          <p className="text-sm text-zinc-400">{rb.description}</p>
                        )}
                      </div>
                      <button
                        onClick={() => handleDelete(rb.id)}
                        className="p-2 text-zinc-500 hover:text-danger hover:bg-danger/10 rounded transition-colors shrink-0"
                        title="Delete runbook"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>

                    {rb.trigger_pattern && (
                      <div className="mb-3 text-xs text-zinc-500">
                        Trigger: <code className="bg-white/5 px-2 py-0.5 rounded">{rb.trigger_pattern}</code>
                      </div>
                    )}

                    <ol className="space-y-1.5">
                      {rb.steps.map((step, i) => (
                        <li key={i} className="flex items-start gap-3 text-sm">
                          <span className="text-xs text-primary font-mono mt-0.5 w-5 text-right shrink-0">{i + 1}.</span>
                          <code className="bg-black/30 px-2 py-1 rounded text-xs text-zinc-300 flex-1 break-all">
                            {step.action}
                          </code>
                        </li>
                      ))}
                    </ol>

                    <div className="flex items-center gap-4 mt-4 pt-3 border-t border-white/5 text-xs text-zinc-500">
                      <span>Used {rb.times_used}×</span>
                      {rb.times_used > 0 && (
                        <span>Success rate {Math.round(rb.success_rate * 100)}%</span>
                      )}
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
