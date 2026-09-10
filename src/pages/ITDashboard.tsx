import {
  CheckCircle2,
  ClipboardList,
  Clock,
  Wrench,
} from "lucide-react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"
import StatCard from "../components/StatCard"
import EmptyState from "../components/EmptyState"

function ITDashboard() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">

      <Sidebar />

      <main className="min-w-0 flex-1">

        <Topbar />

        <div className="p-6 lg:p-8">

          <div className="mb-8">

            <p className="text-sm text-brand-400">
              IT & Development
            </p>

            <h1 className="mt-2 text-3xl font-semibold">
              IT Dashboard
            </h1>

            <p className="mt-2 text-sm text-fg-muted">
              View and manage assigned remediation tasks.
            </p>

          </div>

          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">

            <StatCard
              title="Assigned Tasks"
              value="0"
              description="Tasks assigned to you"
              icon={ClipboardList}
            />

            <StatCard
              title="In Progress"
              value="0"
              description="Remediation currently active"
              icon={Wrench}
            />

            <StatCard
              title="Pending"
              value="0"
              description="Awaiting remediation"
              icon={Clock}
            />

            <StatCard
              title="Completed"
              value="0"
              description="Completed remediation tasks"
              icon={CheckCircle2}
            />

          </div>

          <section className="mt-8 rounded-2xl border border-white/10 bg-surface p-6">

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">

              <div>

                <h2 className="text-lg font-semibold">
                  Remediation Tasks
                </h2>

                <p className="mt-1 text-sm text-fg-muted">
                  Security remediation tasks assigned
                  to the IT team.
                </p>

              </div>

              <div className="flex gap-3">

                <select className="rounded-lg border border-white/10 bg-surface-sunken px-3 py-2 text-sm">

                  <option>
                    All Priority
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

                <select className="rounded-lg border border-white/10 bg-surface-sunken px-3 py-2 text-sm">

                  <option>
                    All Status
                  </option>

                  <option>
                    Pending
                  </option>

                  <option>
                    In Progress
                  </option>

                  <option>
                    Completed
                  </option>

                </select>

              </div>

            </div>

            <div className="mt-6">

              <EmptyState
                title="No remediation tasks assigned"
                description="Remediation tasks generated from security incidents will appear here."
              />

            </div>

          </section>

        </div>

      </main>

    </div>
  )
}

export default ITDashboard