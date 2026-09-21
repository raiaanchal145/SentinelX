import { useEffect, useMemo, useState } from "react"
import { RefreshCw, ServerOff, ShieldAlert, Wifi } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import DemoDataChip from "../../../components/shared/DemoDataChip"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import Sparkline from "../../../components/ui/Sparkline"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"

import { delay, getAssetById, getSocOversight } from "../../../lib/data"
import { scopeFor } from "../../../lib/scope"
import { useMockStore } from "../../../mocks/store"
import type { Alert } from "../../../types"

/** Where to reassign FROM must always match the alert's own organization
 * (not the admin's own scope, which can be "all" for a super_admin viewing
 * every tenant at once) -- this keeps reassignment tenant-safe. */
function analystOptionsFor(users: ReturnType<typeof useMockStore>["state"]["users"], organizationId: string) {
  return users.filter((u) => u.role === "soc_analyst" && u.organizationId === organizationId)
}

function ageLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.round(hours / 24)}d`
}

/** Admin-side aggregate view -- P22 "SOC oversight page (aggregates, workload,
 * coverage, SLA)". This is a read-mostly rollup: the only mutation available
 * here is reassigning an unassigned alert, which is audited the same way
 * every other mock-store action is (see ADMIN_REASSIGN_ALERT). */
function SocOversightAdmin() {
  const { state, dispatch } = useMockStore()
  const toast = useToast()
  const scope = useMemo(() => scopeFor(), [])

  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(() => new Date())

  async function reload() {
    setLoading(true)
    await delay(null)
    setLoading(false)
    setLastUpdated(new Date())
  }

  useEffect(() => {
    let cancelled = false
    delay(null).then(() => {
      if (!cancelled) setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const oversight = useMemo(() => getSocOversight(state, scope), [state, scope])

  function handleReassign(alert: Alert, userId: string) {
    if (!userId) return
    const analyst = state.users.find((u) => u.id === userId)
    dispatch({ type: "ADMIN_REASSIGN_ALERT", alertId: alert.id, userId, actorName: scope.displayName })
    toast.show(`Reassigned "${alert.title}" to ${analyst?.name ?? "analyst"}.`, { tone: "success" })
  }

  const columns: DataTableColumn<Alert>[] = [
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
      key: "asset",
      header: "Asset",
      render: (a) => getAssetById(state, a.assetId)?.hostname ?? <span className="text-fg-faint">--</span>,
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
        const analysts = analystOptionsFor(state.users, a.organizationId)
        return (
          <select
            defaultValue=""
            onChange={(e) => handleReassign(a, e.target.value)}
            aria-label={`Assign ${a.title} to an analyst`}
            className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          >
            <option value="" disabled>
              Choose analyst...
            </option>
            {analysts.map((analyst) => (
              <option key={analyst.id} value={analyst.id}>
                {analyst.name}
              </option>
            ))}
          </select>
        )
      },
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
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">SOC Oversight</h1>
              <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
                Aggregate alert &amp; incident activity across{" "}
                {scope.organizationId === "all" ? "every organization" : "your organization"}. Last updated{" "}
                <time dateTime={lastUpdated.toISOString()} title={lastUpdated.toString()}>
                  {lastUpdated.toLocaleTimeString()}
                </time>
                <DemoDataChip />
              </p>
            </div>
            <IconButton icon={RefreshCw} label="Refresh dashboard" onClick={reload} />
          </div>

          <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            {loading
              ? Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
              : oversight.kpis.map((kpi) => <KpiCard key={kpi.label} {...kpi} />)}
          </section>

          <section aria-label="Event volume" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Event volume (24h)</h2>
            {loading ? (
              <Skeleton className="mt-3 h-12 w-full" />
            ) : (
              <div className="mt-3">
                <Sparkline
                  points={oversight.volume}
                  summary={`${oversight.volume.reduce((sum, p) => sum + p.value, 0)} events in the last 24h`}
                />
              </div>
            )}
          </section>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <section className="xl:col-span-2" aria-label="Needs reassignment">
              <h2 className="mb-2 text-sm font-semibold text-fg-primary">Needs reassignment</h2>
              <DataTable
                columns={columns}
                rows={oversight.unassignedAlerts}
                getRowId={(a) => a.id}
                ariaLabel="Unassigned alerts"
                loading={loading}
                emptyState={
                  <EmptyState
                    title="Nothing unassigned"
                    description="Every open alert currently has an analyst on it."
                  />
                }
              />
            </section>

            <div className="space-y-4">
              <section aria-label="Analyst workload" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Analyst workload</h2>
                {loading ? (
                  <Skeleton count={3} className="h-10 w-full" />
                ) : oversight.analystWorkload.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No alerts assigned to an analyst yet.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {oversight.analystWorkload.map((row) => (
                      <li
                        key={row.user?.id ?? "unknown"}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2 text-xs"
                      >
                        <span className="font-medium text-fg-primary">{row.user?.name ?? "Unknown"}</span>
                        <span className="text-fg-muted">
                          {row.openAlerts} alerts &middot; {row.openIncidents} incidents
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="Top detection rules" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Top detection rules</h2>
                {loading ? (
                  <Skeleton count={3} className="h-10 w-full" />
                ) : oversight.topRules.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No alerts in the current period.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {oversight.topRules.map((rule) => (
                      <li key={rule.name} className="rounded-control border border-line bg-surface-sunken p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-fg-primary">{rule.name}</span>
                          <span className="text-fg-muted">{rule.count} fired</span>
                        </div>
                        <p className="mt-1 text-fg-muted">{rule.falsePositiveRate}% false-positive rate</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="Device coverage" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Device coverage</h2>
                {loading ? (
                  <Skeleton count={2} className="h-6 w-full" />
                ) : oversight.offlineAssets.length === 0 ? (
                  <p className="mt-2 flex items-center gap-1.5 text-xs text-success-fg">
                    <Wifi size={13} aria-hidden="true" /> All monitored assets are connected.
                  </p>
                ) : (
                  <ul className="mt-3 space-y-1.5">
                    {oversight.offlineAssets.slice(0, 6).map((asset) => (
                      <li key={asset.id} className="flex items-center justify-between text-xs text-fg-muted">
                        <span className="flex items-center gap-1.5">
                          <ServerOff size={13} className="text-critical-fg" aria-hidden="true" />
                          {asset.hostname}
                        </span>
                        <span title={new Date(asset.lastSeenAt).toString()}>
                          since {new Date(asset.lastSeenAt).toLocaleDateString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="Needs attention" className="rounded-card border border-line bg-surface p-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-fg-primary">
                  <ShieldAlert size={15} className="text-critical-fg" aria-hidden="true" />
                  Needs attention
                </h2>
                {loading ? (
                  <Skeleton count={2} className="h-8 w-full" />
                ) : oversight.attention.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">Nothing critical or stale right now.</p>
                ) : (
                  <ul className="mt-3 space-y-1.5">
                    {oversight.attention.map((item) => (
                      <li
                        key={`${item.kind}-${item.id}`}
                        className="flex items-center justify-between gap-2 text-xs text-fg-secondary"
                      >
                        <span className="truncate">{item.title}</span>
                        <Badge tone={item.kind === "alert" ? "danger" : "neutral"}>{item.kind}</Badge>
                      </li>
                    ))}
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

export default SocOversightAdmin
