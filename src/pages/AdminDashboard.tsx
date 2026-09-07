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

function AdminDashboard() {
  return (
    <div className="flex min-h-screen bg-[#021325] text-white">

      <Sidebar />

      <main className="min-w-0 flex-1">

        <Topbar />

        <div className="p-6 lg:p-8">

          <div className="mb-8">

            <p className="text-sm text-blue-400">
              System Administration
            </p>

            <h1 className="mt-2 text-3xl font-semibold">
              Admin Dashboard
            </h1>

            <p className="mt-2 text-sm text-slate-500">
              Complete visibility across SentinelX.
            </p>

          </div>

          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">

            <StatCard
              title="Organization Assets"
              value="0"
              description="Registered infrastructure assets"
              icon={Server}
            />

            <StatCard
              title="Security Users"
              value="0"
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

          <section className="mt-8 rounded-2xl border border-white/10 bg-[#0b1f33] p-6">

            <div className="flex items-center justify-between">

              <div>

                <h2 className="text-lg font-semibold">
                  Security Overview
                </h2>

                <p className="mt-1 text-sm text-slate-500">
                  Organization-wide threat visibility.
                </p>

              </div>

              <select className="rounded-xl border border-white/10 bg-[#061727] px-4 py-2 text-sm text-slate-300 outline-none">

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

              <div className="rounded-xl bg-[#061727] p-5">

                <SeverityBadge
                  severity="Critical"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

              <div className="rounded-xl bg-[#061727] p-5">

                <SeverityBadge
                  severity="High"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

              <div className="rounded-xl bg-[#061727] p-5">

                <SeverityBadge
                  severity="Medium"
                />

                <p className="mt-4 text-3xl font-semibold">
                  0
                </p>

              </div>

              <div className="rounded-xl bg-[#061727] p-5">

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