import type { LucideIcon } from "lucide-react"
import {
  Activity,
  AlertTriangle,
  BookOpen,
  ClipboardList,
  FileText,
  LayoutDashboard,
  ScrollText,
  Server,
  ShieldAlert,
  SquareCheck,
  Ticket,
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
  soc_analyst: [
    { label: "Overview", path: "/soc", icon: LayoutDashboard, end: true },
    { label: "Alerts", path: "/soc/alerts", icon: AlertTriangle, module: "soc" },
    { label: "Incidents", path: "/soc/incidents", icon: ShieldAlert, module: "incidents" },
    { label: "Events", path: "/soc/events", icon: Activity, module: "soc" },
    { label: "Assets", path: "/soc/assets", icon: Server, module: "assets" },
    { label: "Reports", path: "/soc/reports", icon: FileText, module: "reports" },
  ],
  it_developer: [
    { label: "My Tasks", path: "/it", icon: ClipboardList, end: true },
    { label: "Tickets", path: "/it/tickets", icon: Ticket, module: "it_tickets" },
    { label: "Assets", path: "/it/assets", icon: Server, module: "assets" },
    { label: "Runbooks", path: "/it/runbooks", icon: BookOpen, module: "it_tickets" },
  ],
  security_manager: [
    { label: "Overview", path: "/manager", icon: LayoutDashboard, end: true },
    { label: "Incidents", path: "/manager/incidents", icon: ShieldAlert, module: "incidents" },
    { label: "Approvals", path: "/manager/approvals", icon: SquareCheck, module: "approvals" },
    { label: "Reports", path: "/manager/reports", icon: FileText, module: "reports" },
    { label: "Assets", path: "/manager/assets", icon: Server, module: "assets" },
    { label: "Audit", path: "/manager/audit", icon: ScrollText, module: "audit_logs" },
  ],
  auditor: [
    { label: "Overview", path: "/auditor", icon: LayoutDashboard, end: true },
    { label: "Audit Logs", path: "/auditor/audit-logs", icon: ScrollText, module: "audit_logs" },
    { label: "Incidents", path: "/auditor/incidents", icon: ShieldAlert, module: "incidents" },
    { label: "Reports", path: "/auditor/reports", icon: FileText, module: "reports" },
  ],
}
