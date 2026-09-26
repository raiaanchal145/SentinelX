import { useCallback, useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Bot, Network, RefreshCw } from "lucide-react"

import IconButton from "../../../components/ui/IconButton"
import SegmentedControl from "../../../components/ui/SegmentedControl"
import Skeleton from "../../../components/ui/Skeleton"
import Sparkline from "../../../components/ui/Sparkline"
import { useToast } from "../../../components/ui/Toast"

import {
  ApiError,
  apiAcknowledgeAlert,
  apiDismissAlert,
  apiGetEventsSummary,
  apiListAlerts,
  apiListAssets,
  type AlertRow,
  type EventSummary,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

import AlertDrawer from "../components/AlertDrawer"
import AlertKpiRow from "../components/AlertKpiRow"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import TriageQueue from "../components/TriageQueue"
import { minutesSince } from "../components/alertShared"

type Range = "24h" | "7d" | "30d"

const RANGE_HOURS: Record<Range, 24 | 168 | 720> = { "24h": 24, "7d": 168, "30d": 720 }
const RANGE_OPTIONS: { value: Range; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
]

/** The in-house SOC analyst's overview (real data only). KPIs and the
 * triage queue come from GET /alerts; event volume from GET
 * /events/summary; device/agent health and AI remain clearly-labelled
 * disabled placeholders until their milestones land. */
function SocOverview() {
  const { me } = useMe()
  const toast = useToast()

  const [range, setRange] = useState<Range>("24h")
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [alertsLoading, setAlertsLoading] = useState(true)
  const [alertsError, setAlertsError] = useState("")
  const [selected, setSelected] = useState<AlertRow | null>(null)
  const [ackTarget, setAckTarget] = useState<AlertRow | null>(null)
  const [dismissTarget, setDismissTarget] = useState<AlertRow | null>(null)

  // Real event volume (P07 read API); bucket count follows the range.
  const [eventSummary, setEventSummary] = useState<EventSummary | null>(null)
  const [eventSummaryError, setEventSummaryError] = useState("")

  const readOnly = me?.organization?.soc_mode === "managed"

  const loadAlerts = useCallback(async function loadAlerts() {
    setAlertsLoading(true)
    setAlertsError("")
    try {
      // Open (not dismissed/converted) alerts, newest activity first --
      // the triage queue ranks them by urgency client-side.
      const res = await apiListAlerts({ time_from: isoAgo(30 * 24), limit: 200 })
      setAlerts(res.alerts.filter((a) => a.status !== "dismissed" && a.status !== "converted"))
      setAlertsError("")
    } catch (err) {
      setAlertsError(err instanceof ApiError ? err.message : "Could not load alerts.")
    } finally {
      setAlertsLoading(false)
    }
  }, [])

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

  useEffect(() => {
    loadAlerts()
  }, [loadAlerts])

  useEffect(() => {
    loadEventSummary()
  }, [loadEventSummary])

  // Asset criticality feeds the triage ordering; a failure here is
  // non-fatal (the queue just ranks by severity + age).
  const [criticality, setCriticality] = useState<Map<string, number>>(new Map())
  useEffect(() => {
    apiListAssets({ page: 1, page_size: 100 })
      .then((res) => {
        const rank: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 }
        setCriticality(new Map(res.assets.map((a) => [a.id, rank[a.criticality] ?? 0])))
      })
      .catch(() => setCriticality(new Map()))
  }, [])

  const volume = useMemo(
    () => (eventSummary?.timeline ?? []).map((value, i) => ({ label: `${i}`, value })),
    [eventSummary],
  )
  const volumeTotal = eventSummary?.total ?? 0
  const volumeSummary = eventSummary
    ? `${volumeTotal} event${volumeTotal === 1 ? "" : "s"} ingested in the selected ${range} window`
    : "Event volume unavailable"

  const lastEventMinutes = useMemo(() => {
    const latest = alerts.map((a) => a.last_seen_at).filter((t): t is string => !!t).sort().at(-1)
    return latest ? minutesSince(latest) : null
  }, [alerts])

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
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Security Operations Overview</h1>
          <p className="mt-0.5 text-xs text-fg-muted">Live alerts and event volume for your organization.</p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl options={RANGE_OPTIONS} value={range} onChange={setRange} ariaLabel="Time range" />
          <IconButton icon={RefreshCw} label="Refresh dashboard" onClick={() => { loadAlerts(); loadEventSummary() }} />
        </div>
      </div>

      <AlertKpiRow alerts={alerts} loading={alertsLoading && alerts.length === 0} />

      {alertsError && (
        <div className="rounded-card border border-danger-fg/30 bg-surface p-6 text-center">
          <p className="text-sm text-danger-fg">{alertsError}</p>
          <button
            type="button"
            onClick={loadAlerts}
            className="mt-3 rounded-control border border-line px-3 py-1.5 text-xs text-fg-secondary hover:border-line-strong"
          >
            Try again
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <section className="xl:col-span-2" aria-label="Triage queue">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-fg-primary">Triage queue</h2>
            {!alertsLoading && alerts.length > 0 && (
              <Link to="/soc/alerts" className="text-xs font-medium text-brand-400 hover:text-brand-300">
                View all alerts
              </Link>
            )}
          </div>
          <TriageQueue
            alerts={alerts.slice(0, 10)}
            loading={alertsLoading}
            criticalityOf={(assetId) => (assetId ? criticality.get(assetId) ?? 0 : 0)}
            onOpen={setSelected}
            onAcknowledge={setAckTarget}
            onDismiss={setDismissTarget}
            canWrite={!readOnly}
            emptyDescription={
              lastEventMinutes !== null
                ? `No alerts need triage -- the last event arrived ${lastEventMinutes} minute${lastEventMinutes === 1 ? "" : "s"} ago.`
                : "Nothing is waiting. New alerts appear here as the detection rules fire."
            }
          />
        </section>

        <div className="space-y-4">
          <section aria-label="Event volume" className="rounded-card border border-line bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-fg-primary">Event volume</h2>
              <IconButton icon={RefreshCw} label="Refresh event volume" onClick={loadEventSummary} />
            </div>
            {eventSummaryError ? (
              <div className="mt-3">
                <p className="text-xs text-danger-fg">{eventSummaryError}</p>
                <button type="button" onClick={loadEventSummary} className="mt-2 text-xs text-brand-400 hover:text-brand-300">
                  Try again
                </button>
              </div>
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

          {/* PLACEHOLDER: device/agent health arrives with the device_agents
              milestone; disabled so the slot is visible but clearly not live. */}
          <section aria-label="Device and agent health (placeholder)" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Agent &amp; device health</h2>
            <div className="mt-3 flex items-center gap-2 rounded-control border border-dashed border-line bg-surface-sunken p-3 text-xs text-fg-muted">
              <Network size={14} aria-hidden="true" />
              Device and agent health arrives with the device-agents milestone.
            </div>
          </section>

          {/* PLACEHOLDER: AI insights arrive with the ai_agents milestone. */}
          <section aria-label="AI insights (placeholder)" className="rounded-card border border-line bg-surface p-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-fg-primary">
              AI insights <span className="text-xs font-normal text-fg-faint">-- not available yet</span>
            </h2>
            <div className="mt-3 flex items-center gap-2 rounded-control border border-dashed border-line bg-surface-sunken p-3 text-xs text-fg-muted">
              <Bot size={14} aria-hidden="true" />
              AI analysis of the current queue arrives with the AI-agents milestone.
            </div>
          </section>
        </div>
      </div>

      <AlertDrawer alert={selected} onClose={() => setSelected(null)} canWrite={!readOnly} assignees={[]} onChanged={loadAlerts} />

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
    </div>
  )
}

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

export default SocOverview
