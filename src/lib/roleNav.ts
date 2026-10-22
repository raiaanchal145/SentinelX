import type { LucideIcon } from "lucide-react"
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Building2,
  ClipboardList,
  FileText,
  Laptop,
  LayoutDashboard,
  Radio,
  ScrollText,
  Server,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SquareCheck,
  Ticket,
  Users,
  UsersRound,
  Wrench,
} from "lucide-react"

import type { Role } from "./auth"
import type { ModuleKey } from "./modules"

export type NavItem = {
  label: string
  path: string
  icon: LucideIcon
  /** Exact-match only (like NavLink's `end`) -- true for every role's Overview/home item. */
  end?: boolean
  /** The module this page needs. Omitted for a role's own Overview/home
   * item, which is always shown. See UserLayout.tsx, which filters
   * against the signed-in account's effective_modules (from useMe()). */
  module?: ModuleKey
}

/**
 * The exact per-role navigation maps from the design spec. Centralised
 * here so UserLayout's top nav, the mobile drawer, and (in a later phase)
 * the command palette all read from one source instead of drifting apart.
 */
export const ROLE_NAV: Partial<Record<Role, NavItem[]>> = {
  super_admin: [
    { label: "Admin Dashboard", path: "/admin", icon: LayoutDashboard, end: true },
    { label: "Organizations", path: "/admin/organizations", icon: Building2 },
    { label: "SOC Team", path: "/admin/soc-team", icon: Users },
    { label: "SOC Oversight", path: "/admin/soc-oversight", icon: ShieldAlert },
    { label: "IT Oversight", path: "/admin/it-oversight", icon: Wrench },
    { label: "Assets", path: "/admin/assets", icon: Server },
    { label: "Security Overview", path: "/admin/security-overview", icon: ShieldCheck },
  ],
  platform_soc_analyst: [
    { label: "SOC Queue", path: "/admin/soc-queue", icon: ShieldAlert, end: true },
  ],
  organization_admin: [
    { label: "Dashboard", path: "/organization", icon: Building2, end: true },
    { label: "Members", path: "/organization/members", icon: Users },
    { label: "Teams", path: "/organization/teams", icon: UsersRound },
    { label: "Assets", path: "/organization/assets", icon: Server },
    { label: "Devices", path: "/organization/devices", icon: Laptop },
    { label: "Event Sources", path: "/organization/event-sources", icon: Radio },
    { label: "Access", path: "/organization/access", icon: ShieldCheck },
    { label: "SOC Oversight", path: "/admin/soc-oversight", icon: ShieldAlert },
    { label: "Security Activity", path: "/organization/security-activity", icon: Activity },
    { label: "Incidents", path: "/organization/incidents", icon: ShieldAlert },
    { label: "Settings", path: "/organization/settings", icon: Settings },
  ],
  soc_analyst: [
    { label: "Overview", path: "/soc", icon: LayoutDashboard, end: true },
    { label: "Alerts", path: "/soc/alerts", icon: AlertTriangle, module: "soc" },
    { label: "Incidents", path: "/soc/incidents", icon: ShieldAlert, module: "incidents" },
    { label: "Events", path: "/soc/events", icon: Activity, module: "soc" },
    { label: "Assets", path: "/soc/assets", icon: Server, module: "assets" },
    { label: "Devices", path: "/devices", icon: Laptop, module: "device_agents" },
    { label: "Reports", path: "/soc/reports", icon: FileText, module: "reports" },
  ],
  it_developer: [
    { label: "My Tasks", path: "/it", icon: ClipboardList, end: true },
    { label: "Tickets", path: "/it/tickets", icon: Ticket, module: "it_tickets" },
    { label: "Assets", path: "/it/assets", icon: Server, module: "assets" },
    { label: "Devices", path: "/devices", icon: Laptop, module: "device_agents" },
    { label: "Runbooks", path: "/it/runbooks", icon: BookOpen, module: "it_tickets" },
  ],
  security_manager: [
    { label: "Overview", path: "/manager", icon: LayoutDashboard, end: true },
    { label: "Security activity", path: "/manager/security-activity", icon: Activity, module: "soc" },
    { label: "Incidents", path: "/manager/incidents", icon: ShieldAlert, module: "incidents" },
    { label: "Approvals", path: "/manager/approvals", icon: SquareCheck, module: "approvals" },
    { label: "Reports", path: "/manager/reports", icon: FileText, module: "reports" },
    { label: "Assets", path: "/manager/assets", icon: Server, module: "assets" },
    { label: "Devices", path: "/devices", icon: Laptop, module: "device_agents" },
    { label: "Event sources", path: "/manager/event-sources", icon: Radio },
    { label: "Audit", path: "/manager/audit", icon: ScrollText, module: "audit_logs" },
  ],
  auditor: [
    { label: "Overview", path: "/auditor", icon: LayoutDashboard, end: true },
    { label: "Audit Logs", path: "/auditor/audit-logs", icon: ScrollText, module: "audit_logs" },
    { label: "Incidents", path: "/auditor/incidents", icon: ShieldAlert, module: "incidents" },
    { label: "Assets", path: "/auditor/assets", icon: Server, module: "assets" },
    { label: "Devices", path: "/devices", icon: Laptop, module: "device_agents" },
    { label: "Reports", path: "/auditor/reports", icon: FileText, module: "reports" },
  ],
}
