import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, RefreshCw, ShieldCheck } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"

import {
  apiGetAdminSecurityOverview,
  ApiError,
  type AdminSecurityOverviewResponse,
} from "../../../lib/api"

type TimeRange = "24h" | "7d" | "30d"

function ageLabel(iso: string | null): string {
  if (!iso) return "N/A"
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export default function AdminSecurityOverview() {
  const toast = useToast()

  const [range, setRange] = useState<TimeRange>("24h")
  const [data, setData] = useState<AdminSecurityOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(() => new Date())

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGetAdminSecurityOverview(range)
      setData(res)
      setLastUpdated(new Date())
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to load security overview.", {
        tone: "danger",
      })
    } finally {
      setLoading(false)
    }
  }, [range, toast])

  useEffect(() => {
    reload()
  }, [reload])

  type ActiveIncidentRow = NonNullable<AdminSecurityOverviewResponse["active_incidents"]>[number]
  type RecentAlertRow = NonNullable<AdminSecurityOverviewResponse["recent_alerts"]>[number]
  type OrgPostureRow = NonNullable<AdminSecurityOverviewResponse["organizations"]>[number]

  const incidentColumns: DataTableColumn<ActiveIncidentRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      render: (inc) => <SeverityBadge severity={inc.severity} showIcon />,
    },
    {
      key: "title",
      header: "Incident",
      render: (inc) => (
        <div>
          <p className="font-medium text-fg-primary">{inc.title}</p>
          <span className="font-mono text-[11px] text-fg-muted uppercase">{inc.status}</span>
        </div>
      ),
    },
    {
      key: "organization",
      header: "Organization",
      render: (inc) => (
        <Link
          to={`/admin/organizations/${inc.organization_id}`}
          className="text-xs font-medium text-brand-300 hover:underline"
        >
          {inc.organization_name}
        </Link>
      ),
    },
    {
      key: "opened_at",
      header: "Opened",
      width: "120px",
      render: (inc) => (
        <span className="text-xs text-fg-muted">{ageLabel(inc.opened_at)}</span>
      ),
    },
  ]

  const alertColumns: DataTableColumn<RecentAlertRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      render: (alt) => <SeverityBadge severity={alt.severity} showIcon />,
    },
    {
      key: "title",
      header: "Alert",
      render: (alt) => (
        <div>
          <p className="font-medium text-fg-primary">{alt.title}</p>
          <span className="font-mono text-[11px] text-fg-muted">{alt.asset_hostname}</span>
        </div>
      ),
    },
    {
      key: "organization",
      header: "Organization",
      render: (alt) => (
        <Link
          to={`/admin/organizations/${alt.organization_id}`}
          className="text-xs font-medium text-brand-300 hover:underline"
        >
          {alt.organization_name}
        </Link>
      ),
    },
    {
      key: "seen",
      header: "First seen",
      width: "120px",
      render: (alt) => <span className="text-xs text-fg-muted">{ageLabel(alt.first_seen_at)}</span>,
    },
  ]

  const orgColumns: DataTableColumn<OrgPostureRow>[] = [
    {
      key: "name",
      header: "Organization",
      render: (o) => (
        <Link
          to={`/admin/organizations/${o.id}`}
          className="font-medium text-fg-primary hover:text-brand-300 hover:underline"
        >
          {o.name}
        </Link>
      ),
    },
    {
      key: "soc_mode",
      header: "SOC Mode",
      width: "120px",
      render: (o) => (
        <Badge tone={o.soc_mode === "managed" ? "brand" : "neutral"} className="capitalize">
          {o.soc_mode.replace("_", "-")}
        </Badge>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "100px",
      render: (o) => (
        <Badge tone={o.status === "active" ? "success" : "neutral"} className="capitalize">
          {o.status}
        </Badge>
      ),
    },
    {
      key: "assets",
      header: "Assets",
      width: "90px",
      render: (o) => <span className="font-mono text-xs">{o.asset_count}</span>,
    },
    {
      key: "devices",
      header: "Devices",
      width: "90px",
      render: (o) => <span className="font-mono text-xs">{o.device_count}</span>,
    },
    {
      key: "action",
      header: "",
      width: "60px",
      render: (o) => (
        <Link
          to={`/admin/organizations/${o.id}`}
          className="text-xs text-brand-300 hover:underline"
          title="View organization detail"
        >
          View &rarr;
        </Link>
      ),
    },
  ]

  const kpis = data?.kpis

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">Security Overview</h1>
              <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
                Cross-tenant security posture, active threats, and tenant defense readiness. Last updated{" "}
                <time dateTime={lastUpdated.toISOString()} title={lastUpdated.toString()}>
                  {lastUpdated.toLocaleTimeString()}
                </time>
              </p>
            </div>
            <div className="flex items-center gap-3">
              <label htmlFor="sec-range-select" className="sr-only">
                Time range
              </label>
              <select
                id="sec-range-select"
                value={range}
                onChange={(e) => setRange(e.target.value as TimeRange)}
                aria-label="Select time range"
                className="rounded-control border border-line bg-surface px-3 py-1.5 text-xs text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                <option value="24h">Last 24 Hours</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
              </select>
              <IconButton icon={RefreshCw} label="Refresh security overview" onClick={reload} />
            </div>
          </div>

          {/* Quick Nav Banner to SOC Oversight */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-brand-500/20 bg-brand-500/10 p-4 text-brand-200">
            <div className="flex items-center gap-3">
              <ShieldCheck size={20} className="shrink-0 text-brand-400" />
              <div>
                <p className="text-sm font-semibold text-brand-100">
                  Platform SOC Triage & Workload Oversight
                </p>
                <p className="mt-0.5 text-xs text-brand-300/80">
                  Review analyst workload balancing, SLA timers, and cross-tenant unassigned alert queues.
                </p>
              </div>
            </div>
            <Link
              to="/admin/soc-oversight"
              className="inline-flex items-center gap-1.5 rounded-control bg-brand-500 px-3 py-1.5 text-xs font-semibold text-canvas transition-colors hover:bg-brand-400"
            >
              Open SOC Oversight <ArrowRight size={13} />
            </Link>
          </div>

          {/* Key Metrics */}
          <section aria-label="Key security metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            {loading && !data ? (
              Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
            ) : (
              <>
                <KpiCard
                  label="Critical Threats"
                  value={String(kpis?.critical_incidents ?? 0)}
                  tone={(kpis?.critical_incidents ?? 0) > 0 ? "critical" : "neutral"}
                />
                <KpiCard
                  label="Active Incidents"
                  value={String(kpis?.total_active_incidents ?? 0)}
                  tone={(kpis?.total_active_incidents ?? 0) > 0 ? "high" : "neutral"}
                />
                <KpiCard
                  label="Open Alerts"
                  value={String(kpis?.open_alerts ?? 0)}
                  tone={(kpis?.open_alerts ?? 0) > 0 ? "medium" : "neutral"}
                />
                <KpiCard
                  label="Mean Time To Ack"
                  value={`${kpis?.mtta_minutes ?? 0}m`}
                  tone="neutral"
                />
                <KpiCard
                  label="Events Processed"
                  value={String(kpis?.security_events_in_range ?? 0)}
                  tone="neutral"
                />
                <KpiCard
                  label="Protected Devices"
                  value={String(kpis?.connected_devices ?? 0)}
                  tone="neutral"
                />
              </>
            )}
          </section>

          {/* Incident Severity Breakdown */}
          <section aria-label="Incident severity breakdown" className="rounded-card border border-line bg-surface p-6">
            <h2 className="text-sm font-semibold text-fg-primary">Active Incidents by Severity</h2>
            <p className="mt-1 text-xs text-fg-muted">Real-time breakdown of open threat investigations across tenants.</p>
            <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4">
                <SeverityBadge severity="Critical" />
                <p className="mt-3 text-2xl font-bold text-red-300">
                  {loading && !data ? "..." : (data?.incidents_by_severity.critical ?? 0)}
                </p>
                <p className="mt-1 text-[11px] text-fg-muted">Immediate action required</p>
              </div>
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                <SeverityBadge severity="High" />
                <p className="mt-3 text-2xl font-bold text-amber-300">
                  {loading && !data ? "..." : (data?.incidents_by_severity.high ?? 0)}
                </p>
                <p className="mt-1 text-[11px] text-fg-muted">Elevated risk posture</p>
              </div>
              <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4">
                <SeverityBadge severity="Medium" />
                <p className="mt-3 text-2xl font-bold text-blue-300">
                  {loading && !data ? "..." : (data?.incidents_by_severity.medium ?? 0)}
                </p>
                <p className="mt-1 text-[11px] text-fg-muted">Standard investigation</p>
              </div>
              <div className="rounded-xl border border-slate-500/20 bg-slate-500/5 p-4">
                <SeverityBadge severity="Low" />
                <p className="mt-3 text-2xl font-bold text-slate-300">
                  {loading && !data ? "..." : (data?.incidents_by_severity.low ?? 0)}
                </p>
                <p className="mt-1 text-[11px] text-fg-muted">Informational/low priority</p>
              </div>
            </div>
          </section>

          {/* Tables Grid: Active Incidents & High Severity Alerts */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Active Incidents */}
            <section aria-label="Active incidents" className="space-y-2">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-fg-primary">Active Incidents</h2>
                <span className="text-xs text-fg-muted">{data?.active_incidents.length ?? 0} active</span>
              </div>
              <DataTable
                columns={incidentColumns}
                rows={data?.active_incidents ?? []}
                getRowId={(i) => i.id}
                ariaLabel="Active incidents"
                loading={loading && !data}
                emptyState={
                  <EmptyState
                    title="No active incidents"
                    description="There are currently no open incidents requiring intervention."
                  />
                }
              />
            </section>

            {/* High/Critical Alerts */}
            <section aria-label="High severity alerts" className="space-y-2">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-fg-primary">High & Critical Alerts</h2>
                <span className="text-xs text-fg-muted">{data?.recent_alerts.length ?? 0} recent</span>
              </div>
              <DataTable
                columns={alertColumns}
                rows={data?.recent_alerts ?? []}
                getRowId={(a) => a.id}
                ariaLabel="Recent critical alerts"
                loading={loading && !data}
                emptyState={
                  <EmptyState
                    title="No critical alerts"
                    description="No unhandled high or critical alerts in the system."
                  />
                }
              />
            </section>
          </div>

          {/* Tenant Defense Readiness Table */}
          <section aria-label="Tenant defense readiness" className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-fg-primary">Organization Defense Posture</h2>
                <p className="text-xs text-fg-muted">Infrastructure coverage and SOC operational mode per tenant.</p>
              </div>
              <Link to="/admin/organizations" className="text-xs text-brand-300 hover:underline">
                Manage Organizations &rarr;
              </Link>
            </div>
            <DataTable
              columns={orgColumns}
              rows={data?.organizations ?? []}
              getRowId={(o) => o.id}
              ariaLabel="Organizations posture"
              loading={loading && !data}
              emptyState={
                <EmptyState
                  title="No organizations found"
                  description="Register organizations to view cross-tenant defense posture."
                />
              }
            />
          </section>
        </div>
      </main>
    </div>
  )
}
