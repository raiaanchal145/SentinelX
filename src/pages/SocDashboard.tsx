import {
  Activity,
  AlertTriangle,
  FileSearch,
  ShieldAlert,
} from "lucide-react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"
import StatCard from "../components/StatCard"
import EmptyState from "../components/EmptyState"

function SOCDashboard() {
  return (
    <div className="flex min-h-screen bg-[#021325] text-white">

      <Sidebar />

      <main className="min-w-0 flex-1">

        <Topbar />

        <div className="p-6 lg:p-8">

          <div className="mb-8">

            <p className="text-sm text-blue-400">
              Security Operations Center
            </p>

            <h1 className="mt-2 text-3xl font-semibold">
              SOC Dashboard
            </h1>

            <p className="mt-2 text-sm text-slate-500">
              Monitor security events, alerts and
              investigations.
            </p>

          </div>

          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">

            <StatCard
              title="Security Events"
              value="0"
              description="Events available for analysis"
              icon={Activity}
            />

            <StatCard
              title="Active Alerts"
              value="0"
              description="Alerts requiring review"
              icon={AlertTriangle}
            />

            <StatCard
              title="Open Incidents"
              value="0"
              description="Incidents under investigation"
              icon={ShieldAlert}
            />

            <StatCard
              title="Investigations"
              value="0"
              description="Active investigation cases"
              icon={FileSearch}
            />

          </div>

          <div className="mt-8 grid gap-6 xl:grid-cols-3">

            <section className="rounded-2xl border border-white/10 bg-[#0b1f33] p-6 xl:col-span-2">

              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">

                <div>

                  <h2 className="text-lg font-semibold">
                    Security Events
                  </h2>

                  <p className="text-sm text-slate-500">
                    Incoming events will appear here.
                  </p>

                </div>

                <div className="flex gap-3">

                  <select className="rounded-lg border border-white/10 bg-[#061727] px-3 py-2 text-sm">

                    <option>
                      All Severity
                    </option>

                    <option>
                      Critical
                    </option>

                    <option>
                      High
                    </option>

                    <option>
                      Medium
                    </option>

                    <option>
                      Low
                    </option>

                  </select>

                  <select className="rounded-lg border border-white/10 bg-[#061727] px-3 py-2 text-sm">

                    <option>
                      All Status
                    </option>

                    <option>
                      New
                    </option>

                    <option>
                      Investigating
                    </option>

                    <option>
                      Closed
                    </option>

                  </select>

                </div>

              </div>

              <div className="mt-6">

                <EmptyState
                  title="No security events available"
                  description="Security events will appear here when event ingestion is connected."
                />

              </div>

            </section>

            <section className="rounded-2xl border border-white/10 bg-[#0b1f33] p-6">

              <h2 className="text-lg font-semibold">
                Analyst Workspace
              </h2>

              <p className="mt-2 text-sm text-slate-500">
                Your investigation activity.
              </p>

              <div className="mt-6 space-y-4">

                <WorkspaceItem
                  title="My Assigned Alerts"
                  value="0"
                />

                <WorkspaceItem
                  title="Active Investigations"
                  value="0"
                />

                <WorkspaceItem
                  title="Pending Actions"
                  value="0"
                />

              </div>

            </section>

          </div>

        </div>

      </main>

    </div>
  )
}

function WorkspaceItem({
  title,
  value,
}: {
  title: string
  value: string
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-white/10 bg-[#061727] p-4">

      <p className="text-sm text-slate-400">
        {title}
      </p>

      <span className="text-xl font-semibold text-blue-400">
        {value}
      </span>

    </div>
  )
}

export default SOCDashboard