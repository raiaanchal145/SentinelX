/**
 * The module keys used throughout organization_modules /
 * organization_role_access / user_access_overrides / the owner's
 * access matrix. Mirrors backend/app/modules.py exactly -- see
 * docs/API_CONTRACT.md ("Module keys").
 */
export const MODULE_KEYS = [
  "assets",
  "soc",
  "incidents",
  "it_tickets",
  "approvals",
  "ai_agents",
  "device_agents",
  "reports",
  "audit_logs",
] as const

export type ModuleKey = (typeof MODULE_KEYS)[number]

export const MODULE_INFO: Record<ModuleKey, { label: string; description: string }> = {
  assets: {
    label: "Asset inventory",
    description: "Track and manage devices, servers, and other assets.",
  },
  soc: {
    label: "SOC / Security operations",
    description: "Alerts, event triage, and threat monitoring.",
  },
  incidents: {
    label: "Incident management",
    description: "Track and respond to security incidents.",
  },
  it_tickets: {
    label: "IT tickets",
    description: "Track and resolve IT support tickets.",
  },
  approvals: {
    label: "Approvals",
    description: "Review and approve pending requests.",
  },
  ai_agents: {
    label: "AI agents",
    description: "Configure and monitor AI-driven automation.",
  },
  device_agents: {
    label: "Device agents",
    description: "Manage endpoint agent deployment and health.",
  },
  reports: {
    label: "Reports",
    description: "Generate and view security and compliance reports.",
  },
  audit_logs: {
    label: "Audit logs",
    description: "View a record of account and system actions.",
  },
}
