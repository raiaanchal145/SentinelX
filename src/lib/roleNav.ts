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

export type NavItem = {
  label: string
  path: string
  icon: LucideIcon
  /** Exact-match only (like NavLink's `end`) -- true for every role's Overview/home item. */
  end?: boolean
}

/**
 * The exact per-role navigation maps from the design spec. Centralised
 * here so UserLayout's top nav, the mobile drawer, and (in a later phase)
 * the command palette all read from one source instead of drifting apart.
 */
export const ROLE_NAV: Partial<Record<Role, NavItem[]>> = {
  soc_analyst: [
    { label: "Overview", path: "/soc", icon: LayoutDashboard, end: true },
    { label: "Alerts", path: "/soc/alerts", icon: AlertTriangle },
    { label: "Incidents", path: "/soc/incidents", icon: ShieldAlert },
    { label: "Events", path: "/soc/events", icon: Activity },
    { label: "Assets", path: "/soc/assets", icon: Server },
    { label: "Reports", path: "/soc/reports", icon: FileText },
  ],
  it_developer: [
    { label: "My Tasks", path: "/it", icon: ClipboardList, end: true },
    { label: "Tickets", path: "/it/tickets", icon: Ticket },
    { label: "Assets", path: "/it/assets", icon: Server },
    { label: "Runbooks", path: "/it/runbooks", icon: BookOpen },
  ],
  security_manager: [
    { label: "Overview", path: "/manager", icon: LayoutDashboard, end: true },
    { label: "Incidents", path: "/manager/incidents", icon: ShieldAlert },
    { label: "Approvals", path: "/manager/approvals", icon: SquareCheck },
    { label: "Reports", path: "/manager/reports", icon: FileText },
    { label: "Assets", path: "/manager/assets", icon: Server },
    { label: "Audit", path: "/manager/audit", icon: ScrollText },
  ],
  auditor: [
    { label: "Overview", path: "/auditor", icon: LayoutDashboard, end: true },
    { label: "Audit Logs", path: "/auditor/audit-logs", icon: ScrollText },
    { label: "Incidents", path: "/auditor/incidents", icon: ShieldAlert },
    { label: "Reports", path: "/auditor/reports", icon: FileText },
  ],
}
