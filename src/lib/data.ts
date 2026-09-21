import type { Alert, AppUser, Asset, Incident, Severity, Ticket } from "../types"
import { SEVERITY_ORDER } from "../types"
import type { StoreState } from "../mocks/store"
import type { Scope } from "./scope"

/**
 * The ONLY module pages should import mock data through. Every function
 * here takes the mock store's state plus a Scope and returns already
 * role/org-filtered data -- pages never touch `state.alerts` etc directly.
 *
 * TODO: this file is the seam for real API calls. When the backend exposes
 * alert/incident/ticket endpoints, these functions become async (return
 * Promise<T>) but keep the same names and (scope, ...) argument shape, so
 * callers barely change -- only MockStoreProvider/useMockStore go away.
 */

// Simulated network latency so loading Skeletons actually get exercised.
// One constant, easy to flip to 0 for a snappier local demo.
export const MOCK_LATENCY_MS = 350

export function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), MOCK_LATENCY_MS))
}

function inScope(organizationId: string, scope: Scope): boolean {
  return scope.organizationId === "all" || organizationId === scope.organizationId
}

function ageMs(iso: string): number {
  return Date.now() - new Date(iso).getTime()
}

export function getAssetById(state: StoreState, id: string | null): Asset | undefined {
  if (!id) return undefined
  return state.assets.find((a) => a.id === id)
}

export function getUserById(state: StoreState, id: string | null): AppUser | undefined {
  if (!id) return undefined
  return state.users.find((u) => u.id === id)
}

export function getOrgAlerts(state: StoreState, scope: Scope): Alert[] {
  return state.alerts.filter((a) => inScope(a.organizationId, scope))
}

export function getOrgIncidents(state: StoreState, scope: Scope): Incident[] {
  return state.incidents.filter((i) => inScope(i.organizationId, scope))
}

export function getOrgTickets(state: StoreState, scope: Scope): Ticket[] {
  return state.tickets.filter((t) => inScope(t.organizationId, scope))
}

// ---------------------------------------------------------------------------
// SOC dashboard (A) -- /soc
// ---------------------------------------------------------------------------

export type Kpi = {
  label: string
  value: string
  trend?: { direction: "up" | "down" | "flat"; label: string; good: boolean }
  link?: string
  tone?: Severity | "neutral"
}

export function getSocKpis(state: StoreState, scope: Scope): Kpi[] {
  const alerts = getOrgAlerts(state, scope)
  const incidents = getOrgIncidents(state, scope)

  const openCritical = incidents.filter(
    (i) => i.severity === "critical" && i.status !== "resolved" && i.status !== "closed",
  )
  const unacknowledged = alerts.filter((a) => a.status === "new")
  const mine = alerts.filter((a) => a.assigneeUserId === scope.userId && a.status !== "dismissed")
  const slaAtRisk = incidents.filter(
    (i) => ageMs(i.openedAt) > 3 * 60 * 60 * 1000 && i.status !== "resolved" && i.status !== "closed",
  )

  const ackTimesMinutes = alerts
    .filter((a) => a.status !== "new")
    .map((a) => Math.max(1, Math.round((new Date(a.lastSeenAt).getTime() - new Date(a.firstSeenAt).getTime()) / 60_000)))
  const mtta = ackTimesMinutes.length
    ? Math.round(ackTimesMinutes.reduce((sum, m) => sum + m, 0) / ackTimesMinutes.length)
    : 0

  return [
    {
      label: "Open critical incidents",
      value: String(openCritical.length),
      link: "/soc/incidents?severity=critical",
      tone: openCritical.length > 0 ? "critical" : "neutral",
    },
    {
      label: "Unacknowledged alerts",
      value: String(unacknowledged.length),
      link: "/soc/alerts?status=new",
      tone: unacknowledged.length > 5 ? "high" : "neutral",
    },
    {
      label: "My assigned alerts",
      value: String(mine.length),
      link: "/soc/alerts?assignee=me",
      tone: "neutral",
    },
    {
      label: "SLA at risk",
      value: String(slaAtRisk.length),
      link: "/soc/incidents?sla=at_risk",
      tone: slaAtRisk.length > 0 ? "medium" : "neutral",
    },
    {
      label: "Mean time to acknowledge",
      value: mtta > 0 ? `${mtta}m` : "--",
      trend: { direction: "down", label: "vs last period", good: true },
      tone: "neutral",
    },
  ]
}

export type TriageRow = {
  alert: Alert
  asset: Asset | undefined
  assignee: AppUser | undefined
}

