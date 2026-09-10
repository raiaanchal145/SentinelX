import { useEffect, useState } from "react"

import {
  Activity,
  AlertTriangle,
  Building2,
  Server,
  ShieldCheck,
  Users,
} from "lucide-react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"
import StatCard from "../components/StatCard"
import SeverityBadge from "../components/SeverityBadge"

import { apiGetStatsOverview } from "../lib/api"

function OrganizationDashboard() {
  const [usersCount, setUsersCount] = useState<number | null>(null)
  const [assetsCount, setAssetsCount] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false

    apiGetStatsOverview()
      .then((stats) => {
        if (cancelled) return
        setUsersCount(stats.users)
        setAssetsCount(stats.assets)
      })
      .catch(() => {
        // Backend not reachable -- leave the cards showing their defaults rather than crash the page.
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="flex min-h-screen bg-canvas text-white">

      <Sidebar />

      <main className="min-w-0 flex-1">

        <Topbar />

        <div className="p-6 lg:p-8">

          <div className="mb-8">

            <p className="text-sm text-brand-400">
              Organization Management
            </p>

            <h1 className="mt-2 text-3xl font-semibold">
              Organization Dashboard
            </h1>

            <p className="mt-2 text-sm text-fg-muted">
              Monitor users, assets, security posture
              and organization activity.
            </p>

          </div>

          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">

            <StatCard
              title="Organization Users"
              value={
                usersCount === null
                  ? "..."
                  : String(usersCount)
              }
              description="Total registered users"
              icon={Users}
            />

            <StatCard
              title="Registered Assets"
              value={
                assetsCount === null
                  ? "..."
                  : String(assetsCount)
              }
              description="Organization infrastructure"
              icon={Server}
            />

            <StatCard
              title="Security Status"
              value="Secure"
              description="Current security posture"
              icon={ShieldCheck}
            />

            <StatCard
              title="Security Activity"
              value="0"
              description="Recent security activity"
              icon={Activity}
            />

          </div>

          <div className="mt-8 grid gap-6 xl:grid-cols-3">

            <section className="rounded-2xl border border-white/10 bg-surface p-6 xl:col-span-2">

              <div className="flex items-center justify-between">

                <div>

                  <h2 className="text-lg font-semibold">
                    Organization Overview
                  </h2>

                  <p className="mt-1 text-sm text-fg-muted">
                    Infrastructure and organization information.
                  </p>

                </div>

                <select className="rounded-xl border border-white/10 bg-surface-sunken px-4 py-2 text-sm">

                  <option>
                    Current Organization
                  </option>

                  <option>
                    All Organizations
                  </option>

                </select>

              </div>

              <div className="mt-6 grid gap-4 md:grid-cols-2">

                <OrganizationCard
                  title="Organization"
                  value="Not Connected"
                  icon={<Building2 size={21} />}
                />

                <OrganizationCard
                  title="Infrastructure"
                  value={
                    assetsCount === null
                      ? "Loading..."
                      : assetsCount === 0
                        ? "No Assets Registered"
                        : `${assetsCount} Asset${assetsCount === 1 ? "" : "s"} Registered`
                  }
                  icon={<Server size={21} />}
                />

                <OrganizationCard
                  title="Users"
                  value={
                    usersCount === null
                      ? "Loading..."
                      : `${usersCount} Active User${usersCount === 1 ? "" : "s"}`
                  }
                  icon={<Users size={21} />}
                />

                <OrganizationCard
                  title="Security Coverage"
                  value="Not Available"
                  icon={<ShieldCheck size={21} />}
                />

              </div>

            </section>

            <section className="rounded-2xl border border-white/10 bg-surface p-6">

              <h2 className="text-lg font-semibold">
                Security Summary
              </h2>

              <p className="mt-1 text-sm text-fg-muted">
                Organization-wide threat summary.
              </p>

              <div className="mt-6 space-y-4">

                <SecurityItem
                  severity="Critical"
                />

                <SecurityItem
                  severity="High"
                />

                <SecurityItem
                  severity="Medium"
                />

                <SecurityItem
                  severity="Low"
                />

              </div>

            </section>

          </div>

          <section className="mt-8 rounded-2xl border border-white/10 bg-surface p-6">

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">

              <div>

                <h2 className="text-lg font-semibold">
                  Organization Activity
                </h2>

                <p className="mt-1 text-sm text-fg-muted">
                  Recent organization and security activity.
                </p>

              </div>

              <div className="flex gap-3">

                <select className="rounded-lg border border-white/10 bg-surface-sunken px-3 py-2 text-sm">

                  <option>
                    All Activity
                  </option>

                  <option>
                    Users
                  </option>

                  <option>
                    Assets
                  </option>

                  <option>
                    Security
                  </option>

                </select>

                <select className="rounded-lg border border-white/10 bg-surface-sunken px-3 py-2 text-sm">

                  <option>
                    Last 24 Hours
                  </option>

                  <option>
                    Last 7 Days
                  </option>

                  <option>
                    Last 30 Days
                  </option>

                </select>

              </div>

            </div>

            <div className="mt-6 flex min-h-[200px] flex-col items-center justify-center rounded-xl border border-dashed border-white/10 bg-surface-sunken">

              <AlertTriangle
                size={28}
                className="text-fg-faint"
              />

              <p className="mt-4 font-medium">
                No organization activity available
              </p>

              <p className="mt-2 text-sm text-fg-muted">
                Activity will appear when organization
                data is connected.
              </p>

            </div>

          </section>

        </div>

      </main>

    </div>
  )
}

function OrganizationCard({
  title,
  value,
  icon,
}: {
  title: string
  value: string
  icon: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-surface-sunken p-5">

      <div className="flex items-center gap-3">

        <div className="rounded-lg bg-brand-500/10 p-3 text-brand-400">
          {icon}
        </div>

        <div>

          <p className="text-sm text-fg-muted">
            {title}
          </p>

          <p className="font-medium">
            {value}
          </p>

        </div>

      </div>

    </div>
  )
}

function SecurityItem({
  severity,
}: {
  severity:
    | "Critical"
    | "High"
    | "Medium"
    | "Low"
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-white/10 bg-surface-sunken p-4">

      <SeverityBadge
        severity={severity}
      />

      <span className="text-xl font-semibold">
        0
      </span>

    </div>
  )
}

export default OrganizationDashboard
