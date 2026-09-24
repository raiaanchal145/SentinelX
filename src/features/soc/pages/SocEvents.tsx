import { useCallback, useEffect, useMemo, useState } from "react"
import { RefreshCw } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import Drawer from "../../../components/ui/Drawer"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiGetEvent,
  apiListEvents,
  apiListEventSources,
  apiGetMyAssignedOrganizations,
  apiListOrganizations,
  type EventRow,
  type EventSourceRow,
  type SocAnalystAssignedOrg,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

/** The fixed event_type vocabulary the backend validates against
 * (docs/API_CONTRACT.md "The fixed event_type vocabulary"). Grouped
 * for the filter dropdown; keep in sync with
 * backend/app/event_ingestion.py EVENT_TYPE_VOCABULARY. */
const EVENT_TYPES = [
  "auth_success", "auth_failure", "sudo_command", "user_add", "user_delete", "group_change", "package_install",
  "app_error", "app_warning", "app_login", "app_login_failed", "config_change", "permission_change", "api_request", "api_error",
  "container_start", "container_stop", "container_kill", "container_create", "container_destroy", "image_pull", "image_push", "docker_daemon_event",
  "firewall_allow", "firewall_deny", "port_scan", "ids_alert", "connection_allowed", "connection_blocked", "dns_query", "dns_response",
  "logon_success", "logon_failure", "process_create", "service_install", "account_created", "account_disabled", "account_lockout", "log_cleared", "policy_change", "scheduled_task",
  "custom", "test_event", "other",
] as const

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const

const TIME_RANGES = [
  { value: "1h", label: "1h", hours: 1 },
  { value: "24h", label: "24h", hours: 24 },
  { value: "7d", label: "7d", hours: 168 },
  { value: "30d", label: "30d", hours: 720 },
  { value: "all", label: "All", hours: 0 },
] as const

const PAGE_SIZE = 50
const LIVE_INTERVAL_MS = 5000

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

type OrgOption = { id: string; name: string }

/** super_admin gets every organization from the admin list; a platform
 * SOC analyst their assigned ones. Everyone else gets no org filter at
 * all -- the backend decides visibility. Names resolve client-side
 * (no backend join); an event from an org missing from the list falls
 * back to its short id. */
function useOrgOptions(): { orgs: OrgOption[]; canFilter: boolean } {
  const { me } = useMe()
  const [orgs, setOrgs] = useState<OrgOption[]>([])

  const role = me?.role
  const canFilter = role === "super_admin" || role === "platform_soc_analyst"

  useEffect(() => {
    if (!canFilter) return
    let cancelled = false
    if (role === "platform_soc_analyst") {
      apiGetMyAssignedOrganizations()
        .then((res) => !cancelled && setOrgs(res.assigned_organizations.map((o: SocAnalystAssignedOrg) => ({ id: o.id, name: o.name }))))
        .catch(() => !cancelled && setOrgs([]))
    } else {
      apiListOrganizations({ page: 1, page_size: 100 })
        .then((res) => !cancelled && setOrgs(res.organizations.map((o) => ({ id: o.id, name: o.name }))))
        .catch(() => !cancelled && setOrgs([]))
    }
    return () => {
      cancelled = true
    }
  }, [canFilter, role])

  return { orgs, canFilter }
}

function orgName(orgs: OrgOption[], organizationId: string): string {
  return orgs.find((o) => o.id === organizationId)?.name ?? `${organizationId.slice(0, 8)}…`
}

