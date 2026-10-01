import type { TicketRow } from "../../lib/api"

/** Constants and small helpers for the IT workspace's real-data pages
 * (the soc incidentShared.ts pattern: component-free so pages import it
 * without pulling in JSX). */

export const TICKET_STATUS_LABELS: Record<string, string> = {
  OPEN: "Open",
  TRIAGED: "Triaged",
  ASSIGNED: "Assigned",
  ACKNOWLEDGED: "Acknowledged",
  INVESTIGATING: "Investigating",
  REMEDIATION: "Remediation",
  VERIFICATION: "Pending verification",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
}

export const TICKET_STATUSES = [
  "OPEN",
  "TRIAGED",
  "ASSIGNED",
  "ACKNOWLEDGED",
  "INVESTIGATING",
  "REMEDIATION",
  "VERIFICATION",
  "RESOLVED",
  "CLOSED",
] as const

export const TICKET_PRIORITIES = ["P1", "P2", "P3", "P4"] as const

/** Tone for a status badge -- only the tones already used across the app. */
export function ticketStatusTone(status: string): "brand" | "neutral" | "danger" | "success" {
  switch (status) {
    case "OPEN":
    case "REOPENED":
      return "brand"
    case "RESOLVED":
      return "success"
    case "VERIFICATION":
      return "brand"
    default:
      return "neutral"
  }
}

export function slaStateLabel(state: string): string {
  switch (state) {
    case "on_track":
      return "SLA on track"
    case "at_risk":
      return "SLA at risk"
    case "breached":
      return "SLA breached"
    default:
      return "No SLA"
  }
}

export function slaBadgeTone(state: string): "brand" | "neutral" | "danger" | "success" {
  switch (state) {
    case "on_track":
      return "success"
    case "at_risk":
      return "brand"
    case "breached":
      return "danger"
    default:
      return "neutral"
  }
}

/** Working states where the checklist/evidence story matters (the
 * "Submit for verification" gate reads these). */
export function isWorkingStatus(status: string): boolean {
  return status === "INVESTIGATING" || status === "REMEDIATION"
}

export function isDoneStatus(status: string): boolean {
  return status === "RESOLVED" || status === "CLOSED"
}

/** The IT board columns of the dashboard, by API status. */
export const BOARD_COLUMNS: { key: string; label: string; statuses: string[] }[] = [
  { key: "assigned", label: "Assigned", statuses: ["OPEN", "TRIAGED", "ASSIGNED"] },
  { key: "acknowledged", label: "Acknowledged", statuses: ["ACKNOWLEDGED"] },
  { key: "in-progress", label: "In progress", statuses: ["INVESTIGATING", "REMEDIATION"] },
  { key: "verification", label: "Ready for verification", statuses: ["VERIFICATION"] },
  { key: "done", label: "Done", statuses: ["RESOLVED", "CLOSED"] },
]

/** Client-side scope bucket for the tickets list. The backend always
 * scopes rows to the caller's organization first; this only decides
 * which of the org's tickets the filter shows. */
export type TicketScope = "mine" | "team" | "all"

export function ticketInScope(ticket: TicketRow, scope: TicketScope, meId: string, teamId: string | null): boolean {
  if (scope === "mine") return ticket.assigned_user_id === meId
  if (scope === "team") return ticket.assigned_team_id !== null && (teamId === null || ticket.assigned_team_id === teamId)
  return true
}

/** Evidence type label from the API's evidence_type + metadata kind. */
export function evidenceTypeLabel(evidenceType: string): string {
  const labels: Record<string, string> = {
    log: "Log",
    file: "File",
    screenshot: "Screenshot",
    note: "Note",
    command_output: "Command output",
  }
  return labels[evidenceType] ?? evidenceType
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "--"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
