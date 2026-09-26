import { useCallback, useEffect, useMemo, useState } from "react"
import { RefreshCw } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiAcknowledgeAlert,
  apiDismissAlert,
  apiGetMyAssignedOrganizations,
  apiListAlerts,
  type AlertRow,
  type SocAnalystAssignedOrg,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

import AlertDrawer from "../../soc/components/AlertDrawer"
import AlertFilters from "../../soc/components/AlertFilters"
import { alertRangeHours, INITIAL_ALERT_FILTERS, type AlertFilterState } from "../../soc/components/alertFilterShared"
import AlertKpiRow from "../../soc/components/AlertKpiRow"
import AlertTable from "../../soc/components/AlertTable"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import { minutesSince } from "../../soc/components/alertShared"

const PAGE_SIZE = 200

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

/** The platform SOC analyst's single workspace (Prompt B section A5, now
 * real): a multi-organization alert queue with an organization filter
 * and per-organization counts, in the existing admin layout. Data comes
 * from GET /alerts -- the backend only ever returns the organizations
 * assigned to the calling analyst (managed + active); an unassigned
 * analyst gets an empty queue. */
function SocQueue() {
  const { me } = useMe()
  const toast = useToast()

  const [orgs, setOrgs] = useState<SocAnalystAssignedOrg[]>([])
  const [orgsLoading, setOrgsLoading] = useState(true)
  const [orgsError, setOrgsError] = useState("")

  const [filters, setFilters] = useState<AlertFilterState>(INITIAL_ALERT_FILTERS)
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selected, setSelected] = useState<AlertRow | null>(null)
  const [ackTarget, setAckTarget] = useState<AlertRow | null>(null)
  const [dismissTarget, setDismissTarget] = useState<AlertRow | null>(null)

  const loadOrgs = useCallback(function loadOrgs() {
    setOrgsLoading(true)
    setOrgsError("")
    apiGetMyAssignedOrganizations()
      .then((res) => setOrgs(res.assigned_organizations))
      .catch((err: unknown) => setOrgsError(err instanceof ApiError ? err.message : "Could not load your organizations."))
      .finally(() => setOrgsLoading(false))
  }, [])

  const loadAlerts = useCallback(
    async function loadAlerts() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListAlerts({
          status: filters.status || undefined,
          severity: filters.severity || undefined,
          assigned_to_me: filters.assignedToMe || undefined,
          time_from: filters.range === "all" ? undefined : isoAgo(alertRangeHours(filters.range)),
          organization_id: filters.organizationId || undefined,
          limit: PAGE_SIZE,
        })
        setAlerts(res.alerts)
        setError("")
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load alerts.")
      } finally {
        setLoading(false)
      }
    },
    [filters],
  )

  useEffect(loadOrgs, [loadOrgs])
  useEffect(() => {
    loadAlerts()
  }, [loadAlerts])

  function orgName(organizationId: string): string {
    return orgs.find((o) => o.id === organizationId)?.name ?? `${organizationId.slice(0, 8)}…`
  }

  /** Per-organization open counts across the loaded page (labelled with
   * the page cap below -- client-side numbers by decision, no new
   * backend endpoint). */
  const perOrgCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const alert of alerts) {
      if (alert.status === "dismissed" || alert.status === "converted") continue
      counts.set(alert.organization_id, (counts.get(alert.organization_id) ?? 0) + 1)
    }
    return counts
  }, [alerts])

  const lastEventMinutes = useMemo(() => {
    const latest = alerts.map((a) => a.last_seen_at).filter((t): t is string => !!t).sort().at(-1)
    return latest ? minutesSince(latest) : null
  }, [alerts])

  // Assign target: the calling analyst themselves. The backend only
  // accepts platform SOC analysts assigned to the alert's organization;
  // that is exactly the caller here.
  const assignees = useMemo(
    () => (me ? [{ account_type: "admin" as const, account_id: me.id, label: me.name || "Me" }] : []),
    [me],
  )

  async function confirmAcknowledge() {
    if (!ackTarget) return
    const target = ackTarget
    setAckTarget(null)
    try {
      await apiAcknowledgeAlert(target.id)
      toast.show(`Acknowledged "${target.title}".`, { tone: "success" })
      loadAlerts()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not acknowledge the alert.", { tone: "danger" })
    }
  }

  async function confirmDismiss(reason?: string) {
    if (!dismissTarget || !reason?.trim()) return
    const target = dismissTarget
    setDismissTarget(null)
    try {
      await apiDismissAlert(target.id, reason.trim())
      toast.show(`Dismissed "${target.title}".`, { tone: "info" })
      loadAlerts()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not dismiss the alert.", { tone: "danger" })
    }
  }

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-400">Platform SOC</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">SOC Queue</h1>
              <p className="mt-1 text-xs text-fg-muted">
                Alerts across your assigned organizations. The backend only returns organizations assigned to you.
              </p>
            </div>
            <IconButton icon={RefreshCw} label="Refresh queue" onClick={() => { loadOrgs(); loadAlerts() }} />
          </div>

          <AlertKpiRow alerts={alerts} loading={loading && alerts.length === 0} alertsPath="/admin/soc-queue" />

          {/* Per-organization counts strip -- the multi-organization view. */}
          <section aria-label="Alerts by organization" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Your assigned organizations</h2>
            {orgsLoading ? (
              <Skeleton count={3} className="mt-3 h-9 w-full" />
            ) : orgsError ? (
              <p className="mt-2 text-xs text-danger-fg">{orgsError}</p>
            ) : orgs.length === 0 ? (
              <p className="mt-2 text-xs text-fg-muted">
                You haven't been assigned to any organizations yet. A platform administrator assigns you from the SOC
                Team page.
              </p>
            ) : (
              <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {orgs.map((org) => (
                  <li key={org.id}>
                    <button
                      type="button"
                      onClick={() => setFilters({ ...filters, organizationId: org.id === filters.organizationId ? "" : org.id })}
                      aria-pressed={org.id === filters.organizationId}
                      className={`flex w-full items-center justify-between rounded-control border p-2.5 text-sm transition ${
                        org.id === filters.organizationId
                          ? "border-brand-500/40 bg-brand-500/10"
                          : "border-line bg-surface-sunken hover:border-line-strong"
                      }`}
                    >
                      <span className="truncate font-medium text-fg-primary" title={org.name}>
                        {org.name}
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="text-xs text-fg-muted" title="Open alerts in this organization (from the loaded page)">
                          {perOrgCounts.get(org.id) ?? 0} open
                        </span>
                        <Badge tone={org.status === "active" ? "success" : "brand"}>{org.status}</Badge>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[11px] text-fg-faint">Counts cover the most recent {PAGE_SIZE} alerts in the selected window.</p>
          </section>

          <AlertFilters value={filters} onChange={setFilters} orgOptions={orgs.map((o) => ({ id: o.id, name: o.name }))} />

          <AlertTable
            alerts={alerts}
            loading={loading}
            error={error}
            onRetry={loadAlerts}
            onOpen={setSelected}
            orgName={orgName}
            assigneeName={(alert) => {
              if (!alert.assigned_account_id) return null
              if (alert.assigned_account_id === me?.id) return me?.name ?? "Me"
              return "Another analyst"
            }}
            emptyTitle="No alerts in your queue"
            emptyDescription={
              orgs.length === 0
                ? "You are not assigned to any organizations yet, so there is nothing to triage."
                : lastEventMinutes !== null
                  ? `No alerts match -- the most recent activity across your organizations was ${lastEventMinutes} minute${lastEventMinutes === 1 ? "" : "s"} ago.`
                  : "No alerts have fired in your assigned organizations recently."
            }
            ariaLabel="Platform SOC alert queue"
          />

          <AlertDrawer alert={selected} onClose={() => setSelected(null)} canWrite assignees={assignees} onChanged={loadAlerts} />

          <ConfirmDialog
            open={ackTarget !== null}
            onClose={() => setAckTarget(null)}
            onConfirm={() => void confirmAcknowledge()}
            title="Acknowledge alert"
            impact={ackTarget ? `Moves "${ackTarget.title}" from new to acknowledged.` : ""}
            confirmLabel="Acknowledge"
            danger={false}
          />

          <ConfirmDialog
            open={dismissTarget !== null}
            onClose={() => setDismissTarget(null)}
            onConfirm={(reason) => void confirmDismiss(reason)}
            title="Dismiss alert"
            impact="Marks this alert as a false positive. A reason is required."
            requireReason
            confirmLabel="Dismiss"
          />

          {!loading && alerts.length === 0 && orgs.length > 0 && (
            <EmptyState
              title="Queue is clear"
              description="No alerts match the current filters in your assigned organizations."
            />
          )}
        </div>
      </main>
    </div>
  )
}

export default SocQueue
