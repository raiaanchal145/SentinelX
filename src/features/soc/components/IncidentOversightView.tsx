import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { RefreshCw, ShieldCheck } from "lucide-react"

import ReadOnlyChip from "../../../components/shared/ReadOnlyChip"
import IconButton from "../../../components/ui/IconButton"
import { ApiError, apiListIncidents, type IncidentRow } from "../../../lib/api"
import { useMe } from "../../../lib/me"

import IncidentFilters from "./IncidentFilters"
import { INITIAL_INCIDENT_FILTERS, incidentRangeHours, type IncidentFilterState } from "./IncidentFilters"
import IncidentTable from "./IncidentTable"

const PAGE_SIZE = 50

function isoAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

type IncidentOversightViewProps = {
  /** Where rows navigate (the role's own read-only detail route). */
  basePath: string
  /** Heading copy above the filters. */
  intro: string
}

/** The read-only incident oversight used by BOTH the security manager
 * (/manager/incidents) and the organization owner
 * (/organization/incidents): same shared component set, no write
 * controls anywhere (the backend refuses their writes; the detail page
 * offers only what allowed_next_states permits, which is nothing or the
 * manager's escalation). A managed org sees the "handled by the platform
 * SOC team" note, and its timeline arrives shared-only from the API. */
function IncidentOversightView({ basePath, intro }: IncidentOversightViewProps) {
  const { me } = useMe()
  const navigate = useNavigate()

  const [filters, setFilters] = useState<IncidentFilterState>(INITIAL_INCIDENT_FILTERS)
  const [incidents, setIncidents] = useState<IncidentRow[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const managed = me?.organization?.soc_mode === "managed"

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListIncidents({
          status: filters.status || undefined,
          severity: filters.severity || undefined,
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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Incidents</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
            {intro}
            {managed && (
              <span className="inline-flex items-center gap-1.5 rounded-pill border border-brand-500/20 bg-brand-500/10 px-2 py-0.5 text-[11px] font-medium text-brand-300">
                <ShieldCheck size={11} aria-hidden="true" />
                Handled by the platform SOC team
              </span>
            )}
            <ReadOnlyChip />
          </p>
        </div>
        <IconButton icon={RefreshCw} label="Refresh incidents" onClick={load} />
      </div>

      {managed && (
        <p className="rounded-card border border-brand-500/20 bg-brand-500/5 p-3 text-xs text-fg-secondary">
          Your organization's SOC is <strong>managed</strong>: the platform SOC team works these incidents. This page is
          read-only -- contact your platform SOC for changes. Internal SOC notes are not shown.
        </p>
      )}

      <IncidentFilters value={filters} onChange={setFilters} />

      <IncidentTable
        incidents={incidents}
        loading={loading}
        error={error}
        onRetry={load}
        onOpen={(incident) => navigate(`${basePath}/${incident.id}`)}
        emptyTitle="No incidents"
        emptyDescription={
          managed
            ? "The platform SOC team has not opened any incidents for your organization yet."
            : "No incidents have been opened for your organization yet."
        }
        ariaLabel="Incident oversight"
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
                  time_from: filters.range === "all" ? undefined : isoAgo(incidentRangeHours(filters.range)),
                  limit: PAGE_SIZE,
                  cursor: nextCursor,
                })
                setIncidents((prev) => [...prev, ...res.incidents.filter((i) => !prev.some((p) => p.id === i.id))])
                setNextCursor(res.next_cursor)
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Could not load more incidents.")
              }
            }}
            className="rounded-control border border-line bg-surface px-4 py-2 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  )
}

export default IncidentOversightView