function EventDetailDrawer({
  eventId,
  onClose,
}: {
  eventId: string | null
  onClose: () => void
}) {
  const [event, setEvent] = useState<EventRow | null>(null)
  const [error, setError] = useState("")
  const { show: showToast } = useToast()

  useEffect(() => {
    if (!eventId) {
      setEvent(null)
      setError("")
      return
    }
    setEvent(null)
    setError("")
    apiGetEvent(eventId)
      .then(setEvent)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load this event."))
  }, [eventId])

  const rawJson = useMemo(() => (event?.raw_data != null ? JSON.stringify(event.raw_data, null, 2) : ""), [event])

  async function copyRaw() {
    try {
      await navigator.clipboard.writeText(rawJson)
      showToast("Raw JSON copied.", { tone: "success" })
    } catch {
      showToast("Could not copy to the clipboard.", { tone: "danger" })
    }
  }

  const normalized = event?.normalized_data as Record<string, unknown> | null | undefined
  const asset = normalized?.asset as Record<string, unknown> | null | undefined

  return (
    <Drawer open={eventId !== null} onClose={onClose} title="Event detail" side="right" widthClassName="w-[480px] max-w-[95vw]">
      {error ? (
        <p className="p-4 text-xs text-danger-fg">{error}</p>
      ) : !event ? (
        <div className="space-y-3 p-4">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton count={4} className="h-4 w-full" />
        </div>
      ) : (
        <div className="space-y-5 p-4 text-sm">
          <div className="flex items-center justify-between gap-2">
            <SeverityBadge severity={event.severity as "critical" | "high" | "medium" | "low" | "info"} showIcon />
            <Badge tone="neutral">{event.event_type}</Badge>
          </div>

          <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-xs">
            <dt className="text-fg-muted">Occurred</dt>
            <dd className="text-fg-primary">{event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "--"}</dd>
            <dt className="text-fg-muted">Ingested</dt>
            <dd className="text-fg-primary">{event.ingested_at ? new Date(event.ingested_at).toLocaleString() : "--"}</dd>
            <dt className="text-fg-muted">Host</dt>
            <dd className="text-fg-primary">{String(normalized?.host ?? "--")}</dd>
            <dt className="text-fg-muted">User</dt>
            <dd className="text-fg-primary">{event.username ?? "--"}</dd>
            <dt className="text-fg-muted">IP</dt>
            <dd className="text-fg-primary">{event.source_ip ?? "--"}</dd>
            <dt className="text-fg-muted">Process</dt>
            <dd className="text-fg-primary">{String(normalized?.process ?? "--")}</dd>
            <dt className="text-fg-muted">Source type</dt>
            <dd className="text-fg-primary">{String(normalized?.source_type ?? "--")}</dd>
            <dt className="text-fg-muted">Asset</dt>
            <dd className="text-fg-primary">
              {asset?.id
                ? `${String(asset.criticality ?? "unknown")} criticality${asset.owner ? ` · owner ${String(asset.owner)}` : ""}`
                : "--"}
            </dd>
            <dt className="text-fg-muted">Message</dt>
            <dd className="break-words text-fg-primary">{String(normalized?.message ?? "--")}</dd>
          </dl>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-fg-primary">Raw JSON</h3>
              <button
                type="button"
                onClick={copyRaw}
                className="rounded-control border border-line px-2 py-1 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
              >
                Copy
              </button>
            </div>
            <pre className="max-h-72 overflow-auto rounded-control border border-line bg-surface-sunken p-3 text-[11px] leading-relaxed text-fg-secondary">
              {rawJson || "--"}
            </pre>
          </div>
        </div>
      )}
    </Drawer>
  )
}

