export type Severity = "critical" | "high" | "medium" | "low" | "info"
export type ActorType = "admin" | "user" | "ai_agent" | "system"

const KNOWN_SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"]

/** Normalises "Critical"/"critical"/etc at the data boundary -- see SeverityBadge. */
export function normalizeSeverity(value: string): Severity {
  const lower = value.toLowerCase()
  return (KNOWN_SEVERITIES as string[]).includes(lower) ? (lower as Severity) : "info"
}

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
}