export function getTriageQueue(state: StoreState, scope: Scope): TriageRow[] {
  const alerts = getOrgAlerts(state, scope).filter(
    (a) => a.status === "new" || a.status === "triaged" || a.status === "investigating",
  )

  return alerts
    .slice()
    .sort((a, b) => {
      const sev = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
      if (sev !== 0) return sev
      return new Date(a.firstSeenAt).getTime() - new Date(b.firstSeenAt).getTime()
    })
    .map((alert) => ({
      alert,
      asset: getAssetById(state, alert.assetId),
      assignee: getUserById(state, alert.assigneeUserId),
    }))
}

export type VolumePoint = { label: string; value: number }

export function getEventVolume(state: StoreState, scope: Scope, rangeHours: 24 | 168 | 720): VolumePoint[] {
  const alerts = getOrgAlerts(state, scope)
  const buckets = 12
  const bucketMs = (rangeHours * 60 * 60 * 1000) / buckets
  const now = Date.now()

  return Array.from({ length: buckets }, (_, i) => {
    const bucketStart = now - (buckets - i) * bucketMs
    const bucketEnd = bucketStart + bucketMs
    const count = alerts.filter((a) => {
      const t = new Date(a.firstSeenAt).getTime()
      return t >= bucketStart && t < bucketEnd
    }).length
    // eventCount approximates raw event volume behind each alert bucket.
    const events = alerts
      .filter((a) => {
        const t = new Date(a.firstSeenAt).getTime()
        return t >= bucketStart && t < bucketEnd
      })
      .reduce((sum, a) => sum + a.eventCount, 0)
    return { label: `${i}`, value: events || count }
  })
}

export type AiInsight = {
  id: string
  text: string
  confidence: number
  linkLabel: string
  link: string
}

export function getAiInsights(state: StoreState, scope: Scope): AiInsight[] {
  const alerts = getOrgAlerts(state, scope)
    .filter((a) => a.status !== "dismissed")
    .slice()
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 3)

  return alerts.map((alert) => {
    const asset = getAssetById(state, alert.assetId)
    return {
      id: alert.id,
      text: `${alert.detectionRuleName} on ${asset?.hostname ?? "an asset"}: ${alert.eventCount} related events with ${alert.confidence}% confidence.`,
      confidence: alert.confidence,
      linkLabel: alert.incidentId ? "Open incident" : "Open alert",
      link: alert.incidentId ? `/soc/incidents/${alert.incidentId}` : `/soc/alerts?id=${alert.id}`,
    }
  })
}

export function getDeviceHealth(state: StoreState, scope: Scope) {
  const assets = state.assets.filter((a) => inScope(a.organizationId, scope))
  const offline = assets.filter((a) => a.agentStatus === "offline")
  return {
    connected: assets.length - offline.length,
    offline: offline.length,
    offlineList: offline,
  }
}

export function getActiveIncidents(state: StoreState, scope: Scope, limit = 4): Incident[] {
  return getOrgIncidents(state, scope)
    .filter((i) => i.status !== "resolved" && i.status !== "closed")
    .sort((a, b) => new Date(a.openedAt).getTime() - new Date(b.openedAt).getTime())
    .slice(0, limit)
}

// ---------------------------------------------------------------------------
// IT dashboard (B) -- /it
// ---------------------------------------------------------------------------

export function getMyTickets(state: StoreState, scope: Scope): Ticket[] {
  return getOrgTickets(state, scope).filter(
    (t) => t.assignedUserId === scope.userId || (t.assignedTeamId && t.assignedTeamId === scope.teamId),
  )
}

export function getItKpis(state: StoreState, scope: Scope): Kpi[] {
  const mine = getMyTickets(state, scope)
  const now = Date.now()
  const endOfToday = new Date().setHours(23, 59, 59, 999)

  const dueToday = mine.filter((t) => t.resolveDueAt && new Date(t.resolveDueAt).getTime() <= endOfToday && t.status !== "CLOSED")
  const atRisk = mine.filter((t) => {
    if (!t.resolveDueAt || t.status === "CLOSED" || t.status === "RESOLVED") return false
    const msLeft = new Date(t.resolveDueAt).getTime() - now
    return msLeft > 0 && msLeft < 2 * 60 * 60 * 1000
  })
  const awaitingVerification = mine.filter((t) => t.status === "VERIFICATION")
  const completedThisWeek = mine.filter(
    (t) => (t.status === "RESOLVED" || t.status === "CLOSED") && ageMs(t.createdAt) < 7 * 24 * 60 * 60 * 1000,
  )

  return [
    { label: "Assigned to me", value: String(mine.filter((t) => t.status !== "CLOSED").length), tone: "neutral" },
    { label: "Due today", value: String(dueToday.length), tone: dueToday.length > 0 ? "medium" : "neutral" },
    { label: "SLA at risk", value: String(atRisk.length), tone: atRisk.length > 0 ? "high" : "neutral" },
    { label: "Awaiting SOC verification", value: String(awaitingVerification.length), tone: "neutral" },
    { label: "Completed this week", value: String(completedThisWeek.length), tone: "neutral" },
  ]
}

