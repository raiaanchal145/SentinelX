import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { RefreshCw } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import { useToast } from "../../../components/ui/Toast"
import { ApiError, apiListIncidents, type IncidentRow } from "../../../lib/api"
import { useMe } from "../../../lib/me"

import IncidentFilters from "../components/IncidentFilters"
import { INITIAL_INCIDENT_FILTERS, incidentRangeHours, type IncidentFilterState } from "../components/IncidentFilters"
import IncidentTable from "../components/IncidentTable"

const PAGE_SIZE = 50

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

function hasAnyFilter(filters: IncidentFilterState): boolean {
  return (
    filters.status !== "" ||
    filters.severity !== "" ||
    filters.range !== "30d" ||
    filters.assignedToMe ||
    filters.organizationId !== ""
  )
}

/** The in-house SOC analyst's incident queue (module `incidents` read).
 * All data comes from GET /incidents -- the backend scopes it to the
 * caller's organization and decides write access; this page is the
 * read/write analyst surface. */
function SocIncidents() {
  const { me } = useMe()
  const toast = useToast()
  const navigate = useNavigate()

  const [filters, setFilters] = useState<IncidentFilterState>(INITIAL_INCIDENT_FILTERS)
  const [incidents, setIncidents] = useState<IncidentRow[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListIncidents({
          status: filters.status || undefined,
          severity: filters.severity || undefined,
          assignee: filters.assignedToMe ? "me" : undefined,
          time_from: filters.range === "all" ? undefined : isoAgo(incidentRangeHours(filters.range)),
          limit: PAGE_SIZE,
        })
        setIncidents(res.incidents)
        setNextCursor(res.next_cursor)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load incidents.")
      } finally {
        setLoading(false)
      }
    },
    [filters],
  )

  useEffect(() => {
    load()
  }, [load])

  const assigneeName = useCallback(
    (incident: IncidentRow): string | null => {
      if (!incident.assigned_account_id) return null
      if (incident.assigned_account_id === me?.id) return me?.name || "Me"
      return "Another analyst"
    },
    [me],
  )

  const openCount = useMemo(
    () => incidents.filter((i) => i.status !== "RESOLVED" && i.status !== "CLOSED" && i.status !== "FALSE_POSITIVE" && i.status !== "DUPLICATE").length,
    [incidents],
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Incidents</h1>
          <p className="mt-0.5 text-xs text-fg-muted">
            The controlled lifecycle: triage, investigate, contain, remediate, verify.{openCount > 0 ? ` ${openCount} open on this page.` : ""}
          </p>
        </div>
        <IconButton icon={RefreshCw} label="Refresh incidents" onClick={load} />
      </div>

      <IncidentFilters value={filters} onChange={setFilters} />

      <IncidentTable
        incidents={incidents}
        loading={loading}
        error={error}
        onRetry={load}
        onOpen={(incident) => navigate(`/soc/incidents/${incident.id}`)}
        assigneeName={assigneeName}
        emptyTitle="No incidents"
        emptyDescription={
          hasAnyFilter(filters)
            ? "No incidents match these filters. Widen the time range or clear a filter."
            : "No incidents yet. Create one from selected alerts on the Alerts page."
        }
        ariaLabel="Incident queue"
      />

      {!loading && !error && nextCursor && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={async () => {
              try {
                const res = await apiListIncidents({
                  status: filters.status || undefined,
                  severity: filters.severity || undefined,
                  assignee: filters.assignedToMe ? "me" : undefined,
                  time_from: filters.range === "all" ? undefined : isoAgo(incidentRangeHours(filters.range)),
                  limit: PAGE_SIZE,
                  cursor: nextCursor,
                })
                setIncidents((prev) => [...prev, ...res.incidents.filter((i) => !prev.some((p) => p.id === i.id))])
                setNextCursor(res.next_cursor)
              } catch (err) {
                toast.show(err instanceof ApiError ? err.message : "Could not load more incidents.", { tone: "danger" })
              }
            }}
            className="rounded-control border border-line bg-surface px-4 py-2 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
          >
            Load more
          </button>
        </div>
      )}

      {!loading && !error && incidents.length === 0 && !hasAnyFilter(filters) && (
        <EmptyState
          title="Queue is clear"
          description="Every incident is resolved, closed or dismissed -- nothing is waiting on you."
        />
      )}
    </div>
  )
}

export default SocIncidents
