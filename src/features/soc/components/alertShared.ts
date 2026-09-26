import type { AlertRow, AlertStatus } from "../../../lib/api"
import type { Severity } from "../../../types/common"

/** "just now" / "5m" / "3h" / "2d" label for an ISO timestamp relative to now. */
export function ageLabel(iso: string | null): string {
  if (!iso) return "--"
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(ms / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

/** Minutes elapsed since `iso` (floored, >= 0); used by the KPI row and empty states. */
export function minutesSince(iso: string | null): number {
  if (!iso) return 0
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60_000))
}

/** Median age in minutes of the given alerts (by last_seen_at). */
export function medianAgeMinutes(alerts: AlertRow[]): number {
  const values = alerts
    .map((a) => minutesSince(a.first_seen_at))
    .sort((a, b) => a - b)
  if (values.length === 0) return 0
  const mid = Math.floor(values.length / 2)
  const median = values.length % 2 === 0 ? (values[mid - 1] + values[mid]) / 2 : values[mid]
  return Math.round(median)
}

export const ALERT_STATUS_LABELS: Record<AlertStatus, string> = {
  new: "New",
  triaged: "Acknowledged",
  investigating: "Investigating",
  dismissed: "Dismissed",
  converted: "Converted",
}

/** Human text for a history action name from the backend. */
export function historyActionLabel(action: string): string {
  const labels: Record<string, string> = {
    create: "Created",
    acknowledge: "Acknowledged",
    assign: "Assigned",
    dismiss: "Dismissed",
    reopen: "Reopened",
  }
  return labels[action] ?? action
}

/**
 * Client-side KPI computation over an alerts page (limit-capped; see the
 * page-level note on the 200-alert cap chosen in docs/DECISIONS.md).
 * "Open" = not dismissed/converted; "unacknowledged" = still `new`.
 */
export function computeAlertKpis(alerts: AlertRow[]): {
  open: number
  unacknowledged: number
  medianAge: number
  bySeverity: Record<string, number>
} {
  const open = alerts.filter((a) => a.status !== "dismissed" && a.status !== "converted")
  const bySeverity: Record<string, number> = {}
  for (const alert of open) {
    bySeverity[alert.severity] = (bySeverity[alert.severity] ?? 0) + 1
  }
  return {
    open: open.length,
    unacknowledged: open.filter((a) => a.status === "new").length,
    medianAge: medianAgeMinutes(open),
    bySeverity,
  }
}

export type { Severity }
