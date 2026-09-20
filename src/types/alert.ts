import type { Severity } from "./common"

export type AlertStatus = "new" | "triaged" | "investigating" | "dismissed" | "converted"

export type Alert = {
  id: string
  organizationId: string
  assetId: string
  detectionRuleId: string
  detectionRuleName: string
  severity: Severity
  confidence: number
  status: AlertStatus
  title: string
  summary: string
  firstSeenAt: string
  lastSeenAt: string
  eventCount: number
  assigneeUserId: string | null
  dismissReason: string | null
  incidentId: string | null
}
