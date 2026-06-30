"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { 
  ShieldAlert, Activity, CheckCircle, Clock, 
  Terminal, Settings, FileText, LayoutDashboard,
  Bell, Search, User, ArrowRight, Zap
} from "lucide-react";
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, 
  Tooltip, ResponsiveContainer, BarChart, Bar 
} from "recharts";

// Mock Data
const metricsData = [
  { time: "00:00", incidents: 2, resolved: 2 },
  { time: "04:00", incidents: 4, resolved: 3 },
  { time: "08:00", incidents: 8, resolved: 7 },
  { time: "12:00", incidents: 15, resolved: 12 },
  { time: "16:00", incidents: 12, resolved: 14 },
  { time: "20:00", incidents: 5, resolved: 6 },
];

const mockIncidents = [
  { id: "INC-1042", title: "API Gateway Latency Spike", status: "Resolved", time: "10 mins ago", fix: "Auto-scaled replicas", type: "auto" },
  { id: "INC-1043", title: "Database CPU Exhaustion", status: "Fix Proposed", time: "25 mins ago", fix: "Pending human approval", type: "manual" },
  { id: "INC-1044", title: "Payment Webhook Failures", status: "Investigating", time: "1 hr ago", fix: "Analyzing logs...", type: "pending" },
  { id: "INC-1041", title: "Redis OOM Killed", status: "Resolved", time: "3 hrs ago", fix: "Cleared temp cache", type: "auto" },
];

export default function Dashboard() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

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
          <NavItem icon={<LayoutDashboard size={20} />} label="Dashboard" href="/" active />
          <NavItem icon={<Activity size={20} />} label="Incidents" href="/incidents" badge="2" />
          <NavItem icon={<Terminal size={20} />} label="Policies" href="#" />
          <NavItem icon={<FileText size={20} />} label="Runbooks" href="#" />
          <NavItem icon={<Settings size={20} />} label="Settings" href="/settings" />
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
        
        {/* Header */}
        <header className="h-16 flex items-center justify-between px-8 border-b border-white/10 glass-panel z-10">
          <h1 className="text-xl font-semibold">Overview</h1>
          <div className="flex items-center gap-6">
            <div className="relative">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input 
                type="text" 
                placeholder="Search incidents..." 
                className="bg-surface border border-white/10 rounded-full pl-10 pr-4 py-1.5 text-sm w-64 focus:outline-none focus:border-primary transition-colors"
              />
            </div>
            <button className="relative text-zinc-400 hover:text-white transition-colors">
              <Bell size={20} />
              <span className="absolute -top-1 -right-1 w-2 h-2 bg-danger rounded-full shadow-[0_0_8px_rgba(225,29,72,0.8)]"></span>
            </button>
          </div>
        </header>

        {/* Scrollable Area */}
        <div className="flex-1 overflow-auto p-8 z-0">
          
          {/* Top Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <MetricCard 
              title="Mean Time To Resolve" 
              value="2m 45s" 
              trend="-12%" 
              trendPositive 
              icon={<Clock size={20} className="text-blue-400" />} 
            />
            <MetricCard 
              title="Auto-Fix Rate" 
              value="84.2%" 
              trend="+5.1%" 
              trendPositive 
              icon={<Zap size={20} className="text-yellow-400" />} 
            />
            <MetricCard 
              title="Open Incidents" 
              value="2" 
              trend="Requires attention" 
              trendPositive={false} 
              icon={<Activity size={20} className="text-danger" />} 
            />
            <MetricCard 
              title="Incidents Prevented" 
              value="1,402" 
              trend="Last 30 days" 
              trendPositive 
              icon={<ShieldAlert size={20} className="text-success" />} 
            />
          </div>

          {/* Charts & Lists Row */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-8">
            
            {/* Main Chart */}
            <div className="xl:col-span-2 glass-panel rounded-xl p-6 border border-white/10">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium">Incident Volume (24h)</h2>
                <select className="bg-surface text-sm border border-white/10 rounded-md px-3 py-1 outline-none">
                  <option>All Services</option>
                  <option>Production</option>
                  <option>Staging</option>
                </select>
              </div>
              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={metricsData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
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
                    <YAxis stroke="#52525b" fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#18181b', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '8px' }}
                      itemStyle={{ color: '#fff' }}
                    />
                    <Area type="monotone" dataKey="incidents" stroke="var(--color-danger)" fillOpacity={1} fill="url(#colorIncidents)" strokeWidth={2} />
                    <Area type="monotone" dataKey="resolved" stroke="var(--color-primary)" fillOpacity={1} fill="url(#colorResolved)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Active Incidents List */}
            <div className="glass-panel rounded-xl border border-white/10 flex flex-col">
              <div className="p-6 border-b border-white/10 flex items-center justify-between">
                <h2 className="text-lg font-medium">Recent Activity</h2>
                <button className="text-sm text-primary hover:text-primary/80 transition-colors">View All</button>
              </div>
              <div className="flex-1 overflow-auto p-2">
                {mockIncidents.map((inc) => (
                  <div key={inc.id} className="p-4 rounded-lg hover:bg-white/5 transition-colors group cursor-pointer border border-transparent hover:border-white/5">
                    <div className="flex justify-between items-start mb-2">
                      <span className="text-sm font-bold text-zinc-300">{inc.id}</span>
                      <span className="text-xs text-zinc-500">{inc.time}</span>
                    </div>
                    <h3 className="font-medium text-white mb-3 text-sm truncate">{inc.title}</h3>
                    <div className="flex items-center justify-between">
                      <StatusBadge status={inc.status} />
                      <div className="flex items-center text-xs text-zinc-400 group-hover:text-primary transition-colors">
                        <span className="mr-1">{inc.fix}</span>
                        {inc.type === 'auto' ? <Zap size={12} className="text-yellow-400"/> : <ArrowRight size={14} />}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}

// Subcomponents

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

function MetricCard({ title, value, trend, trendPositive, icon }: any) {
  return (
    <div className="glass-panel rounded-xl p-6 border border-white/10 relative overflow-hidden group">
      <div className="absolute top-0 right-0 p-6 opacity-20 group-hover:opacity-40 transition-opacity group-hover:scale-110 duration-500">
        {icon}
      </div>
      <h3 className="text-sm text-zinc-400 font-medium mb-2">{title}</h3>
      <div className="text-3xl font-bold text-white mb-2 tracking-tight">{value}</div>
      <div className={`text-xs font-medium ${trendPositive ? 'text-success' : 'text-danger'}`}>
        {trend}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  let colorClass = "bg-zinc-800 text-zinc-300 border-zinc-700";
  
  if (status === "Resolved") colorClass = "bg-success/10 text-success border-success/20";
  if (status === "Fix Proposed") colorClass = "bg-yellow-500/10 text-yellow-500 border-yellow-500/20";
  if (status === "Investigating") colorClass = "bg-blue-500/10 text-blue-400 border-blue-500/20";
  
  return (
    <span className={`px-2 py-1 rounded-md text-[10px] uppercase tracking-wider font-bold border ${colorClass}`}>
      {status}
    </span>
  );
}
