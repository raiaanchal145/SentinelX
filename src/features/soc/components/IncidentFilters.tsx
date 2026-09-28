import { CheckCheck } from "lucide-react"

import SegmentedControl from "../../../components/ui/SegmentedControl"

import { INCIDENT_SEVERITIES, INCIDENT_STATUS_LABELS, INCIDENT_STATUSES } from "./incidentShared"

export type IncidentTimeRange = "1h" | "24h" | "7d" | "30d" | "all"

export const INCIDENT_TIME_RANGES: { value: IncidentTimeRange; label: string; hours: number }[] = [
  { value: "1h", label: "1h", hours: 1 },
  { value: "24h", label: "24h", hours: 24 },
  { value: "7d", label: "7d", hours: 168 },
  { value: "30d", label: "30d", hours: 720 },
  { value: "all", label: "All", hours: 0 },
]

export function incidentRangeHours(range: IncidentTimeRange): number {
  return INCIDENT_TIME_RANGES.find((r) => r.value === range)?.hours ?? 24
}

export type IncidentFilterState = {
  status: "" | (typeof INCIDENT_STATUSES)[number]
  severity: "" | (typeof INCIDENT_SEVERITIES)[number]
  range: IncidentTimeRange
  assignedToMe: boolean
  organizationId: string
}

export const INITIAL_INCIDENT_FILTERS: IncidentFilterState = {
  status: "",
  severity: "",
  range: "30d",
  assignedToMe: false,
  organizationId: "",
}

export type IncidentOrgOption = { id: string; name: string }

type IncidentFiltersProps = {
  value: IncidentFilterState
  onChange: (next: IncidentFilterState) => void
  /** Organization dropdown only for platform roles (populated with ids the
   * backend has already confirmed visible). */
  orgOptions?: IncidentOrgOption[]
  disabled?: boolean
}

const selectClass =
  "rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-secondary focus:border-brand-500 focus:outline-none"

/** The filter row above every incident table. Kept dumb: state lives with
 * the page so a filter change refetches from the API rather than filtering
 * a client copy (counts stay honest with the backend's keyset cursor). */
function IncidentFilters({ value, onChange, orgOptions, disabled = false }: IncidentFiltersProps) {
  const hasFilters =
    value.status !== "" || value.severity !== "" || value.range !== "30d" || value.assignedToMe || value.organizationId !== ""

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-3">
      <select
        aria-label="Filter incidents by status"
        value={value.status}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, status: e.target.value as IncidentFilterState["status"] })}
        className={selectClass}
      >
        <option value="">All statuses</option>
        {INCIDENT_STATUSES.map((s) => (
          <option key={s} value={s}>
            {INCIDENT_STATUS_LABELS[s]}
          </option>
        ))}
      </select>

      <select
        aria-label="Filter incidents by severity"
        value={value.severity}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, severity: e.target.value as IncidentFilterState["severity"] })}
        className={selectClass}
      >
        <option value="">All severities</option>
        {INCIDENT_SEVERITIES.map((s) => (
          <option key={s} value={s}>
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </option>
        ))}
      </select>

      <SegmentedControl
        options={INCIDENT_TIME_RANGES.map(({ value: v, label }) => ({ value: v, label }))}
        value={value.range}
        onChange={(range) => onChange({ ...value, range })}
        ariaLabel="Incident time range"
      />

      <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-secondary">
        <input
          type="checkbox"
          checked={value.assignedToMe}
          disabled={disabled}
          onChange={(e) => onChange({ ...value, assignedToMe: e.target.checked })}
          className="accent-brand-500"
        />
        <CheckCheck size={13} aria-hidden="true" />
        Assigned to me
      </label>

      {orgOptions && (
        <select
          aria-label="Filter incidents by organization"
          value={value.organizationId}
          disabled={disabled}
          onChange={(e) => onChange({ ...value, organizationId: e.target.value })}
          className={selectClass}
        >
          <option value="">All organizations</option>
          {orgOptions.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      )}

      {hasFilters && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange({ ...INITIAL_INCIDENT_FILTERS, range: value.range })}
          className="text-xs text-brand-400 hover:text-brand-300"
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

export default IncidentFilters
