import type { IncidentRow, IncidentStatus } from "../../../lib/api"
import type { Severity } from "../../../types/common"

/** Constants, labels and small helpers for the shared SOC incident
 * components (the alerts' alertShared.ts pattern). Kept component-free so
 * pages can import them without pulling in JSX (fast-refresh friendly). */

export const INCIDENT_SEVERITIES = ["critical", "high", "medium", "low", "info"] as const

/** The transition table's rows, as the API returns them (UPPERCASE). */
export const INCIDENT_STATUSES = [
  "NEW",
  "TRIAGED",
  "INVESTIGATING",
  "CONTAINMENT",
  "REMEDIATION",
  "VERIFICATION",
  "RESOLVED",
  "CLOSED",
  "REOPENED",
  "ESCALATED",
  "FALSE_POSITIVE",
  "DUPLICATE",
] as const

export const INCIDENT_STATUS_LABELS: Record<IncidentStatus, string> = {
  NEW: "New",
  TRIAGED: "Triaged",
  INVESTIGATING: "Investigating",
  CONTAINMENT: "Containment",
  REMEDIATION: "Remediation",
  VERIFICATION: "Pending verification",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
  REOPENED: "Reopened",
  ESCALATED: "Escalated",
  FALSE_POSITIVE: "False positive",
  DUPLICATE: "Duplicate",
}

/** Human words for a transition target (dialog titles/buttons). */
export const TRANSITION_LABELS: Record<string, string> = {
  NEW: "New",
  TRIAGED: "Triaged",
  INVESTIGATING: "Investigating",
  CONTAINMENT: "Containment",
  REMEDIATION: "Remediation",
  VERIFICATION: "Pending verification",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
  REOPENED: "Reopened",
  ESCALATED: "Escalated",
  FALSE_POSITIVE: "False positive",
  DUPLICATE: "Duplicate",
}

/** Terminal or resolved states -- nothing left to do. */
export function isIncidentTerminal(status: IncidentStatus): boolean {
  return status === "FALSE_POSITIVE" || status === "DUPLICATE"
}

export function isIncidentResolvedOrClosed(status: IncidentStatus): boolean {
  return status === "RESOLVED" || status === "CLOSED"
}

/** Which transitions are destructive (typed confirmation per the brief). */
export function isDestructiveTransition(target: string): boolean {
  return target === "CLOSED" || target === "FALSE_POSITIVE" || target === "DUPLICATE"
}

/** Which transitions need a free-text reason (backend 422 otherwise). */
export function transitionRequiresReason(target: string): boolean {
  return target === "FALSE_POSITIVE" || target === "DUPLICATE"
}

/** Which transitions need the resolution summary (backend 422 otherwise). */
export function transitionRequiresSummary(target: string): boolean {
  return target === "CLOSED"
}

/** Timeline entry_type -> human label (backend entry types, one line each). */
export function timelineEntryLabel(entryType: string): string {
  const labels: Record<string, string> = {
    created: "Created",
    status_change: "Status changed",
    comment: "Note",
    assign: "Assigned",
    ticket_created: "Ticket created",
    ticket_status: "Ticket updated",
    link: "Links changed",
    merge: "Merged",
  }
  return labels[entryType] ?? entryType
}

/**
 * Client-side ticket priority preview -- the documented formula from
 * docs/API_CONTRACT.md, mirrored so the analyst sees the computed
 * priority while filling the form. The backend recomputes (and its
 * answer wins); this is a preview, never the authority. Change the
 * weights there and here in the same commit or they drift.
 */
export const TICKET_SEVERITY_POINTS: Record<Severity, number> = {
  critical: 40,
  high: 30,
  medium: 20,
  low: 10,
  info: 5,
}

export const TICKET_CRITICALITY_POINTS: Record<string, number> = {
  critical: 30,
  high: 22,
  medium: 12,
  low: 5,
}

export function ticketConfidencePoints(confidence: number | null): number {
  if (confidence === null || confidence === undefined) return 0
  if (confidence >= 0.9) return 10
  if (confidence >= 0.7) return 5
  return 0
}

export function computeTicketPriorityPreview(
  severity: Severity,
  assetCriticality: string | null,
  confidence: number | null,
): "P1" | "P2" | "P3" | "P4" {
  const score =
    (TICKET_SEVERITY_POINTS[severity] ?? 0) +
    (assetCriticality ? TICKET_CRITICALITY_POINTS[assetCriticality] ?? 0 : 0) +
    ticketConfidencePoints(confidence)
  if (score >= 80) return "P1"
  if (score >= 60) return "P2"
  if (score >= 35) return "P3"
  return "P4"
}

/** Does this incident already carry enough to preview a ticket priority? */
export function incidentPriorityPreview(incident: IncidentRow, assetCriticality: string | null): string {
  return computeTicketPriorityPreview(incident.severity, assetCriticality, incident.confidence)
}

export type { Severity }
