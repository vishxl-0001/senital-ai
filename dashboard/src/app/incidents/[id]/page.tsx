"use client";

import { useState, useEffect, use } from "react";
import Link from "next/link";
import {
  ShieldAlert, ArrowLeft, Clock, Activity, CheckCircle, Zap,
  AlertTriangle, XCircle, Terminal, FileText, ChevronRight
} from "lucide-react";
import { fetchIncident, approveFix, Incident } from "@/lib/api";

const STATUS_STEPS = [
  { key: "detected", label: "Detected", icon: AlertTriangle },
  { key: "investigating", label: "Investigating", icon: Activity },
  { key: "rca_complete", label: "RCA", icon: FileText },
  { key: "fix_proposed", label: "Fix Proposed", icon: Zap },
  { key: "fix_executing", label: "Executing", icon: Terminal },
  { key: "resolved", label: "Resolved", icon: CheckCircle },
];

const STATUS_ORDER = ["detected", "investigating", "rca_complete", "fix_proposed", "fix_approved", "fix_executing", "fix_monitoring", "resolved"];

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchIncident(resolvedParams.id);
        setIncident(data);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [resolvedParams.id]);

  async function handleApprove() {
    if (!incident) return;
    setApproving(true);
    try {
      await approveFix(incident.id);
      const data = await fetchIncident(resolvedParams.id);
      setIncident(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setApproving(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-zinc-500">
        <Activity size={24} className="animate-spin mr-2" /> Loading incident...
      </div>
    );
  }

  if (error || !incident) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-red-400">
        <XCircle size={24} className="mr-2" /> {error || "Incident not found"}
      </div>
    );
  }

  const currentStepIndex = STATUS_ORDER.indexOf(incident.status);
  const confidencePct = incident.rca_confidence ? Math.round(incident.rca_confidence * 100) : 0;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-white/10 glass-panel">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/incidents" className="text-zinc-400 hover:text-white transition-colors">
              <ArrowLeft size={20} />
            </Link>
            <ShieldAlert size={22} className="text-primary" />
            <h1 className="text-lg font-semibold truncate max-w-md">{incident.title}</h1>
          </div>
          {incident.status === "fix_proposed" && (
            <button
              onClick={handleApprove}
              disabled={approving}
              className="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-5 py-2 rounded-lg text-sm font-bold hover:bg-emerald-500/30 transition-colors disabled:opacity-50"
            >
              {approving ? "Approving..." : "✅ Approve Fix"}
            </button>
          )}
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Progress Bar */}
        <div className="glass-panel rounded-xl border border-white/10 p-6 mb-6">
          <div className="flex items-center justify-between">
            {STATUS_STEPS.map((step, i) => {
              const stepIndex = STATUS_ORDER.indexOf(step.key);
              const isActive = stepIndex <= currentStepIndex;
              const isCurrent = step.key === incident.status || (incident.status === "fix_approved" && step.key === "fix_proposed");
              const Icon = step.icon;
              return (
                <div key={step.key} className="flex items-center flex-1">
                  <div className="flex flex-col items-center">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center border-2 transition-all ${
                      isCurrent ? "bg-primary/20 border-primary text-primary scale-110 shadow-[0_0_15px_rgba(139,92,246,0.4)]" :
                      isActive ? "bg-primary/10 border-primary/50 text-primary" :
                      "bg-zinc-800 border-zinc-700 text-zinc-500"
                    }`}>
                      <Icon size={18} />
                    </div>
                    <span className={`text-[10px] mt-2 font-medium uppercase tracking-wider ${isActive ? "text-primary" : "text-zinc-500"}`}>
                      {step.label}
                    </span>
                  </div>
                  {i < STATUS_STEPS.length - 1 && (
                    <div className={`flex-1 h-0.5 mx-2 mt-[-20px] rounded ${isActive ? "bg-primary/40" : "bg-zinc-800"}`} />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column — Details */}
          <div className="lg:col-span-2 space-y-6">
            {/* Root Cause */}
            <Section title="🔬 Root Cause Analysis" badge={`${confidencePct}% confidence`}>
              <p className="text-zinc-300 leading-relaxed">
                {incident.root_cause || "Pending investigation..."}
              </p>
              {incident.rca_evidence && incident.rca_evidence.length > 0 && (
                <div className="mt-4 space-y-2">
                  <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Evidence</h4>
                  {incident.rca_evidence.map((ev: any, i: number) => (
                    <div key={i} className="flex items-start gap-3 bg-white/[0.02] rounded-lg p-3 border border-white/5">
                      <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                        ev.weight === "strong" ? "bg-emerald-500/10 text-emerald-400" :
                        ev.weight === "moderate" ? "bg-yellow-500/10 text-yellow-400" :
                        "bg-zinc-500/10 text-zinc-400"
                      }`}>{ev.weight || ev.type}</span>
                      <span className="text-sm text-zinc-300">{ev.description}</span>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {/* Investigation Summary */}
            {incident.investigation_summary && (
              <Section title="📋 Investigation Summary">
                <p className="text-zinc-300 leading-relaxed">{incident.investigation_summary}</p>
              </Section>
            )}

            {/* Fix Plan */}
            {incident.fix_plan && (
              <Section title="🔧 Fix Plan" badge={incident.fix_plan.risk_level}>
                <p className="text-zinc-300 mb-4">{incident.fix_plan.fix_summary}</p>
                <div className="space-y-3">
                  <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Steps</h4>
                  {(incident.fix_plan.steps || []).map((step: any, i: number) => (
                    <div key={i} className="flex items-start gap-3 bg-white/[0.02] rounded-lg p-4 border border-white/5">
                      <span className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-bold shrink-0">
                        {step.order || i + 1}
                      </span>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-white">{step.action}</p>
                        {step.command && (
                          <code className="block mt-2 text-xs bg-black/40 text-emerald-300 px-3 py-2 rounded-md font-mono">
                            {step.command}
                          </code>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Rollback Plan */}
                {incident.fix_plan.rollback_plan && (
                  <div className="mt-6 p-4 rounded-lg border border-yellow-500/20 bg-yellow-500/5">
                    <h4 className="text-xs font-bold text-yellow-400 uppercase tracking-wider mb-2">⚠️ Rollback Plan</h4>
                    <p className="text-sm text-zinc-300">{incident.fix_plan.rollback_plan.description}</p>
                  </div>
                )}
              </Section>
            )}

            {/* Fix Result */}
            {incident.fix_result && (
              <Section title={incident.fix_result.status === "success" ? "✅ Fix Result" : "❌ Fix Failed"}>
                <div className="space-y-2">
                  {(incident.fix_result.results || []).map((r: any, i: number) => (
                    <div key={i} className={`flex items-center gap-3 p-3 rounded-lg border ${
                      r.status === "success" ? "bg-emerald-500/5 border-emerald-500/20" : "bg-red-500/5 border-red-500/20"
                    }`}>
                      {r.status === "success" ? <CheckCircle size={14} className="text-emerald-400" /> : <XCircle size={14} className="text-red-400" />}
                      <span className="text-sm text-zinc-300">{r.action}</span>
                      <span className="ml-auto text-xs text-zinc-500">{r.output}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>

          {/* Right Column — Meta */}
          <div className="space-y-6">
            {/* Quick Info */}
            <div className="glass-panel rounded-xl border border-white/10 p-6">
              <h3 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-4">Details</h3>
              <div className="space-y-4">
                <MetaRow label="Status" value={incident.status.replace(/_/g, " ").toUpperCase()} />
                <MetaRow label="Severity" value={incident.severity?.toUpperCase() || "—"} />
                <MetaRow label="Source" value={incident.source || "—"} />
                <MetaRow label="Fix Type" value={incident.fix_type || "—"} />
                <MetaRow label="Approval" value={incident.fix_approval || "Pending"} />
                <MetaRow label="MTTR" value={incident.mttr_seconds ? `${incident.mttr_seconds}s` : "—"} />
              </div>
            </div>

            {/* Timestamps */}
            <div className="glass-panel rounded-xl border border-white/10 p-6">
              <h3 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-4">Timeline</h3>
              <div className="space-y-3">
                <TimelineRow label="Detected" time={incident.detected_at} />
                <TimelineRow label="Investigation Started" time={incident.investigation_started_at} />
                <TimelineRow label="RCA Complete" time={incident.rca_completed_at} />
                <TimelineRow label="Fix Started" time={incident.fix_started_at} />
                <TimelineRow label="Resolved" time={incident.resolved_at} />
              </div>
            </div>

            {/* Affected Services */}
            {incident.affected_services && incident.affected_services.length > 0 && (
              <div className="glass-panel rounded-xl border border-white/10 p-6">
                <h3 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-4">Affected Services</h3>
                <div className="flex flex-wrap gap-2">
                  {incident.affected_services.map((svc, i) => (
                    <span key={i} className="bg-primary/10 text-primary text-xs font-medium px-3 py-1 rounded-full border border-primary/20">
                      {svc}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub Components ──

function Section({ title, badge, children }: { title: string; badge?: string; children: React.ReactNode }) {
  return (
    <div className="glass-panel rounded-xl border border-white/10 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold">{title}</h2>
        {badge && (
          <span className="text-xs font-bold px-2 py-1 rounded-md bg-primary/10 text-primary border border-primary/20 uppercase">
            {badge}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-zinc-500">{label}</span>
      <span className="text-sm font-medium text-zinc-200">{value}</span>
    </div>
  );
}

function TimelineRow({ label, time }: { label: string; time: string | null }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`w-2 h-2 rounded-full shrink-0 ${time ? "bg-primary" : "bg-zinc-700"}`} />
      <div className="flex-1 flex items-center justify-between">
        <span className="text-sm text-zinc-400">{label}</span>
        <span className="text-xs text-zinc-500 font-mono">
          {time ? new Date(time).toLocaleTimeString() : "—"}
        </span>
      </div>
    </div>
  );
}
