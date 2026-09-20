export type AssetCriticality = "critical" | "high" | "medium" | "low"

export type Asset = {
  id: string
  organizationId: string
  teamId: string | null
  hostname: string
  ipAddress: string | null
  assetType: string
  criticality: AssetCriticality
  environment: "production" | "staging" | "development"
  owner: string | null
  ownerUserId: string | null
  lastSeenAt: string
  status: "active" | "inactive"
  // UI-only: the real Asset model has a generic `status` string, not a
  // dedicated agent-connectivity field yet -- see the earlier note in
  // this codebase's asset type. Kept here so SOC Assets / device-health
  // panels have something to render.
  agentStatus: "connected" | "offline"
}