export const IT_WORKFLOW_ORDER: Ticket["status"][] = [
  "ASSIGNED",
  "ACKNOWLEDGED",
  "INVESTIGATING",
  "REMEDIATION",
  "VERIFICATION",
  "RESOLVED",
]

export function getMyWorkByStatus(state: StoreState, scope: Scope): Record<string, Ticket[]> {
  const mine = getMyTickets(state, scope).filter((t) => t.status !== "CLOSED")
  const groups: Record<string, Ticket[]> = {}

  for (const status of IT_WORKFLOW_ORDER) {
    groups[status] = mine
      .filter((t) => t.status === status || (status === "ASSIGNED" && (t.status === "OPEN" || t.status === "TRIAGED")))
      .sort((a, b) => {
        const aOverdue = a.resolveDueAt ? new Date(a.resolveDueAt).getTime() - Date.now() : Infinity
        const bOverdue = b.resolveDueAt ? new Date(b.resolveDueAt).getTime() - Date.now() : Infinity
        return aOverdue - bOverdue
      })
  }
  return groups
}

export function getDueSoon(state: StoreState, scope: Scope, limit = 5): Ticket[] {
  return getMyTickets(state, scope)
    .filter((t) => t.resolveDueAt && t.status !== "CLOSED" && t.status !== "RESOLVED")
    .sort((a, b) => new Date(a.resolveDueAt!).getTime() - new Date(b.resolveDueAt!).getTime())
    .slice(0, limit)
}

export function getMyAssets(state: StoreState, scope: Scope): Asset[] {
  const mine = getMyTickets(state, scope)
  const assetIds = new Set(mine.map((t) => t.assetId).filter(Boolean) as string[])
  return state.assets.filter((a) => assetIds.has(a.id) || a.ownerUserId === scope.userId)
}

// ---------------------------------------------------------------------------
// Admin oversight (C / D) -- built now, wired into pages in a later step
// ---------------------------------------------------------------------------

