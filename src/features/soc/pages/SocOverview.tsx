import { useCallback, useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { RefreshCw, ServerOff, Wifi } from "lucide-react"

import DemoDataChip from "../../../components/shared/DemoDataChip"
import EmptyState from "../../../components/EmptyState"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import SegmentedControl from "../../../components/ui/SegmentedControl"
import Skeleton from "../../../components/ui/Skeleton"
import Sparkline from "../../../components/ui/Sparkline"
import { useToast } from "../../../components/ui/Toast"

import {
  delay,
  getActiveIncidents,
  getAiInsights,
  getAssetById,
  getDeviceHealth,
  getSocKpis,
  getTriageQueue,
  getUserById,
  type TriageRow,
} from "../../../lib/data"
import { ApiError, apiGetEventsSummary, type EventSummary } from "../../../lib/api"
import { scopeFor } from "../../../lib/scope"
import { useMockStore } from "../../../mocks/store"

import AlertDetailDrawer from "../components/AlertDetailDrawer"
import TriageQueueTable from "../components/TriageQueueTable"

type Range = "24h" | "7d" | "30d"

const RANGE_HOURS: Record<Range, 24 | 168 | 720> = { "24h": 24, "7d": 168, "30d": 720 }
const RANGE_OPTIONS: { value: Range; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
]

function SocOverview() {
  const { state, dispatch } = useMockStore()
  const toast = useToast()
  const navigate = useNavigate()
  const scope = useMemo(() => scopeFor(), [])

  const [range, setRange] = useState<Range>("24h")
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(() => new Date())
  const [selectedRow, setSelectedRow] = useState<TriageRow | null>(null)
  const [dismissTarget, setDismissTarget] = useState<TriageRow | null>(null)

  // Real event volume (P07 read API) -- the rest of the dashboard stays
  // mock until the alerts work (P10). The backend decides visibility.
  const [eventSummary, setEventSummary] = useState<EventSummary | null>(null)
  const [eventSummaryError, setEventSummaryError] = useState("")

  const loadEventSummary = useCallback(
    function loadEventSummary() {
      // 12 buckets covering the selected window (bucket size = hours/12).
      const bucketHours = Math.max(1, Math.round(RANGE_HOURS[range] / 12))
      apiGetEventsSummary({ buckets: 12, bucket_hours: bucketHours })
        .then((res) => {
          setEventSummary(res)
          setEventSummaryError("")
        })
        .catch((err: unknown) => setEventSummaryError(err instanceof ApiError ? err.message : "Could not load event volume."))
    },
    [range],
  )

  async function reload() {
    setLoading(true)
    await delay(null)
    setLoading(false)
    setLastUpdated(new Date())
  }

  // Re-runs whenever the time range changes too, so the SegmentedControl
  // actually recomputes the mock data (and exercises the skeletons).
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    delay(null).then(() => {
      if (!cancelled) {
        setLoading(false)
        setLastUpdated(new Date())
      }
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range])

  // The real event volume follows the same range control.
  useEffect(() => {
    loadEventSummary()
  }, [loadEventSummary])

  const kpis = useMemo(() => getSocKpis(state, scope), [state, scope])
  const triageRows = useMemo(() => getTriageQueue(state, scope), [state, scope])
  const visibleTriageRows = triageRows.slice(0, 10)
  const aiInsights = useMemo(() => getAiInsights(state, scope), [state, scope])
  const deviceHealth = useMemo(() => getDeviceHealth(state, scope), [state, scope])
  const activeIncidents = useMemo(() => getActiveIncidents(state, scope, 4), [state, scope])

  // Real numbers: the sparkline draws the backend's timeline buckets and
  // the summary line reports the real total for the window.
  const volume = useMemo(
    () =>
      (eventSummary?.timeline ?? []).map((value, i) => ({
        label: `${i}`,
        value,
      })),
    [eventSummary],
  )
  const volumeTotal = eventSummary?.total ?? 0
  const volumeSummary = eventSummary
    ? `${volumeTotal} event${volumeTotal === 1 ? "" : "s"} ingested in the selected ${range} window`
    : "Event volume unavailable"

  function handleAcknowledge(row: TriageRow) {
    dispatch({ type: "ACK_ALERT", alertId: row.alert.id, actorName: scope.displayName })
    toast.show(`Acknowledged "${row.alert.title}".`, { tone: "success" })
  }

  function handleAssignToMe(row: TriageRow) {
    dispatch({ type: "ASSIGN_ALERT_TO_ME", alertId: row.alert.id, userId: scope.userId, actorName: scope.displayName })
    toast.show(`Assigned "${row.alert.title}" to you.`, { tone: "success" })
  }

  function handleEscalate(row: TriageRow) {
    const incidentId = `incident-live-${row.alert.id}`
    dispatch({ type: "ESCALATE_ALERT", alertId: row.alert.id, actorName: scope.displayName })
    toast.show(`Escalated "${row.alert.title}" to a new incident.`, {
      tone: "info",
      actionLabel: "View incident",
      onAction: () => {
        navigate(`/soc/incidents/${incidentId}`)
      },
    })
  }

  function confirmDismiss(reason?: string) {
    if (!dismissTarget) return
    const row = dismissTarget
    const previousStatus = row.alert.status
    dispatch({
      type: "DISMISS_ALERT",
      alertId: row.alert.id,
      reason: reason ?? "",
      actorName: scope.displayName,
    })
    setDismissTarget(null)
    toast.show(`Dismissed "${row.alert.title}" as a false positive.`, {
      tone: "info",
      actionLabel: "Undo",
      onAction: () => {
        dispatch({
          type: "RESTORE_ALERT_STATUS",
          alertId: row.alert.id,
          status: previousStatus,
          actorName: scope.displayName,
        })
      },
    })
  }

  const hasWork = triageRows.length > 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Security Operations Overview</h1>
          <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
            Last updated{" "}
            <time dateTime={lastUpdated.toISOString()} title={lastUpdated.toString()}>
              {lastUpdated.toLocaleTimeString()}
            </time>
            <DemoDataChip />
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl options={RANGE_OPTIONS} value={range} onChange={setRange} ariaLabel="Time range" />
          <IconButton icon={RefreshCw} label="Refresh dashboard" onClick={reload} />
        </div>
      </div>

      <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {loading
          ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
          : kpis.map((kpi) => <KpiCard key={kpi.label} {...kpi} />)}
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <section className="xl:col-span-2" aria-label="Triage queue">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-fg-primary">Triage queue</h2>
            {hasWork && (
              <Link to="/soc/alerts" className="text-xs font-medium text-brand-400 hover:text-brand-300">
                View all alerts
              </Link>
            )}
          </div>
          <TriageQueueTable
            rows={visibleTriageRows}
            loading={loading}
            onOpenDetail={setSelectedRow}
            onAcknowledge={handleAcknowledge}
            onAssignToMe={handleAssignToMe}
            onDismiss={setDismissTarget}
            onEscalate={handleEscalate}
          />
        </section>

        <div className="space-y-4">
          <section aria-label="AI insights" className="rounded-card border border-line bg-surface p-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-fg-primary">
              AI insights <span className="text-xs font-normal text-fg-faint">-- verify before acting</span>
            </h2>
            {loading ? (
              <Skeleton count={3} className="h-14 w-full" />
            ) : aiInsights.length === 0 ? (
              <p className="mt-2 text-xs text-fg-muted">No AI findings for the current queue.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {aiInsights.map((insight) => (
                  <li key={insight.id} className="rounded-control border border-line bg-surface-sunken p-3 text-xs">
                    <p className="text-fg-secondary">{insight.text}</p>
                    <Link
                      to={insight.link}
                      className="mt-1.5 inline-block font-medium text-brand-400 hover:text-brand-300"
                    >
                      {insight.linkLabel}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="Event volume" className="rounded-card border border-line bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-fg-primary">Event volume</h2>
              <IconButton icon={RefreshCw} label="Refresh event volume" onClick={loadEventSummary} />
            </div>
            {eventSummaryError ? (
              <p className="mt-3 text-xs text-danger-fg">{eventSummaryError}</p>
            ) : !eventSummary ? (
              <Skeleton className="mt-3 h-12 w-full" />
            ) : (
              <>
                <div className="mt-3">
                  <Sparkline points={volume} summary={volumeSummary} />
                </div>
                <p className="mt-2 text-xs text-fg-muted">{volumeSummary}</p>
              </>
            )}
          </section>

          <section aria-label="Agent and device health" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Agent &amp; device health</h2>
            {loading ? (
              <Skeleton count={2} className="h-6 w-full" />
            ) : (
              <>
                <div className="mt-3 flex items-center gap-4 text-xs">
                  <span className="flex items-center gap-1.5 text-fg-secondary">
                    <Wifi size={14} className="text-success-fg" aria-hidden="true" />
                    {deviceHealth.connected} connected
                  </span>
                  <span className="flex items-center gap-1.5 text-fg-secondary">
                    <ServerOff size={14} className="text-critical-fg" aria-hidden="true" />
                    {deviceHealth.offline} offline
                  </span>
                </div>
                {deviceHealth.offlineList.length > 0 && (
                  <ul className="mt-3 space-y-1.5">
                    {deviceHealth.offlineList.slice(0, 5).map((asset) => (
                      <li key={asset.id} className="flex items-center justify-between text-xs text-fg-muted">
                        <span>{asset.hostname}</span>
                        <span title={new Date(asset.lastSeenAt).toString()}>
                          since {new Date(asset.lastSeenAt).toLocaleDateString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      <section aria-label="Active incidents">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg-primary">Active incidents</h2>
          <Link to="/soc/incidents" className="text-xs font-medium text-brand-400 hover:text-brand-300">
            View all incidents
          </Link>
        </div>
        {loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-28 w-full rounded-card" />
            ))}
          </div>
        ) : activeIncidents.length === 0 ? (
          <p className="text-xs text-fg-muted">No active incidents right now.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {activeIncidents.map((incident) => {
              const assignee = getUserById(state, incident.assigneeUserId)
              return (
                <Link
                  key={incident.id}
                  to={`/soc/incidents/${incident.id}`}
                  className="rounded-card border border-line bg-surface p-3 text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                >
                  <div className="flex items-center justify-between gap-2">
                    <SeverityBadge severity={incident.severity} showIcon />
                    <Badge tone="neutral">{incident.status}</Badge>
                  </div>
                  <p className="mt-2 line-clamp-2 font-medium text-fg-primary">{incident.title}</p>
                  <p className="mt-2 text-fg-muted">
                    Age {Math.round((Date.now() - new Date(incident.openedAt).getTime()) / (60 * 60 * 1000))}h &middot;{" "}
                    {assignee?.name ?? "Unassigned"}
                  </p>
                </Link>
              )
            })}
          </div>
        )}
      </section>

      {!loading && !hasWork && (
        <EmptyState
          title="Queue is clear"
          description="Nothing needs your attention right now -- new alerts will show up here as they come in."
        />
      )}

      <AlertDetailDrawer
        open={selectedRow !== null}
        onClose={() => setSelectedRow(null)}
        alert={selectedRow?.alert ?? null}
        asset={selectedRow ? getAssetById(state, selectedRow.alert.assetId) : undefined}
        assignee={selectedRow ? selectedRow.assignee : undefined}
      />

      <ConfirmDialog
        open={dismissTarget !== null}
        onClose={() => setDismissTarget(null)}
        onConfirm={confirmDismiss}
        title="Dismiss as false positive?"
        impact={`"${dismissTarget?.alert.title ?? ""}" will be marked dismissed. You can undo this from the confirmation toast.`}
        requireReason
        confirmLabel="Dismiss"
        danger
      />
    </div>
  )
}

export default SocOverview
