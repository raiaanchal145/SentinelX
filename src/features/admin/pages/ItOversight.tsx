import { useEffect, useMemo, useState } from "react"
import { RefreshCw } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import DemoDataChip from "../../../components/shared/DemoDataChip"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import CountdownChip from "../../../components/ui/CountdownChip"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"

import { delay, getAssetById, getItOversight, IT_WORKFLOW_ORDER } from "../../../lib/data"
import { scopeFor } from "../../../lib/scope"
import { useMockStore } from "../../../mocks/store"
import type { Ticket } from "../../../types"

const STATUS_LABEL: Record<string, string> = {
  ASSIGNED: "Assigned",
  ACKNOWLEDGED: "Acknowledged",
  INVESTIGATING: "Investigating",
  REMEDIATION: "Remediation",
  VERIFICATION: "Verification",
  RESOLVED: "Resolved",
}

/** Same tenant-safety note as the SOC oversight page: candidates come from
 * the ticket's own organization, not the admin's (possibly "all") scope. */
function itOptionsFor(users: ReturnType<typeof useMockStore>["state"]["users"], organizationId: string) {
  return users.filter((u) => u.role === "it_developer" && u.organizationId === organizationId)
}

/** Admin-side aggregate view -- P22 "IT oversight page (aggregates, workload,
 * coverage, SLA)". Reassigning an at-risk/overdue ticket is the only
 * mutation here, and it is audited via ADMIN_REASSIGN_TICKET. */
function ItOversightAdmin() {
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

  const oversight = useMemo(() => getItOversight(state, scope), [state, scope])

  function handleReassign(ticket: Ticket, userId: string) {
    if (!userId) return
    const dev = state.users.find((u) => u.id === userId)
    dispatch({ type: "ADMIN_REASSIGN_TICKET", ticketId: ticket.id, userId, actorName: scope.displayName })
    toast.show(`Reassigned ${ticket.ticketNumber} to ${dev?.name ?? "IT"}.`, { tone: "success" })
  }

  const columns: DataTableColumn<Ticket>[] = [
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
      key: "asset",
      header: "Asset",
      render: (t) => getAssetById(state, t.assetId)?.hostname ?? <span className="text-fg-faint">--</span>,
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
      render: (t) => {
        const current = state.users.find((u) => u.id === t.assignedUserId)
        return current?.name ?? <span className="text-fg-faint">Unassigned</span>
      },
    },
    {
      key: "reassign",
      header: "Reassign",
      width: "200px",
      render: (t) => {
        const devs = itOptionsFor(state.users, t.organizationId)
        return (
          <select
            defaultValue=""
            onChange={(e) => handleReassign(t, e.target.value)}
            aria-label={`Reassign ${t.ticketNumber} to another IT developer`}
            className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          >
            <option value="" disabled>
              Choose IT developer...
            </option>
            {devs.map((dev) => (
              <option key={dev.id} value={dev.id}>
                {dev.name}
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
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">IT Oversight</h1>
              <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
                Remediation coverage, SLA health and workload across{" "}
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

          <section aria-label="Pipeline by status" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Open tickets by stage</h2>
            {loading ? (
              <Skeleton className="mt-3 h-10 w-full" />
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {IT_WORKFLOW_ORDER.map((status) => {
                  const row = oversight.byStatus.find((s) => s.status === status)
                  return (
                    <span
                      key={status}
                      className="inline-flex items-center gap-1.5 rounded-control border border-line bg-surface-sunken px-2.5 py-1.5 text-xs text-fg-secondary"
                    >
                      {STATUS_LABEL[status] ?? status}
                      <Badge tone={row && row.count > 0 ? "brand" : "neutral"}>{row?.count ?? 0}</Badge>
                    </span>
                  )
                })}
              </div>
            )}
          </section>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <section className="xl:col-span-2" aria-label="SLA at risk">
              <h2 className="mb-2 text-sm font-semibold text-fg-primary">Overdue &amp; at-risk tickets</h2>
              <DataTable
                columns={columns}
                rows={oversight.slaTable}
                getRowId={(t) => t.id}
                ariaLabel="Overdue and at-risk tickets"
                loading={loading}
                emptyState={
                  <EmptyState title="SLA is healthy" description="No ticket is overdue or close to breaching its SLA." />
                }
              />
            </section>

            <div className="space-y-4">
              <section aria-label="By team" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">By team</h2>
                {loading ? (
                  <Skeleton count={2} className="h-10 w-full" />
                ) : oversight.byTeam.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No tickets assigned to a team yet.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {oversight.byTeam.map((row) => (
                      <li
                        key={row.team?.id ?? "unknown"}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2 text-xs"
                      >
                        <span className="font-medium text-fg-primary">{row.team?.name ?? "Unassigned team"}</span>
                        <span className="text-fg-muted">
                          {row.open} open &middot; {row.overdue} overdue
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="IT workload" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">IT workload</h2>
                {loading ? (
                  <Skeleton count={3} className="h-10 w-full" />
                ) : oversight.workload.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No open tickets assigned yet.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {oversight.workload.map((row) => (
                      <li
                        key={row.user?.id ?? "unknown"}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2 text-xs"
                      >
                        <span className="font-medium text-fg-primary">{row.user?.name ?? "Unknown"}</span>
                        <span className="text-fg-muted">
                          {row.openTasks} open &middot; {row.overdue} overdue
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="Awaiting verification" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Awaiting SOC verification</h2>
                {loading ? (
                  <Skeleton count={2} className="h-8 w-full" />
                ) : oversight.awaitingVerification.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">Nothing waiting on SOC right now.</p>
                ) : (
                  <ul className="mt-3 space-y-1.5">
                    {oversight.awaitingVerification.slice(0, 6).map((ticket) => (
                      <li key={ticket.id} className="flex items-center justify-between gap-2 text-xs text-fg-secondary">
                        <span className="truncate">
                          {ticket.ticketNumber} &middot; {ticket.title}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="Repeat-incident assets" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Repeat-incident assets</h2>
                {loading ? (
                  <Skeleton count={2} className="h-8 w-full" />
                ) : oversight.repeatAssets.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-muted">No asset has needed remediation more than once.</p>
                ) : (
                  <ul className="mt-3 space-y-1.5">
                    {oversight.repeatAssets.map((row, i) => (
                      <li
                        key={row.asset?.id ?? `unknown-${i}`}
                        className="flex items-center justify-between text-xs text-fg-secondary"
                      >
                        <span>{row.asset?.hostname ?? "Unknown asset"}</span>
                        <Badge tone="neutral">{row.count}x</Badge>
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

export default ItOversightAdmin
