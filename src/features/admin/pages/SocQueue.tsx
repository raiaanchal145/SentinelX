import { useEffect, useState } from "react"
import { Radar } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import EmptyState from "../../../components/EmptyState"
import Skeleton from "../../../components/ui/Skeleton"
import { apiGetMyAssignedOrganizations, ApiError, type SocAnalystAssignedOrg } from "../../../lib/api"

/** platform_soc_analyst's home page (Prompt B section A5) -- a
 * placeholder for now (the real triage queue arrives with the alerts
 * work), plus the analyst's own assigned organizations, read from the
 * self-service GET /admin/soc-analysts/me endpoint. */
function SocQueue() {
  const [orgs, setOrgs] = useState<SocAnalystAssignedOrg[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  function load() {
    setLoading(true)
    setLoadError("")
    apiGetMyAssignedOrganizations()
      .then((res) => setOrgs(res.assigned_organizations))
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load your organizations."))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div>
            <p className="text-sm text-brand-400">Platform SOC</p>
            <h1 className="mt-2 text-2xl font-semibold text-fg-primary">SOC Queue</h1>
          </div>

          <EmptyState
            title="The SOC queue is coming soon"
            description="Cross-organization alert triage arrives with the alerts work. For now, here are the organizations assigned to you."
          />

          <section aria-label="Your assigned organizations" className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">Your assigned organizations</h2>

            {loading ? (
              <Skeleton count={3} className="mt-3 h-9 w-full" />
            ) : loadError ? (
              <p className="mt-2 text-xs text-danger-fg">{loadError}</p>
            ) : !orgs || orgs.length === 0 ? (
              <p className="mt-2 text-xs text-fg-muted">
                You haven't been assigned to any organizations yet. A platform administrator assigns you from the SOC
                Team page.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {orgs.map((org) => (
                  <li
                    key={org.id}
                    className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-sm"
                  >
                    <span className="flex items-center gap-2 font-medium text-fg-primary">
                      <Radar size={14} className="text-brand-400" aria-hidden="true" />
                      {org.name}
                    </span>
                    <Badge tone={org.status === "active" ? "success" : "brand"}>{org.status}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}

export default SocQueue