export function getSocOversight(state: StoreState, scope: Scope) {
  const alerts = getOrgAlerts(state, scope)
  const incidents = getOrgIncidents(state, scope)
  const dismissed = alerts.filter((a) => a.status === "dismissed")
  const unassigned = alerts.filter((a) => !a.assigneeUserId && a.status !== "dismissed")

  const analystIds = Array.from(new Set(alerts.map((a) => a.assigneeUserId).filter(Boolean) as string[]))
  const analystWorkload = analystIds.map((id) => {
    const user = getUserById(state, id)
    const owned = alerts.filter((a) => a.assigneeUserId === id)
    const ownedIncidents = incidents.filter((i) => i.assigneeUserId === id)
    return {
      user,
      openAlerts: owned.filter((a) => a.status !== "dismissed").length,
      openIncidents: ownedIncidents.filter((i) => i.status !== "resolved" && i.status !== "closed").length,
    }
  })

  const ruleCounts = new Map<string, { count: number; falsePositives: number }>()
  for (const alert of alerts) {
    const entry = ruleCounts.get(alert.detectionRuleName) ?? { count: 0, falsePositives: 0 }
    entry.count += 1
    if (alert.status === "dismissed") entry.falsePositives += 1
    ruleCounts.set(alert.detectionRuleName, entry)
  }
  const topRules = Array.from(ruleCounts.entries())
    .map(([name, v]) => ({ name, count: v.count, falsePositiveRate: Math.round((v.falsePositives / v.count) * 100) }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6)

  const offlineAssets = state.assets.filter((a) => inScope(a.organizationId, scope) && a.agentStatus === "offline")

  // Exposed as full rows (not just the KPI count above) so the admin
  // oversight page can offer a reassign action per alert.
  const unassignedAlerts = unassigned
    .slice()
    .sort((a, b) => {
      const sev = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
      if (sev !== 0) return sev
      return new Date(a.firstSeenAt).getTime() - new Date(b.firstSeenAt).getTime()
    })

  const attention = [
    ...alerts
      .filter((a) => a.severity === "critical" && a.status === "new")
      .map((a) => ({ kind: "alert" as const, id: a.id, title: a.title, link: `/soc/alerts?id=${a.id}` })),
    ...incidents
      .filter((i) => ageMs(i.openedAt) > 6 * 60 * 60 * 1000 && i.status !== "resolved" && i.status !== "closed")
      .map((i) => ({ kind: "incident" as const, id: i.id, title: i.title, link: `/soc/incidents/${i.id}` })),
  ]

  return {
    kpis: [
      { label: "Alerts (period)", value: String(alerts.length), tone: "neutral" as const },
      { label: "Unassigned / unacknowledged", value: String(unassigned.length), tone: unassigned.length > 5 ? "high" as const : "neutral" as const },
      { label: "Mean time to acknowledge", value: "18m", tone: "neutral" as const },
      { label: "Mean time to respond", value: "1h 42m", tone: "neutral" as const },
      { label: "False-positive rate", value: `${dismissed.length ? Math.round((dismissed.length / alerts.length) * 100) : 0}%`, tone: "neutral" as const },
      { label: "Devices online", value: `${state.assets.filter((a) => inScope(a.organizationId, scope)).length - offlineAssets.length} of ${state.assets.filter((a) => inScope(a.organizationId, scope)).length}`, tone: offlineAssets.length > 0 ? "medium" as const : "neutral" as const },
    ] satisfies Kpi[],
    volume: getEventVolume(state, scope, 24),
    analystWorkload,
    topRules,
    offlineAssets,
    unassignedAlerts,
    attention,
  }
}

export function getItOversight(state: StoreState, scope: Scope) {
  const tickets = getOrgTickets(state, scope)
  const open = tickets.filter((t) => t.status !== "CLOSED")
  const now = Date.now()
  const overdue = open.filter((t) => t.resolveDueAt && new Date(t.resolveDueAt).getTime() < now)
  const atRisk = open.filter((t) => {
    if (!t.resolveDueAt) return false
    const msLeft = new Date(t.resolveDueAt).getTime() - now
    return msLeft > 0 && msLeft < 2 * 60 * 60 * 1000
  })
  const awaitingVerification = tickets.filter((t) => t.status === "VERIFICATION")
  const reopened = tickets.filter((t) => t.reopenReason)

  const byStatus = IT_WORKFLOW_ORDER.map((status) => ({
    status,
    count: open.filter((t) => t.status === status || (status === "ASSIGNED" && (t.status === "OPEN" || t.status === "TRIAGED"))).length,
  }))

  const teamIds = Array.from(new Set(tickets.map((t) => t.assignedTeamId).filter(Boolean) as string[]))
  const byTeam = teamIds.map((teamId) => {
    const team = state.teams.find((t) => t.id === teamId)
    const teamTickets = open.filter((t) => t.assignedTeamId === teamId)
    return {
      team,
      open: teamTickets.length,
      overdue: teamTickets.filter((t) => t.resolveDueAt && new Date(t.resolveDueAt).getTime() < now).length,
    }
  })

  const itUserIds = Array.from(new Set(tickets.map((t) => t.assignedUserId).filter(Boolean) as string[]))
  const workload = itUserIds.map((id) => {
    const user = getUserById(state, id)
    const owned = open.filter((t) => t.assignedUserId === id)
    return {
      user,
      openTasks: owned.length,
      overdue: owned.filter((t) => t.resolveDueAt && new Date(t.resolveDueAt).getTime() < now).length,
    }
  })

  const assetIncidentCounts = new Map<string, number>()
  for (const t of tickets) {
    if (!t.assetId) continue
    assetIncidentCounts.set(t.assetId, (assetIncidentCounts.get(t.assetId) ?? 0) + 1)
  }
  const repeatAssets = Array.from(assetIncidentCounts.entries())
    .map(([assetId, count]) => ({ asset: getAssetById(state, assetId), count }))
    .filter((entry) => entry.count > 1)
    .sort((a, b) => b.count - a.count)
    .slice(0, 5)

  return {
    kpis: [
      { label: "Open tickets", value: String(open.length), tone: "neutral" as const },
      { label: "SLA breaches", value: String(overdue.length), tone: overdue.length > 0 ? "critical" as const : "neutral" as const },
      { label: "At risk (<25% time left)", value: String(atRisk.length), tone: atRisk.length > 0 ? "high" as const : "neutral" as const },
      { label: "Mean time to remediate", value: "3h 20m", tone: "neutral" as const },
      { label: "Awaiting verification", value: String(awaitingVerification.length), tone: "neutral" as const },
      { label: "Reopen rate", value: `${tickets.length ? Math.round((reopened.length / tickets.length) * 100) : 0}%`, tone: reopened.length > 0 ? "medium" as const : "neutral" as const },
    ] satisfies Kpi[],
    byStatus,
    byTeam,
    slaTable: [...overdue, ...atRisk],
    workload,
    awaitingVerification,
    repeatAssets,
  }
}
