import type { ActorType, Severity } from "./common"

// Matches the backend's uppercase TicketStatus string values exactly
// (see backend/app/models.py's _by_value() enum helper).
export type TicketStatus =
  | "OPEN"
  | "TRIAGED"
  | "ASSIGNED"
  | "ACKNOWLEDGED"
  | "INVESTIGATING"
  | "REMEDIATION"
  | "VERIFICATION"
  | "RESOLVED"
  | "CLOSED"

export type ChecklistItem = { id: string; label: string; done: boolean }

export type Evidence = { id: string; fileName: string; sizeBytes: number; addedAt: string }

export type TicketComment = {
  id: string
  authorName: string
  authorType: ActorType
  body: string
  createdAt: string
}

/**
 * The backend models Ticket and Task as separate tables (a ticket has
 * many remediation tasks). For this mock, IT works one record end to
 * end with an inline checklist, so Ticket and Task are treated as the
 * same thing here -- `Task` is kept as an alias so code that talks about
 * "my tasks" reads naturally. Splitting them back out is a mechanical
 * change once real endpoints exist.
 */
export type Ticket = {
  id: string
  ticketNumber: string
  organizationId: string
  incidentId: string | null
  title: string
  description: string
  severity: Severity
  status: TicketStatus
  assignedTeamId: string | null
  assignedUserId: string | null
  assetId: string | null
  environment: string | null
  ackDueAt: string | null
  resolveDueAt: string | null
  acknowledgedAt: string | null
  createdAt: string
  checklist: ChecklistItem[]
  evidence: Evidence[]
  recommendedSteps: string[]
  runbookId: string | null
  reopenReason: string | null
  comments: TicketComment[]
}

export type Task = Ticket
