import {
  Activity,
  Building2,
  ClipboardList,
  LayoutDashboard,
  Server,
  ShieldAlert,
  ShieldCheck,
  Users,
  Wrench,
} from "lucide-react"

import { NavLink } from "react-router-dom"

function Sidebar() {
  const role = localStorage.getItem(
    "sentinelx_role",
  )

  /*
    SUPER ADMIN
    Can see everything
  */

  const superAdminItems = [
    {
      name: "Admin Dashboard",
      icon: LayoutDashboard,
      path: "/admin",
    },
    {
      name: "Organization Dashboard",
      icon: Building2,
      path: "/organization-dashboard",
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
      name: "Users & Access",
      icon: Users,
      path: "/admin",
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

  const organizationAdminItems = [
    {
      name: "Organization Dashboard",
      icon: Building2,
      path: "/organization-dashboard",
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
  ]

  /*
    SOC ANALYST
    Only SOC-related information
  */

  const socItems = [
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

  const itItems = [
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

  const items =
    role === "super_admin"
      ? superAdminItems
      : role === "organization_admin"
        ? organizationAdminItems
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

              {item.name}

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