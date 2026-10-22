import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { AlertCircle, Clock, RefreshCw, Users, Wrench } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import CountdownChip from "../../../components/ui/CountdownChip"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"

import {
  ApiError,
  apiGetItOversight,
  type ItOversightResponse,
  type SlaTicketRow,
} from "../../../lib/api"

const STATUS_LABEL: Record<string, string> = {
  OPEN: "Open",
  TRIAGED: "Triaged",
  ASSIGNED: "Assigned",
  ACKNOWLEDGED: "Acknowledged",
  INVESTIGATING: "Investigating",
  REMEDIATION: "Remediation",
  VERIFICATION: "Verification",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
}

type TimeRange = "24h" | "7d" | "30d"

function ItOversightAdmin() {
  const toast = useToast()

  const [range, setRange] = useState<TimeRange>("24h")
  const [data, setData] = useState<ItOversightResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(() => new Date())

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGetItOversight(range)
      setData(res)
      setLastUpdated(new Date())
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to load IT oversight telemetry.", {
        tone: "danger",
      })
    } finally {
      setLoading(false)
    }
  }, [range, toast])

  useEffect(() => {
    reload()
  }, [reload])

  const columns: DataTableColumn<SlaTicketRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      render: (t) => <SeverityBadge severity={t.severity} showIcon />,
    },
    {
      key: "ticket",
      header: "Ticket",
      render: (t) => (
        <div>
          <p className="font-mono text-[11px] text-fg-faint">{t.ticketNumber}</p>
          <p className="font-medium text-fg-primary">{t.title}</p>
        </div>
      ),
    },
    {
      key: "organization",
      header: "Organization",
      render: (t) => (
        <Link
          to={`/admin/organizations/${t.organizationId}`}
          className="text-xs font-medium text-brand-300 hover:underline"
        >
          {t.organizationName}
        </Link>
      ),
    },
    {
      key: "asset",
      header: "Asset",
      render: (t) => <span className="font-mono text-xs">{t.assetHostname}</span>,
    },
    {
      key: "due",
      header: "SLA",
      width: "130px",
      render: (t) => <CountdownChip dueAt={t.resolveDueAt} />,
    },
    {
      key: "assignee",
      header: "Assigned to",
      render: (t) => (
        <span className={t.assigneeName === "Unassigned" ? "text-fg-faint" : "text-fg-secondary"}>
          {t.assigneeName}
        </span>
      ),
    },
  ]

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">IT Oversight</h1>
              <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
                Remediation coverage, SLA health, and developer workloads across tenants. Last updated{" "}
                <time dateTime={lastUpdated.toISOString()} title={lastUpdated.toString()}>
                  {lastUpdated.toLocaleTimeString()}
                </time>
              </p>
            </div>
            <div className="flex items-center gap-3">
              <label htmlFor="it-range-select" className="sr-only">
                Time range
              </label>
              <select
                id="it-range-select"
                value={range}
                onChange={(e) => setRange(e.target.value as TimeRange)}
                aria-label="Select time range"
                className="rounded-control border border-line bg-surface px-3 py-1.5 text-xs text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                <option value="24h">Last 24 Hours</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
              </select>
              <IconButton icon={RefreshCw} label="Refresh dashboard" onClick={reload} />
            </div>
          </div>

          {/* Key metrics */}
          <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            {loading && !data
              ? Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
              : data?.kpis.map((kpi) => <KpiCard key={kpi.label} {...kpi} />)}
          </section>

          {/* Pipeline by stage */}
          <section aria-label="Pipeline by status" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Open tickets by workflow stage</h2>
            {loading && !data ? (
              <Skeleton className="mt-3 h-10 w-full" />
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {data?.byStatus.map((row) => (
                  <span
                    key={row.status}
                    className="inline-flex items-center gap-1.5 rounded-control border border-line bg-surface-sunken px-2.5 py-1.5 text-xs text-fg-secondary"
                  >
                    {STATUS_LABEL[row.status] ?? row.status}
                    <Badge tone={row.count > 0 ? "brand" : "neutral"}>{row.count}</Badge>
                  </span>
                ))}
              </div>
            )}
          </section>

          {/* Main Oversight Grid */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* SLA At-Risk Queue */}
            <section className="xl:col-span-2" aria-label="SLA at risk">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-fg-primary">Overdue &amp; at-risk tickets</h2>
                <span className="text-xs text-fg-muted">
                  {data?.slaTable.length ?? 0} tickets nearing breach
                </span>
              </div>
              <DataTable
                columns={columns}
                rows={data?.slaTable ?? []}
                getRowId={(t) => t.id}
                ariaLabel="Overdue and at-risk tickets"
                loading={loading && !data}
                emptyState={
                  <EmptyState title="SLA is healthy" description="No ticket is currently overdue or at risk of SLA breach." />
                }
              />
            </section>

            {/* Team & Dev Workloads */}
            <div className="space-y-4">
              {/* By Team */}
              <section aria-label="By team" className="rounded-card border border-line bg-surface p-4">
                <div className="flex items-center justify-between">
                  <h2 className="flex items-center gap-1.5 text-sm font-semibold text-fg-primary">
                    <Users size={15} className="text-brand-400" aria-hidden="true" />
                    Workload by Team
                  </h2>
                </div>
                {loading && !data ? (
                  <Skeleton count={2} className="mt-3 h-10 w-full" />
                ) : (data?.byTeam.length ?? 0) === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No tickets assigned to a team yet.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {data?.byTeam.map((row) => (
                      <li
                        key={row.team.id}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-xs"
                      >
                        <span className="font-medium text-fg-primary">{row.team.name}</span>
                        <span className="text-fg-muted">
                          {row.open} open &middot;{" "}
                          <span className={row.overdue > 0 ? "font-semibold text-critical-fg" : ""}>
                            {row.overdue} overdue
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Developer Workload */}
              <section aria-label="IT workload" className="rounded-card border border-line bg-surface p-4">
                <div className="flex items-center justify-between">
                  <h2 className="flex items-center gap-1.5 text-sm font-semibold text-fg-primary">
                    <Wrench size={15} className="text-brand-400" aria-hidden="true" />
                    Developer Workload
                  </h2>
                </div>
                {loading && !data ? (
                  <Skeleton count={3} className="mt-3 h-10 w-full" />
                ) : (data?.workload.length ?? 0) === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No active IT developers found.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {data?.workload.map((row) => (
                      <li
                        key={row.user.id}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-xs"
                      >
                        <div>
                          <span className="font-medium text-fg-primary">{row.user.name}</span>
                          <p className="text-[11px] text-fg-muted">{row.user.email}</p>
                        </div>
                        <span className="text-fg-muted">
                          {row.openTasks} open &middot;{" "}
                          <span className={row.overdue > 0 ? "font-semibold text-critical-fg" : ""}>
                            {row.overdue} overdue
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Tenant IT Health Matrix */}
              <section aria-label="Tenant IT health" className="rounded-card border border-line bg-surface p-4">
                <h2 className="flex items-center gap-1.5 text-sm font-semibold text-fg-primary">
                  <Clock size={15} className="text-brand-400" aria-hidden="true" />
                  Tenant Ticket Health
                </h2>
                {loading && !data ? (
                  <Skeleton count={3} className="mt-3 h-10 w-full" />
                ) : (data?.organizations.length ?? 0) === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No organization tickets found.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {data?.organizations.slice(0, 5).map((org) => {
                      const prio = org.open_tickets_by_priority
                      return (
                        <li
                          key={org.id}
                          className="flex flex-col gap-1 rounded-control border border-line bg-surface-sunken p-2.5 text-xs"
                        >
                          <div className="flex items-center justify-between">
                            <Link to={`/admin/organizations/${org.id}`} className="font-medium text-fg-primary hover:underline">
                              {org.name}
                            </Link>
                            <span className="text-fg-muted">
                              P1: <strong className="text-critical-fg">{prio.P1}</strong> &middot; P2:{" "}
                              <strong className="text-amber-400">{prio.P2}</strong> &middot; P3: {prio.P3}
                            </span>
                          </div>
                          {(org.sla_at_risk > 0 || org.sla_breached > 0) && (
                            <p className="flex items-center gap-1 text-[11px] text-critical-fg">
                              <AlertCircle size={12} />
                              {org.sla_breached} breached &middot; {org.sla_at_risk} at risk
                            </p>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default ItOversightAdmin
