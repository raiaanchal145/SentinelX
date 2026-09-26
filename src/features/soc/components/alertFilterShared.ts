/** Filter constants + types for the shared SOC alert components. Kept in
 * a separate module from AlertFilters.tsx so that file stays
 * component-only (fast-refresh friendly). */

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
