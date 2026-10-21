import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

import {
  Activity,
  Bot,
  Laptop,
  Server,
  ShieldAlert,
  Users,
} from "lucide-react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"
import StatCard from "../components/StatCard"
import SeverityBadge from "../components/SeverityBadge"

import { apiGetAdminOverview, type AdminOverviewResponse } from "../lib/api"

type TimeRange = "24h" | "7d" | "30d"

function AdminDashboard() {
  const [range, setRange] = useState<TimeRange>("24h")
  const [overview, setOverview] = useState<AdminOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    apiGetAdminOverview(range)
      .then((res) => {
        if (cancelled) return
        setOverview(res)
      })
      .catch(() => {
        // Leave previous state or fallback
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [range])

  const stats = overview?.stats
  const devices = overview?.devices
  const ai = overview?.ai_usage
  const orgs = overview?.organizations

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />

      <main className="min-w-0 flex-1">
        <Topbar />

        <div className="p-6 lg:p-8">
          <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-3xl font-semibold">Admin Dashboard</h1>
              <p className="mt-2 text-sm text-fg-muted">
                Complete visibility across SentinelX organizations and platform services.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="range-select" className="sr-only">
                Time range
              </label>
              <select
                id="range-select"
                value={range}
                onChange={(e) => setRange(e.target.value as TimeRange)}
                aria-label="Select time range"
                className="rounded-xl border border-white/10 bg-surface-sunken px-4 py-2 text-sm text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                <option value="24h">Last 24 Hours</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
              </select>
            </div>
          </div>

          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <StatCard
              title="Organization Assets"
              value={loading && !stats ? "..." : String(stats?.assets ?? 0)}
              description="Registered infrastructure assets"
              icon={Server}
            />

            <StatCard
              title="Security Users"
              value={loading && !stats ? "..." : String(stats?.users ?? 0)}
              description="Registered organization users"
              icon={Users}
            />

            <StatCard
              title="Open Incidents"
              value={loading && !stats ? "..." : String(stats?.open_incidents ?? 0)}
              description="Active cross-tenant incidents"
              icon={ShieldAlert}
            />

            <StatCard
              title="Security Events"
              value={loading && !stats ? "..." : String(stats?.security_events ?? 0)}
              description={`Processed events (${range})`}
              icon={Activity}
            />
          </div>

          {/* Security Overview (Severity breakdown) */}
          <section className="mt-8 rounded-2xl border border-white/10 bg-surface p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">Security Overview</h2>
                <p className="mt-1 text-sm text-fg-muted">
                  Organization-wide active incidents by severity level.
                </p>
              </div>

              <div className="flex items-center gap-3 text-xs text-fg-muted">
                <Link
                  to="/admin/soc-oversight"
                  className="rounded-control border border-line bg-surface-sunken px-3 py-1.5 font-medium text-brand-300 hover:text-brand-200"
                >
                  View SOC Oversight &rarr;
                </Link>
              </div>
            </div>

            <div className="mt-8 grid gap-4 md:grid-cols-4">
              <div className="rounded-xl bg-surface-sunken p-5">
                <SeverityBadge severity="Critical" />
                <p className="mt-4 text-3xl font-semibold">
                  {loading && !stats ? "..." : (stats?.incidents_by_severity.critical ?? 0)}
                </p>
              </div>

              <div className="rounded-xl bg-surface-sunken p-5">
                <SeverityBadge severity="High" />
                <p className="mt-4 text-3xl font-semibold">
                  {loading && !stats ? "..." : (stats?.incidents_by_severity.high ?? 0)}
                </p>
              </div>

              <div className="rounded-xl bg-surface-sunken p-5">
                <SeverityBadge severity="Medium" />
                <p className="mt-4 text-3xl font-semibold">
                  {loading && !stats ? "..." : (stats?.incidents_by_severity.medium ?? 0)}
                </p>
              </div>

              <div className="rounded-xl bg-surface-sunken p-5">
                <SeverityBadge severity="Low" />
                <p className="mt-4 text-3xl font-semibold">
                  {loading && !stats ? "..." : (stats?.incidents_by_severity.low ?? 0)}
                </p>
              </div>
            </div>
          </section>

          {/* Devices & AI Telemetry Overview */}
          <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Endpoint Monitoring Rollup */}
            <section className="rounded-2xl border border-white/10 bg-surface p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="flex items-center gap-2 text-lg font-semibold">
                    <Laptop size={18} className="text-brand-400" aria-hidden="true" />
                    Endpoint Devices
                  </h2>
                  <p className="mt-1 text-sm text-fg-muted">
                    Consented Windows agents and heartbeat telemetry.
                  </p>
                </div>
                <span className="text-xs text-fg-muted">
                  {devices?.total ?? 0} total enrolled
                </span>
              </div>

              <div className="mt-6 grid grid-cols-3 gap-3">
                <div className="rounded-xl bg-surface-sunken p-4 text-center">
                  <span className="text-xs font-medium text-success-fg">Connected</span>
                  <p className="mt-2 text-2xl font-bold text-fg-primary">
                    {devices?.connected ?? 0}
                  </p>
                  <span className="text-[11px] text-fg-muted">&le;2m heartbeat</span>
                </div>

                <div className="rounded-xl bg-surface-sunken p-4 text-center">
                  <span className="text-xs font-medium text-amber-400">Stale</span>
                  <p className="mt-2 text-2xl font-bold text-fg-primary">
                    {devices?.stale ?? 0}
                  </p>
                  <span className="text-[11px] text-fg-muted">2-10m heartbeat</span>
                </div>

                <div className="rounded-xl bg-surface-sunken p-4 text-center">
                  <span className="text-xs font-medium text-critical-fg">Offline</span>
                  <p className="mt-2 text-2xl font-bold text-fg-primary">
                    {devices?.offline ?? 0}
                  </p>
                  <span className="text-[11px] text-fg-muted">&gt;10m silent</span>
                </div>
              </div>
            </section>

            {/* AI Agent Telemetry Rollup */}
            <section className="rounded-2xl border border-white/10 bg-surface p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="flex items-center gap-2 text-lg font-semibold">
                    <Bot size={18} className="text-brand-400" aria-hidden="true" />
                    AI Intelligence &amp; Usage
                  </h2>
                  <p className="mt-1 text-sm text-fg-muted">
                    Agent runs, LLM token consumption and cost ({range}).
                  </p>
                </div>
                <span className="text-xs text-fg-muted">
                  {ai?.total_runs ?? 0} executions
                </span>
              </div>

              <div className="mt-6 grid grid-cols-3 gap-3">
                <div className="rounded-xl bg-surface-sunken p-4 text-center">
                  <span className="text-xs text-fg-muted">Total Runs</span>
                  <p className="mt-2 text-2xl font-bold text-fg-primary">
                    {ai?.total_runs ?? 0}
                  </p>
                  <span className="text-[11px] text-fg-muted">pipeline executions</span>
                </div>

                <div className="rounded-xl bg-surface-sunken p-4 text-center">
                  <span className="text-xs text-fg-muted">Tokens Used</span>
                  <p className="mt-2 text-2xl font-bold text-fg-primary">
                    {(ai?.tokens_used ?? 0).toLocaleString()}
                  </p>
                  <span className="text-[11px] text-fg-muted">prompt + completion</span>
                </div>

                <div className="rounded-xl bg-surface-sunken p-4 text-center">
                  <span className="text-xs text-fg-muted">Estimated Cost</span>
                  <p className="mt-2 text-2xl font-bold text-fg-primary">
                    ${(ai?.cost_usd ?? 0).toFixed(4)}
                  </p>
                  <span className="text-[11px] text-fg-muted">USD incurred</span>
                </div>
              </div>
            </section>
          </div>

          {/* Tenants breakdown */}
          <section className="mt-8 rounded-2xl border border-white/10 bg-surface p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">Tenant Overview</h2>
                <p className="mt-1 text-sm text-fg-muted">
                  Organization deployment modes and account health.
                </p>
              </div>

              <Link
                to="/admin/organizations"
                className="text-xs text-brand-300 hover:text-brand-200"
              >
                Manage Organizations ({orgs?.total ?? 0}) &rarr;
              </Link>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-xl bg-surface-sunken p-4">
                <p className="text-xs text-fg-muted">Managed SOC</p>
                <p className="mt-2 text-2xl font-semibold text-fg-primary">
                  {orgs?.by_mode.managed ?? 0}
                </p>
              </div>
              <div className="rounded-xl bg-surface-sunken p-4">
                <p className="text-xs text-fg-muted">In-house SOC</p>
                <p className="mt-2 text-2xl font-semibold text-fg-primary">
                  {orgs?.by_mode.in_house ?? 0}
                </p>
              </div>
              <div className="rounded-xl bg-surface-sunken p-4">
                <p className="text-xs text-fg-muted">Active</p>
                <p className="mt-2 text-2xl font-semibold text-success-fg">
                  {orgs?.by_status.active ?? 0}
                </p>
              </div>
              <div className="rounded-xl bg-surface-sunken p-4">
                <p className="text-xs text-fg-muted">Suspended / Archived</p>
                <p className="mt-2 text-2xl font-semibold text-critical-fg">
                  {(orgs?.by_status.suspended ?? 0) + (orgs?.by_status.archived ?? 0)}
                </p>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

export default AdminDashboard
