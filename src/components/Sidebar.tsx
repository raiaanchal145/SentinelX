import {
  Activity,
  Building2,
  ClipboardList,
  LayoutDashboard,
  Server,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Users,
  UsersRound,
  Wrench,
} from "lucide-react"

import type { LucideIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { NavLink } from "react-router-dom"

import { apiListOrganizations } from "../lib/api"
import Badge from "./ui/Badge"

type NavItem = {
  name: string
  icon: LucideIcon
  path: string
  /** Rendered as a Badge next to the label -- omit for no badge. */
  badgeCount?: number | null
}

function Sidebar() {
  const role = localStorage.getItem(
    "sentinelx_role",
  )

  // Cheap "how many organizations need my attention" count for the nav
  // badge -- fetched once per Sidebar mount (every admin page renders
  // its own Sidebar, so this refreshes on every admin-side navigation,
  // including right after approving/rejecting one). super_admin-only:
  // the endpoint is 403 for anyone else.
  const [pendingOrgCount, setPendingOrgCount] = useState<number | null>(null)

  useEffect(() => {
    if (role !== "super_admin") return
    let cancelled = false
    apiListOrganizations({ status: "pending", page_size: 1 })
      .then((res) => {
        if (!cancelled) setPendingOrgCount(res.total)
      })
      .catch(() => {
        if (!cancelled) setPendingOrgCount(null)
      })
    return () => {
      cancelled = true
    }
  }, [role])

  /*
    SUPER ADMIN
    Can see everything
  */

  const superAdminItems: NavItem[] = [
    {
      name: "Organizations",
      icon: Building2,
      path: "/admin/organizations",
      // Rendered as a Badge next to the label below -- how many
      // organizations are waiting on platform approval right now.
      badgeCount: pendingOrgCount,
    },
    {
      name: "SOC Team",
      icon: Users,
      path: "/admin/soc-team",
    },
    {
      name: "Admin Dashboard",
      icon: LayoutDashboard,
      path: "/admin",
    },
    {
      // Was "/soc-dashboard", which only ever redirected into the
      // analyst-only /soc route and bounced an admin straight back home.
      // Now points at the real admin-side oversight page (P22).
      name: "SOC Oversight",
      icon: ShieldAlert,
      path: "/admin/soc-oversight",
    },
    {
      // Same fix as above, for the IT side.
      name: "IT Oversight",
      icon: Wrench,
      path: "/admin/it-oversight",
    },
    {
      name: "Assets",
      icon: Server,
      path: "/admin",
    },
    {
      name: "Security Overview",
      icon: ShieldCheck,
      path: "/admin",
    },
  ]

  /*
    ORGANIZATION ADMIN
    Was previously falling through to itItems below (there was no branch
    for this role at all) -- a pre-existing gap, not something introduced
    here. Gets its own dashboard plus the same two oversight pages, scoped
    to their one organization by scopeFor() rather than "all".
  */

  const organizationAdminItems: NavItem[] = [
    {
      name: "Dashboard",
      icon: Building2,
      path: "/organization",
    },
    {
      name: "Members",
      icon: Users,
      path: "/organization/members",
    },
    {
      name: "Teams",
      icon: UsersRound,
      path: "/organization/teams",
    },
    {
      name: "Assets",
      icon: Server,
      path: "/organization/assets",
    },
    {
      name: "Access",
      icon: ShieldCheck,
      path: "/organization/access",
    },
    {
      name: "SOC Oversight",
      icon: ShieldAlert,
      path: "/admin/soc-oversight",
    },
    {
      name: "IT Oversight",
      icon: Wrench,
      path: "/admin/it-oversight",
    },
    {
      name: "Settings",
      icon: Settings,
      path: "/organization/settings",
    },
  ]

  /*
    SOC ANALYST
    Only SOC-related information
  */

  const socItems: NavItem[] = [
    {
      name: "SOC Dashboard",
      icon: LayoutDashboard,
      path: "/soc-dashboard",
    },
    {
      name: "Security Events",
      icon: Activity,
      path: "/soc-dashboard",
    },
    {
      name: "Incidents",
      icon: ShieldAlert,
      path: "/soc-dashboard",
    },
    {
      name: "Investigation",
      icon: ClipboardList,
      path: "/soc-dashboard",
    },
  ]

  /*
    IT / DEVELOPER
    Only IT-related information
  */

  const itItems: NavItem[] = [
    {
      name: "IT Dashboard",
      icon: LayoutDashboard,
      path: "/it-dashboard",
    },
    {
      name: "Assigned Tasks",
      icon: ClipboardList,
      path: "/it-dashboard",
    },
    {
      name: "Remediation",
      icon: Wrench,
      path: "/it-dashboard",
    },
  ]

  /*
    PLATFORM SOC ANALYST
    Restricted admin-side navigation -- see Prompt B section A5. The
    real triage queue arrives with the alerts work; for now this is a
    placeholder plus the analyst's own assigned organizations.
  */

  const platformSocAnalystItems: NavItem[] = [
    {
      name: "SOC Queue",
      icon: ShieldAlert,
      path: "/admin/soc-queue",
    },
  ]

  const items =
    role === "super_admin"
      ? superAdminItems
      : role === "organization_admin"
        ? organizationAdminItems
        : role === "platform_soc_analyst"
          ? platformSocAnalystItems
          : role === "soc_analyst"
            ? socItems
            : itItems

  return (
    <aside className="flex min-h-screen w-72 flex-col border-r border-white/10 bg-surface-sunken">

      {/* LOGO */}

      <div className="border-b border-white/10 p-6">

        <div className="flex items-center gap-3">

          <div className="rounded-xl bg-brand-500/10 p-2.5">

            <ShieldCheck
              size={27}
              className="text-brand-400"
            />

          </div>

          <div>

            <h1 className="text-xl font-bold text-white">

              Sentinel
              <span className="text-brand-400">
                X
              </span>

            </h1>

            <p className="text-xs text-fg-muted">
              AI Security Operations
            </p>

          </div>

        </div>

      </div>

      {/* NAVIGATION */}

      <nav className="space-y-2 p-4">

        {items.map((item) => {
          const Icon = item.icon
          const badgeCount = item.badgeCount

          return (
            <NavLink
              key={item.name}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-4 py-3 text-sm transition ${
                  isActive
                    ? "bg-brand-500/10 text-brand-400"
                    : "text-fg-subtle hover:bg-white/5 hover:text-white"
                }`
              }
            >

              <Icon size={19} />

              <span className="flex-1">{item.name}</span>

              {!!badgeCount && <Badge tone="brand">{badgeCount}</Badge>}

            </NavLink>
          )
        })}

      </nav>

      {/* BOTTOM */}

      <div className="mt-auto p-5">

        <div className="rounded-xl border border-brand-500/10 bg-brand-500/5 p-4">

          <p className="text-xs font-medium text-brand-300">
            SentinelX Platform
          </p>

          <p className="mt-1 text-xs leading-5 text-fg-muted">
            AI-powered security monitoring and incident response.
          </p>

        </div>

      </div>

    </aside>
  )
}

export default Sidebar