import { useCallback, useEffect, useMemo, useState } from "react"
import { ShieldCheck } from "lucide-react"

import ReadOnlyChip from "../../../components/shared/ReadOnlyChip"
import AlertTable from "../components/AlertTable"
import AlertDrawer from "../components/AlertDrawer"
import AlertKpiRow from "../components/AlertKpiRow"
import AlertFilters from "../components/AlertFilters"
import { alertRangeHours, INITIAL_ALERT_FILTERS, type AlertFilterState } from "../components/alertFilterShared"
import { minutesSince } from "../components/alertShared"
import { ApiError, apiListAlerts, type AlertRow } from "../../../lib/api"
import { useMe } from "../../../lib/me"

const PAGE_SIZE = 200

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

/** Read-only oversight for a MANAGED organization's owner and security
 * manager: they see their organization's alert counts and details, but
 * every action button is hidden -- the platform SOC team works this
 * queue (backend refuses writes with 403 alert_write_not_allowed; the
 * UI matches that by never offering an action). Also used in-house as a
 * read-only view, since it simply renders what GET /alerts returns for
 * the caller. */
function SecurityActivity() {
  const { me } = useMe()
  const managed = me?.organization?.soc_mode === "managed"

  const [filters, setFilters] = useState<AlertFilterState>(INITIAL_ALERT_FILTERS)
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selected, setSelected] = useState<AlertRow | null>(null)

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListAlerts({
          status: filters.status || undefined,
          severity: filters.severity || undefined,
          time_from: filters.range === "all" ? undefined : isoAgo(alertRangeHours(filters.range)),
          limit: PAGE_SIZE,
        })
        setAlerts(res.alerts)
        setError("")
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load security activity.")
      } finally {
        setLoading(false)
      }
    },
    [filters],
  )

  useEffect(() => {
    load()
  }, [load])

  const lastEventMinutes = useMemo(() => {
    const latest = alerts.map((a) => a.last_seen_at).filter((t): t is string => !!t).sort().at(-1)
    return latest ? minutesSince(latest) : null
  }, [alerts])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Security activity</h1>
          <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
            Alert activity in {me?.organization?.name ?? "your organization"}.
            {managed && (
              <span className="inline-flex items-center gap-1.5 rounded-pill border border-brand-500/20 bg-brand-500/10 px-2 py-0.5 text-[11px] font-medium text-brand-300">
                <ShieldCheck size={11} aria-hidden="true" />
                Handled by the platform SOC team
              </span>
            )}
            <ReadOnlyChip />
          </p>
        </div>
      </div>

      {managed && (
        <p className="rounded-card border border-brand-500/20 bg-brand-500/5 p-3 text-xs text-fg-secondary">
          Your organization's SOC is <strong>managed</strong>: the platform SOC team triages and responds to these
          alerts. This page is read-only -- contact your platform SOC for changes.
        </p>
      )}

      <AlertKpiRow alerts={alerts} loading={loading && alerts.length === 0} alertsPath="" />

      <AlertFilters value={filters} onChange={setFilters} />

      <AlertTable
        alerts={alerts}
        loading={loading}
        error={error}
        onRetry={load}
        onOpen={setSelected}
        emptyTitle="No security activity"
        emptyDescription={
          lastEventMinutes !== null
            ? `No alerts right now -- the last event arrived ${lastEventMinutes} minute${lastEventMinutes === 1 ? "" : "s"} ago.`
            : "No alerts have fired in your organization yet."
        }
        ariaLabel="Security activity"
      />

      {/* Detail stays available (oversight is read + inspect); the drawer
          renders no action buttons because canWrite is false. */}
      <AlertDrawer alert={selected} onClose={() => setSelected(null)} canWrite={false} assignees={[]} onChanged={load} />
    </div>
  )
}

export default SecurityActivity
