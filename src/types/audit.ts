import type { ActorType } from "./common"

export type AuditEntry = {
  id: string
  organizationId: string
  actorType: ActorType
  actorName: string
  action: string
  targetType: string
  targetId: string
  createdAt: string
  details?: string
}
