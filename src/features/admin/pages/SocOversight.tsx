import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, RefreshCw, Users } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import Dialog from "../../../components/ui/Dialog"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import Sparkline from "../../../components/ui/Sparkline"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"

import {
  ApiError,
  apiGetSocOversight,
  apiReassignAlert,
  type SocOversightResponse,
  type UnassignedAlertRow,
} from "../../../lib/api"

function ageLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.round(hours / 24)}d`
}

type TimeRange = "24h" | "7d" | "30d"

function SocOversightAdmin() {
  const toast = useToast()

  const [range, setRange] = useState<TimeRange>("24h")
  const [data, setData] = useState<SocOversightResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(() => new Date())

  // Reassignment Modal State
  const [reassignAlert, setReassignAlert] = useState<UnassignedAlertRow | null>(null)
  const [selectedAnalystId, setSelectedAnalystId] = useState<string>("")
  const [reassignReason, setReassignReason] = useState<string>("Workload rebalancing")
  const [reassigning, setReassigning] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGetSocOversight(range)
      setData(res)
      setLastUpdated(new Date())
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to load SOC oversight telemetry.", {
        tone: "danger",
      })
    } finally {
      setLoading(false)
    }
  }, [range, toast])

  useEffect(() => {
    reload()
  }, [reload])

  function handleOpenReassign(alert: UnassignedAlertRow, analystId: string) {
    if (!analystId) return
    setReassignAlert(alert)
    setSelectedAnalystId(analystId)
    setReassignReason("Workload rebalancing")
  }

  async function handleConfirmReassign() {
    if (!reassignAlert || !selectedAnalystId) return
    if (!reassignReason.trim()) {
      toast.show("A reason is required to reassign an alert.", { tone: "danger" })
      return
    }

    setReassigning(true)
    try {
      await apiReassignAlert(reassignAlert.id, selectedAnalystId, reassignReason.trim())
      toast.show(`Reassigned "${reassignAlert.title}" successfully.`, { tone: "success" })
      setReassignAlert(null)
      setSelectedAnalystId("")
      reload()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not reassign alert.", { tone: "danger" })
    } finally {
      setReassigning(false)
    }
  }

  const columns: DataTableColumn<UnassignedAlertRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      render: (a) => <SeverityBadge severity={a.severity} showIcon />,
    },
    {
      key: "title",
      header: "Alert",
      render: (a) => (
        <div>
          <p className="font-medium text-fg-primary">{a.title}</p>
          <p className="text-xs text-fg-muted">{a.detectionRuleName}</p>
        </div>
      ),
    },
    {
      key: "organization",
      header: "Organization",
      render: (a) => (
        <Link
          to={`/admin/organizations/${a.organizationId}`}
          className="text-xs font-medium text-brand-300 hover:underline"
        >
          {a.organizationName}
        </Link>
      ),
    },
    {
      key: "asset",
      header: "Asset",
      render: (a) => <span className="font-mono text-xs">{a.assetHostname}</span>,
    },
    {
      key: "age",
      header: "Age",
      width: "72px",
      render: (a) => <span title={new Date(a.firstSeenAt).toString()}>{ageLabel(a.firstSeenAt)}</span>,
    },
    {
      key: "reassign",
      header: "Assign to",
      width: "200px",
      render: (a) => {
        const eligible = a.eligibleAnalysts || []
        if (eligible.length === 0) {
          return (
            <span className="text-[11px] text-critical-fg" title="Assign a platform SOC analyst to this org first">
              No assigned analyst
            </span>
          )
        }
        return (
          <select
            defaultValue=""
            onChange={(e) => handleOpenReassign(a, e.target.value)}
            aria-label={`Assign ${a.title} to an analyst`}
            className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          >
            <option value="" disabled>
              Choose analyst...
            </option>
            {eligible.map((analyst) => (
              <option key={analyst.id} value={analyst.id}>
                {analyst.name}
              </option>
            ))}
          </select>
        )
      },
    },
  ]

  const totalVolume = data?.volume.reduce((sum, p) => sum + p.value, 0) ?? 0

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">SOC Oversight</h1>
              <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
                Cross-tenant security activity, analyst workloads, and triage health. Last updated{" "}
                <time dateTime={lastUpdated.toISOString()} title={lastUpdated.toString()}>
                  {lastUpdated.toLocaleTimeString()}
                </time>
              </p>
            </div>
            <div className="flex items-center gap-3">
              <label htmlFor="soc-range-select" className="sr-only">
                Time range
              </label>
              <select
                id="soc-range-select"
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

          {/* Coverage Gaps Call-to-action */}
          {data && data.coverage_gaps.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200">
              <div className="flex items-center gap-3">
                <AlertTriangle size={20} className="shrink-0 text-amber-400" />
                <div>
                  <p className="text-sm font-semibold text-amber-200">
                    Coverage Gaps: {data.coverage_gaps.length} Managed Organization(s) Without Assigned Analyst
                  </p>
                  <p className="mt-0.5 text-xs text-amber-300/80">
                    Tenants lacking dedicated oversight: {data.coverage_gaps.map((o) => o.name).join(", ")}.
                  </p>
                </div>
              </div>
              <Link
                to="/admin/soc-team"
                className="inline-flex items-center gap-1.5 rounded-control bg-amber-500 px-3 py-1.5 text-xs font-semibold text-black transition-colors hover:bg-amber-400"
              >
                <Users size={13} />
                Assign Analysts on SOC Team Page &rarr;
              </Link>
            </div>
          )}

          {/* Key Metrics */}
          <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            {loading && !data
              ? Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
              : data?.kpis.map((kpi) => <KpiCard key={kpi.label} {...kpi} />)}
          </section>

          {/* Event Volume Sparkline */}
          <section aria-label="Event volume" className="rounded-card border border-line bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-fg-primary">Event volume (24h)</h2>
              <span className="text-xs text-fg-muted">{totalVolume} security events ingested</span>
            </div>
            {loading && !data ? (
              <Skeleton className="mt-3 h-12 w-full" />
            ) : (
              <div className="mt-3">
                <Sparkline
                  points={data?.volume.map((p) => ({ label: p.time, value: p.value })) ?? []}
                  summary={`${totalVolume} events across all tenants in the last 24h`}
                />
              </div>
            )}
          </section>

          {/* Main Oversight Grid */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* Needs Reassignment Queue */}
            <section className="xl:col-span-2" aria-label="Needs reassignment">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-fg-primary">Needs reassignment</h2>
                <Link to="/admin/soc-queue" className="text-xs text-brand-300 hover:underline">
                  Open Platform SOC Queue &rarr;
                </Link>
              </div>
              <DataTable
                columns={columns}
                rows={data?.unassigned_alerts ?? []}
                getRowId={(a) => a.id}
                ariaLabel="Unassigned alerts"
                loading={loading && !data}
                emptyState={
                  <EmptyState
                    title="Nothing unassigned"
                    description="Every open alert currently has an active analyst assigned."
                  />
                }
              />
            </section>

            {/* Workload & Rule Health Sidebar */}
            <div className="space-y-4">
              {/* Analyst Workload */}
              <section aria-label="Analyst workload" className="rounded-card border border-line bg-surface p-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-fg-primary">Platform Analyst Workload</h2>
                  <Link to="/admin/soc-team" className="text-xs text-brand-300 hover:underline">
                    Team &rarr;
                  </Link>
                </div>
                {loading && !data ? (
                  <Skeleton count={3} className="mt-3 h-10 w-full" />
                ) : (data?.analyst_workload.length ?? 0) === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No platform analysts assigned yet.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {data?.analyst_workload.map((analyst) => (
                      <li
                        key={analyst.id}
                        className="flex flex-col gap-1 rounded-control border border-line bg-surface-sunken p-2.5 text-xs"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-fg-primary">{analyst.name}</span>
                          <span className="text-fg-muted">
                            {analyst.open_alerts} alerts &middot; {analyst.open_incidents} incidents
                          </span>
                        </div>
                        <span className="text-[11px] text-fg-muted">
                          {analyst.assigned_organizations.length} managed org(s) assigned
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Top Detection Rules */}
              <section aria-label="Top detection rules" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Top detection rules</h2>
                {loading && !data ? (
                  <Skeleton count={3} className="mt-3 h-10 w-full" />
                ) : (data?.top_rules.length ?? 0) === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No alert firings in this period.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {data?.top_rules.map((rule) => (
                      <li key={rule.name} className="rounded-control border border-line bg-surface-sunken p-2.5 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-fg-primary">{rule.name}</span>
                          <span className="text-fg-muted">{rule.count} fired</span>
                        </div>
                        <div className="mt-1 flex items-center justify-between text-fg-muted">
                          <span>False-positive rate</span>
                          <span className={rule.false_positive_rate > 30 ? "text-amber-400" : ""}>
                            {rule.false_positive_rate}%
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Tenant Monitoring Matrix */}
              <section aria-label="Tenant SOC matrix" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Tenant SOC Health</h2>
                {loading && !data ? (
                  <Skeleton count={3} className="mt-3 h-10 w-full" />
                ) : (data?.organizations.length ?? 0) === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No organizations found.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {data?.organizations.slice(0, 5).map((org) => (
                      <li
                        key={org.id}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2 text-xs"
                      >
                        <div>
                          <Link to={`/admin/organizations/${org.id}`} className="font-medium text-fg-primary hover:underline">
                            {org.name}
                          </Link>
                          <p className="text-[11px] text-fg-muted">
                            {org.soc_mode === "managed" ? "Managed" : "In-House"} &middot; {org.open_incidents} incidents
                          </p>
                        </div>
                        <div className="text-right">
                          <Badge tone={org.unacknowledged_alerts > 0 ? "danger" : "neutral"}>
                            {org.unacknowledged_alerts} unack
                          </Badge>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>
        </div>

        {/* Reassignment Confirmation Dialog */}
        {reassignAlert && (
          <Dialog
            open={Boolean(reassignAlert)}
            onClose={() => setReassignAlert(null)}
            title="Reassign Alert"
            footer={
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setReassignAlert(null)} disabled={reassigning}>
                  Cancel
                </Button>
                <Button onClick={handleConfirmReassign} loading={reassigning}>
                  Confirm Reassignment
                </Button>
              </div>
            }
          >
            <div className="space-y-4">
              <p className="text-xs text-fg-muted">
                Reassigning this alert transfers ownership to another platform SOC analyst assigned to{" "}
                <strong className="text-fg-primary">{reassignAlert.organizationName}</strong>. This action is permanently audited.
              </p>

              <div className="rounded-control border border-line bg-surface-sunken p-3 text-xs">
                <p className="font-medium text-fg-primary">{reassignAlert.title}</p>
                <p className="mt-1 text-fg-muted">
                  Rule: {reassignAlert.detectionRuleName} &middot; Severity: {reassignAlert.severity}
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-fg-secondary">
                  Target Platform SOC Analyst
                </label>
                <select
                  value={selectedAnalystId}
                  onChange={(e) => setSelectedAnalystId(e.target.value)}
                  className="mt-1 w-full rounded-control border border-line bg-surface px-3 py-2 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                >
                  {reassignAlert.eligibleAnalysts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.email})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-fg-secondary">
                  Reason for Reassignment <span className="text-critical-fg">*</span>
                </label>
                <input
                  type="text"
                  value={reassignReason}
                  onChange={(e) => setReassignReason(e.target.value)}
                  placeholder="e.g. Workload rebalancing, Shift handover"
                  className="mt-1 w-full rounded-control border border-line bg-surface px-3 py-2 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                />
              </div>
            </div>
          </Dialog>
        )}
      </main>
    </div>
  )
}

export default SocOversightAdmin
