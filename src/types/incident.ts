import type { ActorType, Severity } from "./common"

export type IncidentStatus =
  | "new"
  | "triaged"
  | "investigating"
  | "containment"
  | "remediation"
  | "verification"
  | "resolved"
  | "closed"
  | "escalated"

export type Incident = {
  id: string
  organizationId: string
  title: string
  summary: string
  severity: Severity
  status: IncidentStatus
  primaryAssetId: string | null
  openedAt: string
  resolvedAt: string | null
  assigneeUserId: string | null
  alertIds: string[]
}

export type IncidentTimelineEntry = {
  id: string
  incidentId: string
  occurredAt: string
  entryType: string
  description: string
  actorType: ActorType
  actorName: string
}
