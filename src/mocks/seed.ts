import type {
  Alert,
  AlertStatus,
  Asset,
  AssetCriticality,
  AuditEntry,
  Incident,
  IncidentTimelineEntry,
  Organization,
  Severity,
  Team,
  Ticket,
  TicketStatus,
  AppUser,
} from "../types"
import type { Session } from "../lib/auth"

// ---------------------------------------------------------------------------
// Deterministic mock seed data. Nothing here uses Math.random(): every load
// produces the same dataset (only *relative* to "now", so SLA countdowns
// still look live), which is what makes acknowledge/assign/verify actions
// during a walkthrough easy to reason about and demo reliably.
// ---------------------------------------------------------------------------

const MIN = 60_000
const HOUR = 60 * MIN

function ago(now: number, ms: number) {
  return new Date(now - ms).toISOString()
}

function fromNow(now: number, ms: number) {
  return new Date(now + ms).toISOString()
}

export const ORGANIZATIONS: Organization[] = [
  { id: "org-1", name: "Meridian Health Systems" },
  { id: "org-2", name: "Northwind Retail Group" },
  { id: "org-3", name: "Blue Harbor Logistics" },
]

export const TEAMS: Team[] = [
  { id: "team-soc-1", organizationId: "org-1", name: "SOC Team" },
  { id: "team-it-1", organizationId: "org-1", name: "IT Team" },
  { id: "team-soc-2", organizationId: "org-2", name: "SOC Team" },
  { id: "team-it-3", organizationId: "org-3", name: "IT Team" },
]

const SOC_NAMES = ["Priya Nair", "Jordan Blake", "Sam Whitfield", "Alex Romero"]
const IT_NAMES = ["Devon Marsh", "Kira Long", "Theo Park"]
const MANAGER_NAME = "Morgan Ellis"

const HOSTNAMES = [
  "web-prod-01", "web-prod-02", "api-gateway-01", "db-primary-01", "db-replica-02",
  "vpn-edge-01", "fw-core-01", "fw-core-02", "auth-svc-01", "billing-svc-01",
  "workstation-fin-07", "workstation-hr-03", "laptop-eng-11", "laptop-eng-19",
  "backup-node-01", "k8s-node-01", "k8s-node-02", "k8s-node-03", "mail-relay-01",
  "dns-internal-01", "monitoring-01", "ci-runner-02", "storage-nas-01",
  "pos-terminal-14", "pos-terminal-22", "warehouse-scanner-04", "iot-hub-01",
  "crm-app-01", "erp-app-01", "print-server-01",
]

const RULES = [
  "Brute Force Login Attempt", "Impossible Travel", "Malware Signature Match",
  "Privilege Escalation Attempt", "Suspicious Outbound Connection",
  "Data Exfiltration Volume Threshold", "Unusual Process Execution",
  "Firewall Rule Change", "Ransomware Behavior Pattern", "Port Scan Detected",
]

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"]
const ALERT_STATUSES: AlertStatus[] = ["new", "triaged", "investigating", "dismissed", "converted"]
const TICKET_STATUSES: TicketStatus[] = [
  "OPEN", "TRIAGED", "ASSIGNED", "ACKNOWLEDGED", "INVESTIGATING",
  "REMEDIATION", "VERIFICATION", "RESOLVED", "CLOSED",
]
const CRITICALITIES: AssetCriticality[] = ["critical", "high", "medium", "low"]

function pick<T>(arr: T[], i: number): T {
  return arr[i % arr.length]
}

export type SeedData = {
  organizations: Organization[]
  teams: Team[]
  users: AppUser[]
  assets: Asset[]
  alerts: Alert[]
  incidents: Incident[]
  incidentTimeline: IncidentTimelineEntry[]
  tickets: Ticket[]
  audit: AuditEntry[]
}

/** The "you" record -- the logged-in session, represented as a first-class
 * mock user so seed alerts/tickets can be pre-assigned to whoever is
 * actually logged in, and "my work" filters have something real to show. */
function meUser(session: Session): AppUser {
  const teamId =
    session.role === "it_developer" ? "team-it-1" : session.role === "soc_analyst" ? "team-soc-1" : null

  return {
    id: "me",
    organizationId: "org-1",
    teamId,
    name: session.name ?? "You",
    role: (session.role as AppUser["role"]) ?? "soc_analyst",
  }
}

