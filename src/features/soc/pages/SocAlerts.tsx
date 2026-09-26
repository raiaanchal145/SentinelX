import { useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"

import AlertFilters from "../components/AlertFilters"
import { alertRangeHours, INITIAL_ALERT_FILTERS, type AlertFilterState } from "../components/alertFilterShared"
import AlertTable from "../components/AlertTable"
import AlertDrawer from "../components/AlertDrawer"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import IconButton from "../../../components/ui/IconButton"
import { useToast } from "../../../components/ui/Toast"
import { RefreshCw } from "lucide-react"
import {
  ApiError,
  apiDismissAlert,
  apiListAlerts,
  apiAcknowledgeAlert,
  type AlertRow,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"
import { minutesSince } from "../components/alertShared"

const PAGE_SIZE = 50

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

/** The in-house SOC analyst's alert queue (module `soc` read; the
 * platform SOC's multi-organization queue is /admin/soc-queue). All
 * data comes from GET /alerts -- the backend scopes it to the caller's
 * organization and decides write access per alert. */
function SocAlerts() {
  const { me } = useMe()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()

  const [filters, setFilters] = useState<AlertFilterState>(() => ({
    ...INITIAL_ALERT_FILTERS,
    status: (searchParams.get("status") as AlertFilterState["status"]) || "",
    severity: (searchParams.get("severity") as AlertFilterState["severity"]) || "",
  }))
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selected, setSelected] = useState<AlertRow | null>(null)
  const [ackTarget, setAckTarget] = useState<AlertRow | null>(null)
  const [dismissTarget, setDismissTarget] = useState<AlertRow | null>(null)

  // Read-only when the org is managed: the backend returns
  // alert_write_not_allowed for its own accounts, so the UI hides the
  // action buttons instead of offering actions that will fail.
  const readOnly = me?.organization?.soc_mode === "managed"

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListAlerts({
          status: filters.status || undefined,
          severity: filters.severity || undefined,
          assigned_to_me: filters.assignedToMe || undefined,
          time_from: filters.range === "all" ? undefined : isoAgo(alertRangeHours(filters.range)),
          limit: PAGE_SIZE,
        })
        setAlerts(res.alerts)
        setNextCursor(res.next_cursor)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load alerts.")
      } finally {
        setLoading(false)
      }
    },
    [filters],
  )

  useEffect(() => {
    load()
  }, [load])

  // Keep the URL shareable: status/severity filters land in the query string.
  useEffect(() => {
    const params = new URLSearchParams()
    if (filters.status) params.set("status", filters.status)
    if (filters.severity) params.set("severity", filters.severity)
    setSearchParams(params, { replace: true })
  }, [filters.status, filters.severity, setSearchParams])

  const lastEventMinutes = useMemo(() => {
    const latest = alerts
      .map((a) => a.last_seen_at)
      .filter((t): t is string => !!t)
      .sort()
      .at(-1)
    return latest ? minutesSince(latest) : null
  }, [alerts])

  function handleKeyDown(alert: AlertRow, event: React.KeyboardEvent<HTMLTableRowElement>) {
    if (event.key === "a" && !readOnly && alert.status === "new") {
      event.preventDefault()
      setAckTarget(alert)
    }
  }

  async function confirmAcknowledge() {
    if (!ackTarget) return
    const target = ackTarget
    setAckTarget(null)
    try {
      await apiAcknowledgeAlert(target.id)
      toast.show(`Acknowledged "${target.title}".`, { tone: "success" })
      load()
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
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not dismiss the alert.", { tone: "danger" })
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Alerts</h1>
          <p className="mt-0.5 text-xs text-fg-muted">
            Detection and correlation alerts for your organization{readOnly ? " (read-only -- the platform SOC team works this queue)" : ""}.
          </p>
        </div>
        <IconButton icon={RefreshCw} label="Refresh alerts" onClick={load} />
      </div>

      <AlertFilters value={filters} onChange={setFilters} />

      <AlertTable
        alerts={alerts}
        loading={loading}
        error={error}
        onRetry={load}
        onOpen={setSelected}
        onRowKeyDown={handleKeyDown}
        emptyTitle="No alerts"
        emptyDescription={
          hasAnyFilter(filters)
            ? "No alerts match these filters. Widen the time range or clear a filter."
            : lastEventMinutes !== null
              ? `No alerts right now -- the last event arrived ${lastEventMinutes} minute${lastEventMinutes === 1 ? "" : "s"} ago.`
              : "No alerts have fired yet. Events appear here once the detection rules match them."
        }
      />

      {!loading && !error && nextCursor && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={async () => {
              try {
                const res = await apiListAlerts({
                  status: filters.status || undefined,
                  severity: filters.severity || undefined,
                  assigned_to_me: filters.assignedToMe || undefined,
                  time_from: filters.range === "all" ? undefined : isoAgo(alertRangeHours(filters.range)),
                  limit: PAGE_SIZE,
                  cursor: nextCursor,
                })
                setAlerts((prev) => [...prev, ...res.alerts.filter((a) => !prev.some((p) => p.id === a.id))])
                setNextCursor(res.next_cursor)
              } catch (err) {
                toast.show(err instanceof ApiError ? err.message : "Could not load more alerts.", { tone: "danger" })
              }
            }}
            className="rounded-control border border-line bg-surface px-4 py-2 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
          >
            Load more
          </button>
        </div>
      )}

      <AlertDrawer
        alert={selected}
        onClose={() => setSelected(null)}
        canWrite={!readOnly}
        assignees={[]}
        onChanged={load}
      />

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

function hasAnyFilter(filters: AlertFilterState): boolean {
  return filters.status !== "" || filters.severity !== "" || filters.range !== "24h" || filters.assignedToMe || filters.organizationId !== ""
}

export default SocAlerts
