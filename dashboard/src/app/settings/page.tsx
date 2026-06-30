"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { listApiKeys, createApiKey as createApiKeyRequest } from "@/lib/api";
import {
  ShieldAlert, Activity, Terminal, Settings, FileText,
  LayoutDashboard, Key, Plus, Trash2, Copy, Check
} from "lucide-react";

export default function SettingsPage() {
  const [mounted, setMounted] = useState(false);
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [generatedKey, setGeneratedKey] = useState("");
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);

  // The backend derives the tenant from the verified Clerk session JWT — the
  // client never sends tenant_id. listApiKeys()/createApiKey() attach the
  // session token via the shared authed API client.
  const loadApiKeys = async () => {
    try {
      const data = await listApiKeys();
      setApiKeys(data.api_keys || []);
    } catch (err) {
      console.error("Failed to fetch API keys", err);
    }
  };

  useEffect(() => {
    setMounted(true);
    loadApiKeys();
  }, []);

  const createApiKey = async () => {
    if (!newKeyName.trim()) return;
    setLoading(true);
    try {
      const data = await createApiKeyRequest(newKeyName);
      setGeneratedKey(data.api_key);
      setNewKeyName("");
      loadApiKeys(); // Refresh list
    } catch (err) {
      console.error("Failed to create API key", err);
    }
    setLoading(false);
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(generatedKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!mounted) return null;

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
          <NavItem icon={<LayoutDashboard size={20} />} label="Dashboard" href="/" />
          <NavItem icon={<Activity size={20} />} label="Incidents" href="/incidents" />
          <NavItem icon={<Terminal size={20} />} label="Policies" href="#" />
          <NavItem icon={<FileText size={20} />} label="Runbooks" href="#" />
          <NavItem icon={<Settings size={20} />} label="Settings" href="/settings" active />
        </nav>
        
        <div className="p-4 border-t border-white/10">
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
        <header className="h-16 flex items-center justify-between px-8 border-b border-white/10 glass-panel z-10">
          <h1 className="text-xl font-semibold">Settings / Integrations</h1>
        </header>

        <div className="flex-1 overflow-auto p-8 z-0">
          <div className="max-w-4xl mx-auto space-y-8">
            
            {/* API Keys Section */}
            <div className="glass-panel rounded-xl p-6 border border-white/10">
              <div className="flex items-center gap-3 mb-6">
                <Key className="text-primary" size={24} />
                <h2 className="text-lg font-medium">API Keys</h2>
              </div>
              <p className="text-sm text-zinc-400 mb-6">
                Use API Keys to authenticate external services like Prometheus or Datadog when sending webhook alerts to Sentinel AI.
              </p>

              {/* Generate New Key */}
              <div className="flex gap-4 mb-8 p-4 bg-surface rounded-lg border border-white/5">
                <input
                  type="text"
                  placeholder="Key Name (e.g., Production Prometheus)"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  className="flex-1 bg-background border border-white/10 rounded-md px-4 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
                />
                <button 
                  onClick={createApiKey}
                  disabled={loading || !newKeyName.trim()}
                  className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
                >
                  <Plus size={16} /> Generate Key
                </button>
              </div>

              {/* Show Generated Key (One Time) */}
              {generatedKey && (
                <div className="mb-8 p-4 bg-success/10 border border-success/30 rounded-lg">
                  <h3 className="text-success font-medium text-sm mb-2 flex items-center gap-2">
                    <Check size={16} /> Key Generated Successfully!
                  </h3>
                  <p className="text-xs text-zinc-400 mb-3">
                    Please copy this key now. You will not be able to see it again.
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-black/50 px-4 py-2 rounded text-sm text-zinc-300 font-mono select-all">
                      {generatedKey}
                    </code>
                    <button 
                      onClick={copyToClipboard}
                      className="p-2 bg-white/10 hover:bg-white/20 rounded text-white transition-colors"
                    >
                      {copied ? <Check size={16} className="text-success" /> : <Copy size={16} />}
                    </button>
                  </div>
                </div>
              )}

              {/* List of Keys */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-zinc-300 mb-4 border-b border-white/10 pb-2">Active Keys</h3>
                {apiKeys.length === 0 ? (
                  <p className="text-sm text-zinc-500 italic">No API keys found.</p>
                ) : (
                  apiKeys.map((key) => (
                    <div key={key.id} className="flex items-center justify-between p-4 rounded-lg bg-surface border border-white/5">
                      <div>
                        <div className="font-medium text-sm text-white mb-1">{key.name}</div>
                        <div className="flex items-center gap-4 text-xs text-zinc-500">
                          <code className="font-mono bg-black/30 px-2 py-0.5 rounded">{key.prefix}</code>
                          <span>Created: {new Date(key.created_at).toLocaleDateString()}</span>
                          {key.last_used_at && <span>Last used: {new Date(key.last_used_at).toLocaleDateString()}</span>}
                        </div>
                      </div>
                      <button className="p-2 text-zinc-500 hover:text-danger hover:bg-danger/10 rounded transition-colors">
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))
                )}
              </div>

            </div>

            {/* Integration Guide Section */}
            <div className="glass-panel rounded-xl p-6 border border-white/10">
              <h2 className="text-lg font-medium mb-4">Webhook Integration Guide</h2>
              <div className="space-y-4 text-sm text-zinc-300">
                <p>Configure your AlertManager or monitoring tool to send POST requests to:</p>
                <code className="block bg-surface border border-white/10 p-3 rounded font-mono text-primary/90">
                  http://your-sentinel-instance.com/api/v1/alerts/webhook/prometheus
                </code>
                <p>Make sure to include the API key in the headers:</p>
                <code className="block bg-surface border border-white/10 p-3 rounded font-mono text-zinc-400">
                  X-API-Key: sentinel_abc123...
                </code>
              </div>
            </div>

          </div>
        </div>
      </main>
    </div>
  );
}

// NavItem Component
function NavItem({ icon, label, href = "#", active = false }: { icon: React.ReactNode, label: string, href?: string, active?: boolean }) {
  return (
    <Link href={href} className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 ${
      active 
        ? "bg-primary/10 text-primary border border-primary/20" 
        : "text-zinc-400 hover:text-white hover:bg-white/5 border border-transparent"
    }`}>
      {icon}
      <span className="font-medium">{label}</span>
    </Link>
  );
}
