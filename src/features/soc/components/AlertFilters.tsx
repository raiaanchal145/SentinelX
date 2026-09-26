import { CheckCheck } from "lucide-react"

import SegmentedControl from "../../../components/ui/SegmentedControl"

export const ALERT_SEVERITIES = ["critical", "high", "medium", "low", "info"] as const
export const ALERT_STATUSES = ["new", "triaged", "investigating", "dismissed", "converted"] as const

export type AlertTimeRange = "1h" | "24h" | "7d" | "30d" | "all"

export const ALERT_TIME_RANGES: { value: AlertTimeRange; label: string; hours: number }[] = [
  { value: "1h", label: "1h", hours: 1 },
  { value: "24h", label: "24h", hours: 24 },
  { value: "7d", label: "7d", hours: 168 },
  { value: "30d", label: "30d", hours: 720 },
  { value: "all", label: "All", hours: 0 },
]

export function alertRangeHours(range: AlertTimeRange): number {
  return ALERT_TIME_RANGES.find((r) => r.value === range)?.hours ?? 24
}

export type AlertFilterState = {
  status: "" | (typeof ALERT_STATUSES)[number]
  severity: "" | (typeof ALERT_SEVERITIES)[number]
  range: AlertTimeRange
  assignedToMe: boolean
  organizationId: string
}

export const INITIAL_ALERT_FILTERS: AlertFilterState = {
  status: "",
  severity: "",
  range: "24h",
  assignedToMe: false,
  organizationId: "",
}

export type OrgOption = { id: string; name: string }

type AlertFiltersProps = {
  value: AlertFilterState
  onChange: (next: AlertFilterState) => void
  /** Organization dropdown is only rendered (and only ever populated with
   * ids the backend has already confirmed visible) for platform roles. */
  orgOptions?: OrgOption[]
  disabled?: boolean
}

const selectClass =
  "rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-secondary focus:border-brand-500 focus:outline-none"

/** The filter row above every alert table. Kept dumb: state lives with the
 * page so a filter change refetches from the API rather than filtering a
 * client copy (counts stay honest with the backend's keyset pagination). */
function AlertFilters({ value, onChange, orgOptions, disabled = false }: AlertFiltersProps) {
  const hasFilters =
    value.status !== "" || value.severity !== "" || value.range !== "24h" || value.assignedToMe || value.organizationId !== ""

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-3">
      <select
        aria-label="Filter by status"
        value={value.status}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, status: e.target.value as AlertFilterState["status"] })}
        className={selectClass}
      >
        <option value="">All statuses</option>
        {ALERT_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s === "triaged" ? "Acknowledged" : s === "converted" ? "Converted" : s.charAt(0).toUpperCase() + s.slice(1)}
          </option>
        ))}
      </select>

      <select
        aria-label="Filter by severity"
        value={value.severity}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, severity: e.target.value as AlertFilterState["severity"] })}
        className={selectClass}
      >
        <option value="">All severities</option>
        {ALERT_SEVERITIES.map((s) => (
          <option key={s} value={s}>
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </option>
        ))}
      </select>

      <SegmentedControl
        options={ALERT_TIME_RANGES.map(({ value: v, label }) => ({ value: v, label }))}
        value={value.range}
        onChange={(range) => onChange({ ...value, range })}
        ariaLabel="Time range"
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
          aria-label="Filter by organization"
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
          onClick={() => onChange({ ...INITIAL_ALERT_FILTERS, range: value.range })}
          className="text-xs text-brand-400 hover:text-brand-300"
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

export default AlertFilters
