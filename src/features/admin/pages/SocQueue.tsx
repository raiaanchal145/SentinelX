import { useEffect, useState } from "react"
import { Radar } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import EmptyState from "../../../components/EmptyState"
import Skeleton from "../../../components/ui/Skeleton"
import { apiGetMyAssignedOrganizations, ApiError, type SocAnalystAssignedOrg } from "../../../lib/api"
import AssetsPage from "../../assets/AssetsPage"

/** platform_soc_analyst's home page (Prompt B section A5). The real
 * triage queue arrives with the alerts work; for now this lists the
 * analyst's assigned organizations (self-service
 * GET /admin/soc-analysts/me) and gives a read-only assets view of
 * whichever one is selected -- the same /assets endpoints an
 * organization-side reader uses, with organization_id picking the org
 * and the backend checking it against the analyst's assignments. */
function SocQueue() {
  const [orgs, setOrgs] = useState<SocAnalystAssignedOrg[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null)

  function load() {
    setLoading(true)
    setLoadError("")
    apiGetMyAssignedOrganizations()
      .then((res) => setOrgs(res.assigned_organizations))
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load your organizations."))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const selectedOrg = orgs?.find((org) => org.id === selectedOrgId) ?? null

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
                  <li key={org.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedOrgId(org.id === selectedOrgId ? null : org.id)}
                      aria-pressed={org.id === selectedOrgId}
                      className={`flex w-full items-center justify-between rounded-control border p-2.5 text-sm transition ${
                        org.id === selectedOrgId
                          ? "border-brand-500/40 bg-brand-500/10"
                          : "border-line bg-surface-sunken hover:border-line-strong"
                      }`}
                    >
                      <span className="flex items-center gap-2 font-medium text-fg-primary">
                        <Radar size={14} className="text-brand-400" aria-hidden="true" />
                        {org.name}
                      </span>
                      <span className="flex items-center gap-2">
                        <Badge tone={org.status === "active" ? "success" : "brand"}>{org.status}</Badge>
                        <Badge tone="neutral">Managed SOC</Badge>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {!loading && !loadError && selectedOrg && (
            <section aria-label={`Assets of ${selectedOrg.name}`}>
              <AssetsPage
                access="read"
                organizationId={selectedOrg.id}
                title={`Assets — ${selectedOrg.name}`}
                description="Read-only view of this assigned organization's assets."
              />
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

export default SocQueue