function SocEvents() {
  const { orgs, canFilter: canFilterOrg } = useOrgOptions()

  const [rows, setRows] = useState<EventRow[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)

  // Filters. searchInput is the live text box; search commits on
  // Enter/blur so typing doesn't fire a request per keystroke.
  const [range, setRange] = useState<(typeof TIME_RANGES)[number]["value"]>("24h")
  const [eventType, setEventType] = useState("")
  const [severity, setSeverity] = useState("")
  const [sourceId, setSourceId] = useState("")
  const [user, setUser] = useState("")
  const [ip, setIp] = useState("")
  const [organizationId, setOrganizationId] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")

  const [sources, setSources] = useState<EventSourceRow[]>([])
  const [live, setLive] = useState(false)

  const selectClass =
    "rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-secondary focus:border-brand-500 focus:outline-none"

  useEffect(() => {
    apiListEventSources()
      .then((res) => setSources(res.event_sources))
      .catch(() => setSources([]))
  }, [])

  const buildParams = useCallback(
    (extra: { limit?: number; cursor?: string | null } = {}) => ({
      time_from: range === "all" ? undefined : isoAgo(TIME_RANGES.find((r) => r.value === range)!.hours),
      event_type: eventType || undefined,
      severity: severity || undefined,
      source_id: sourceId || undefined,
      user: user || undefined,
      ip: ip || undefined,
      organization_id: organizationId || undefined,
      q: search || undefined,
      ...extra,
    }),
    [range, eventType, severity, sourceId, user, ip, organizationId, search],
  )

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListEvents(buildParams({ limit: PAGE_SIZE }))
        setRows(res.events)
        setNextCursor(res.next_cursor)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load events.")
      } finally {
        setLoading(false)
      }
    },
    [buildParams],
  )

  const loadMore = useCallback(
    async function loadMore() {
      if (!nextCursor) return
      setError("")
      try {
        const res = await apiListEvents(buildParams({ limit: PAGE_SIZE, cursor: nextCursor }))
        setRows((prev) => [...prev, ...res.events.filter((e) => !prev.some((p) => p.id === e.id))])
        setNextCursor(res.next_cursor)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load more events.")
      }
    },
    [buildParams, nextCursor],
  )

  useEffect(() => {
    load()
  }, [load])

  // Live refresh: poll every 5s. Pauses when the tab is hidden so a
  // background tab doesn't hammer the API, and resumes on return.
  useEffect(() => {
    if (!live) return
    function hidden() {
      return typeof document !== "undefined" && document.hidden
    }
    const id = window.setInterval(() => {
      if (!hidden()) {
        load()
      }
    }, LIVE_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [live, load])

  const hasAnyFilter =
    range !== "24h" || eventType !== "" || severity !== "" || sourceId !== "" || user !== "" || ip !== "" || organizationId !== "" || search !== ""

  const columns = [
    { key: "occurred", label: "Time", render: (e: EventRow) => (e.occurred_at ? new Date(e.occurred_at).toLocaleTimeString() : "--") },
    { key: "severity", label: "Severity", render: (e: EventRow) => <SeverityBadge severity={e.severity as "critical" | "high" | "medium" | "low" | "info"} /> },
    { key: "type", label: "Type", render: (e: EventRow) => <Badge tone="neutral">{e.event_type}</Badge> },
    { key: "user", label: "User", render: (e: EventRow) => e.username ?? "--" },
    { key: "ip", label: "IP", render: (e: EventRow) => e.source_ip ?? "--" },
    ...(canFilterOrg
      ? [{ key: "org", label: "Organization", render: (e: EventRow) => <span title={e.organization_id}>{orgName(orgs, e.organization_id)}</span> }]
      : []),
  ] as const

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Events</h1>
          <p className="mt-0.5 text-xs text-fg-muted">Raw and normalized events from every registered source.</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-secondary">
            <input
              type="checkbox"
              checked={live}
              onChange={(e) => setLive(e.target.checked)}
              className="accent-brand-500"
              aria-label="Live refresh every 5 seconds"
            />
            Live
          </label>
          <IconButton icon={RefreshCw} label="Refresh events" onClick={load} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-3">
        <select aria-label="Time range" value={range} onChange={(e) => setRange(e.target.value as typeof range)} className={selectClass}>
          {TIME_RANGES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
        <select aria-label="Event type" value={eventType} onChange={(e) => setEventType(e.target.value)} className={selectClass}>
          <option value="">All types</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)} className={selectClass}>
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select aria-label="Source" value={sourceId} onChange={(e) => setSourceId(e.target.value)} className={selectClass}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        {canFilterOrg && (
          <select aria-label="Organization" value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} className={selectClass}>
            <option value="">All organizations</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        )}
        <input
          aria-label="Filter by user"
          placeholder="User"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setSearch(user)}
          onBlur={() => setSearch(user)}
          className={selectClass}
        />
        <input
          aria-label="Filter by IP"
          placeholder="IP"
          value={ip}
          onChange={(e) => setIp(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setSearch(search)}
          onBlur={() => setSearch(search)}
          className={selectClass}
        />
        <input
          aria-label="Search events"
          placeholder="Search…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") setSearch(searchInput)
          }}
          onBlur={() => setSearch(searchInput)}
          className={`${selectClass} w-44`}
        />
        {hasAnyFilter && (
          <button
            type="button"
            onClick={() => {
              setRange("24h")
              setEventType("")
              setSeverity("")
              setSourceId("")
              setUser("")
              setIp("")
              setOrganizationId("")
              setSearchInput("")
              setSearch("")
            }}
            className="text-xs text-brand-400 hover:text-brand-300"
          >
            Clear filters
          </button>
        )}
      </div>

      {error ? (
        <div className="rounded-card border border-danger-fg/30 bg-surface p-6 text-center">
          <p className="text-sm text-danger-fg">{error}</p>
          <button type="button" onClick={load} className="mt-3 rounded-control border border-line px-3 py-1.5 text-xs text-fg-secondary hover:border-line-strong">
            Try again
          </button>
        </div>
      ) : loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-control" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No events"
          description={
            hasAnyFilter
              ? "No events match these filters. Widen the time range or clear a filter."
              : "No events have been ingested yet. Register an event source, send events with its API key (or run the simulator), and they'll appear here."
          }
        />
      ) : (
        <div className="overflow-hidden rounded-card border border-line">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line bg-surface-sunken text-left text-fg-muted">
                {columns.map((c) => (
                  <th key={c.key} className="px-3 py-2 font-medium">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((event) => (
                <tr
                  key={event.id}
                  onClick={() => setSelectedEventId(event.id)}
                  className="cursor-pointer border-b border-line/60 bg-surface transition last:border-b-0 hover:bg-surface-hover"
                >
                  {columns.map((c) => (
                    <td key={c.key} className="px-3 py-2 text-fg-secondary">
                      {c.render(event)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && nextCursor && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={loadMore}
            className="rounded-control border border-line bg-surface px-4 py-2 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
          >
            Load more
          </button>
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <p className="text-center text-[11px] text-fg-faint">
          Showing {rows.length} event{rows.length === 1 ? "" : "s"} · click a row for normalized fields and raw JSON
        </p>
      )}

      <EventDetailDrawer eventId={selectedEventId} onClose={() => setSelectedEventId(null)} />
    </div>
  )
}

export default SocEvents
