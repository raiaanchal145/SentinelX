import { useEffect, useState } from "react"

import {
  Activity,
  Server,
  ShieldAlert,
  Users,
} from "lucide-react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"
import StatCard from "../components/StatCard"
import SeverityBadge from "../components/SeverityBadge"

import { apiGetStatsOverview } from "../lib/api"

function AdminDashboard() {
  const [assetsCount, setAssetsCount] = useState<number | null>(null)
  const [usersCount, setUsersCount] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false

    apiGetStatsOverview()
      .then((stats) => {
        if (cancelled) return
        setAssetsCount(stats.assets)
        setUsersCount(stats.users)
      })
      .catch(() => {
        // Backend not reachable -- leave the cards showing "0" rather than crash the page.
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
              System Administration
            </p>

            <h1 className="mt-2 text-3xl font-semibold">
              Admin Dashboard
            </h1>

            <p className="mt-2 text-sm text-fg-muted">
              Complete visibility across SentinelX.
            </p>

          </div>

          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">

            <StatCard
              title="Organization Assets"
              value={
                assetsCount === null
                  ? "..."
                  : String(assetsCount)
              }
              description="Registered infrastructure assets"
              icon={Server}
            />

            <StatCard
              title="Security Users"
              value={
                usersCount === null
                  ? "..."
                  : String(usersCount)
              }
              description="Registered organization users"
              icon={Users}
            />

            <StatCard
              title="Open Incidents"
              value="0"
              description="Organization-wide incidents"
              icon={ShieldAlert}
            />

            <StatCard
              title="Security Events"
              value="0"
              description="Processed security activity"
              icon={Activity}
            />

          </div>

          <section className="mt-8 rounded-2xl border border-white/10 bg-surface p-6">

            <div className="flex items-center justify-between">

              <div>

                <h2 className="text-lg font-semibold">
                  Security Overview
                </h2>

                <p className="mt-1 text-sm text-fg-muted">
                  Organization-wide threat visibility.
                </p>

              </div>

              <select className="rounded-xl border border-white/10 bg-surface-sunken px-4 py-2 text-sm text-fg-secondary outline-none">

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

            <div className="mt-8 grid gap-4 md:grid-cols-4">

              <div className="rounded-xl bg-surface-sunken p-5">

                <SeverityBadge
                  severity="Critical"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

              <div className="rounded-xl bg-surface-sunken p-5">

                <SeverityBadge
                  severity="High"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

              <div className="rounded-xl bg-surface-sunken p-5">

                <SeverityBadge
                  severity="Medium"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

              <div className="rounded-xl bg-surface-sunken p-5">

                <SeverityBadge
                  severity="Low"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

            </div>

          </section>

        </div>

      </main>

    </div>
  )
}

export default AdminDashboard