export function buildSeedData(session: Session): SeedData {
  const now = Date.now()

  const users: AppUser[] = [
    meUser(session),
    ...SOC_NAMES.map((name, i) => ({
      id: `soc-${i + 1}`,
      organizationId: i === 3 ? "org-2" : "org-1",
      teamId: i === 3 ? "team-soc-2" : "team-soc-1",
      name,
      role: "soc_analyst" as const,
    })),
    ...IT_NAMES.map((name, i) => ({
      id: `it-${i + 1}`,
      organizationId: i === 2 ? "org-3" : "org-1",
      teamId: i === 2 ? "team-it-3" : "team-it-1",
      name,
      role: "it_developer" as const,
    })),
    {
      id: "mgr-1",
      organizationId: "org-1",
      teamId: null,
      name: MANAGER_NAME,
      role: "security_manager" as const,
    },
  ]

  const assets: Asset[] = HOSTNAMES.map((hostname, i) => {
    const orgId = i % 10 === 9 ? "org-3" : i % 7 === 6 ? "org-2" : "org-1"
    const offline = i % 5 === 4
    return {
      id: `asset-${i + 1}`,
      organizationId: orgId,
      teamId: orgId === "org-1" ? (i % 2 === 0 ? "team-soc-1" : "team-it-1") : null,
      hostname,
      ipAddress: `10.${(i % 4) + 1}.${(i * 7) % 255}.${(i * 13) % 255}`,
      assetType: hostname.startsWith("fw") ? "firewall" : hostname.startsWith("workstation") || hostname.startsWith("laptop") ? "workstation" : hostname.startsWith("pos") ? "application" : "server",
      criticality: pick(CRITICALITIES, i),
      environment: i % 6 === 0 ? "development" : i % 4 === 0 ? "staging" : "production",
      owner: pick([...SOC_NAMES, ...IT_NAMES], i),
      ownerUserId: i % 2 === 0 ? pick(SOC_NAMES.map((_, j) => `soc-${j + 1}`), i) : pick(IT_NAMES.map((_, j) => `it-${j + 1}`), i),
      lastSeenAt: offline ? ago(now, (i + 3) * HOUR) : ago(now, (i % 6) * MIN + 1),
      status: "active",
      agentStatus: offline ? "offline" : "connected",
    }
  })

  const org1Assets = assets.filter((a) => a.organizationId === "org-1")

  const alerts: Alert[] = Array.from({ length: 40 }, (_, i) => {
    const orgId = i % 8 === 7 ? "org-2" : i % 11 === 10 ? "org-3" : "org-1"
    const orgAssets = assets.filter((a) => a.organizationId === orgId)
    const asset = pick(orgAssets, i)
    const severity = pick(SEVERITIES, i)
    const status = pick(ALERT_STATUSES, i + 1)
    const assignToMe = orgId === "org-1" && i % 6 === 0 && status !== "dismissed"
    return {
      id: `alert-${i + 1}`,
      organizationId: orgId,
      assetId: asset.id,
      detectionRuleId: `rule-${(i % RULES.length) + 1}`,
      detectionRuleName: pick(RULES, i),
      severity,
      confidence: 55 + ((i * 7) % 45),
      status,
      title: `${pick(RULES, i)} on ${asset.hostname}`,
      summary: `${pick(RULES, i)} detected on ${asset.hostname} (${asset.ipAddress}). ${asset.criticality} criticality asset.`,
      firstSeenAt: ago(now, (i + 1) * 11 * MIN),
      lastSeenAt: ago(now, i * 3 * MIN),
      eventCount: 1 + (i % 12) * 4,
      assigneeUserId: assignToMe ? "me" : status === "new" ? null : pick(["soc-1", "soc-2", "soc-3", null], i),
      dismissReason: status === "dismissed" ? "Confirmed benign -- scheduled maintenance window" : null,
      incidentId: status === "converted" ? `incident-${(i % 12) + 1}` : null,
    }
  })

  const incidents: Incident[] = Array.from({ length: 12 }, (_, i) => {
    const orgId = i % 5 === 4 ? "org-2" : "org-1"
    const related = alerts.filter((a) => a.organizationId === orgId).slice(i, i + 2)
    const asset = assets.find((a) => a.id === related[0]?.assetId) ?? org1Assets[0]
    const statuses: Incident["status"][] = [
      "new", "triaged", "investigating", "containment", "remediation", "verification", "resolved", "closed",
    ]
    return {
      id: `incident-${i + 1}`,
      organizationId: orgId,
      title: `${pick(RULES, i)} -- ${asset.hostname}`,
      summary: `Escalated from alert triage. Affects ${asset.hostname} and related infrastructure.`,
      severity: pick(SEVERITIES, i),
      status: pick(statuses, i),
      primaryAssetId: asset.id,
      openedAt: ago(now, (i + 1) * 4 * HOUR),
      resolvedAt: i % 4 === 0 ? ago(now, i * HOUR) : null,
      assigneeUserId: i % 3 === 0 ? "me" : pick(["soc-1", "soc-2", "soc-3"], i),
      alertIds: related.map((a) => a.id),
    }
  })

  const incidentTimeline: IncidentTimelineEntry[] = incidents.flatMap((incident, i) => [
    {
      id: `${incident.id}-t1`,
      incidentId: incident.id,
      occurredAt: incident.openedAt,
      entryType: "created",
      description: "Incident opened from alert escalation.",
      actorType: "user" as const,
      actorName: pick(SOC_NAMES, i),
    },
    {
      id: `${incident.id}-t2`,
      incidentId: incident.id,
      occurredAt: ago(now, i * HOUR),
      entryType: "ai_analysis",
      description: "AI analysis attached -- see AI analysis panel.",
      actorType: "ai_agent" as const,
      actorName: "SentinelX AI",
    },
  ])

  const RECOMMENDED_STEPS = [
    "Isolate the affected host from the network",
    "Rotate credentials for the affected account",
    "Apply the latest security patch",
    "Review firewall rules for the affected segment",
    "Confirm backup integrity before remediation",
  ]

  const tickets: Ticket[] = Array.from({ length: 25 }, (_, i) => {
    const orgId = i % 6 === 5 ? "org-2" : "org-1"
    const orgAssets = assets.filter((a) => a.organizationId === orgId)
    const asset = pick(orgAssets, i)
    const status = pick(TICKET_STATUSES, i)
    const overdue = i % 7 === 0
    const atRisk = i % 5 === 0 && !overdue
    const assignToMe = orgId === "org-1" && i % 3 === 0 && status !== "CLOSED"
    const stepCount = 3 + (i % 3)
    const doneCount =
      status === "CLOSED" || status === "RESOLVED" || status === "VERIFICATION"
        ? stepCount
        : status === "REMEDIATION"
          ? Math.max(1, stepCount - 1)
          : status === "INVESTIGATING" || status === "ACKNOWLEDGED"
            ? 1
            : 0

    return {
      id: `ticket-${i + 1}`,
      ticketNumber: `TICK-${100 + i}`,
      organizationId: orgId,
      incidentId: i < incidents.length ? incidents[i % incidents.length].id : null,
      title: `Remediate ${pick(RULES, i)} on ${asset.hostname}`,
      description: `The SOC identified ${pick(RULES, i).toLowerCase()} affecting ${asset.hostname}. Please investigate and remediate per the recommended steps.`,
      severity: pick(SEVERITIES, i),
      status,
      assignedTeamId: orgId === "org-1" ? "team-it-1" : "team-it-3",
      assignedUserId: assignToMe ? "me" : pick(["it-1", "it-2", "it-3"], i),
      assetId: asset.id,
      environment: asset.environment,
      ackDueAt: overdue ? ago(now, 25 * MIN) : atRisk ? fromNow(now, 40 * MIN) : fromNow(now, (i + 2) * HOUR),
      resolveDueAt: overdue ? ago(now, 3 * HOUR) : atRisk ? fromNow(now, 90 * MIN) : fromNow(now, (i + 6) * HOUR),
      acknowledgedAt: status === "OPEN" || status === "TRIAGED" ? null : ago(now, (i + 1) * HOUR),
      createdAt: ago(now, (i + 2) * HOUR),
      checklist: Array.from({ length: stepCount }, (_, s) => ({
        id: `${`ticket-${i + 1}`}-check-${s}`,
        label: pick(RECOMMENDED_STEPS, s),
        done: s < doneCount,
      })),
      evidence:
        status === "VERIFICATION" || status === "RESOLVED" || status === "CLOSED"
          ? [{ id: `${`ticket-${i + 1}`}-ev-1`, fileName: "remediation-proof.png", sizeBytes: 184_320, addedAt: ago(now, i * MIN) }]
          : [],
      recommendedSteps: RECOMMENDED_STEPS.slice(0, stepCount),
      runbookId: `runbook-${(i % 4) + 1}`,
      reopenReason: i % 11 === 0 ? "Verification failed -- exploit path still reachable from the VPN segment." : null,
      comments: [
        {
          id: `${`ticket-${i + 1}`}-c1`,
          authorName: pick(SOC_NAMES, i),
          authorType: "user" as const,
          body: "Please prioritise -- this asset is customer-facing.",
          createdAt: ago(now, (i + 1) * 30 * MIN),
        },
      ],
    }
  })

  const audit: AuditEntry[] = Array.from({ length: 20 }, (_, i) => ({
    id: `audit-${i + 1}`,
    organizationId: i % 4 === 0 ? "org-2" : "org-1",
    actorType: i % 5 === 0 ? "ai_agent" : "user",
    actorName: i % 5 === 0 ? "SentinelX AI" : pick([...SOC_NAMES, ...IT_NAMES], i),
    action: pick(["alert.acknowledge", "alert.dismiss", "ticket.create", "ticket.verify", "incident.escalate"], i),
    targetType: pick(["alert", "ticket", "incident"], i),
    targetId: `seed-${i + 1}`,
    createdAt: ago(now, (i + 1) * 45 * MIN),
  }))

  return {
    organizations: ORGANIZATIONS,
    teams: TEAMS,
    users,
    assets,
    alerts,
    incidents,
    incidentTimeline,
    tickets,
    audit,
  }
}
