import { useEffect, useState } from "react"
import { Layers, UserPlus } from "lucide-react"
import { useNavigate } from "react-router-dom"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import EmptyState from "../../../components/EmptyState"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import { apiGetOrganizationOverview, ApiError, type OrganizationOverview } from "../../../lib/api"

/** Organization owner's home page (Prompt B section B1). Reads the
 * live status from GET /organization on every load rather than trusting
 * a cached session, since that endpoint deliberately keeps working
 * regardless of status (docs/API_CONTRACT.md) -- an owner who was
 * already logged in when their organization got suspended/archived
 * lands on the matching status screen instead of a broken dashboard. */
function OwnerDashboard() {
  const navigate = useNavigate()
  const [overview, setOverview] = useState<OrganizationOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  function load() {
    setLoading(true)
    setLoadError("")
    apiGetOrganizationOverview()
      .then((res) => {
        if (res.status === "pending") {
          navigate("/organization-pending", { replace: true })
          return
        }
        if (res.status === "suspended" || res.status === "archived") {
          navigate("/organization-suspended", { replace: true, state: { status: res.status } })
          return
        }
        setOverview(res)
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load your organization."))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          {loading && <Skeleton count={4} className="h-10 w-full" />}

          {!loading && loadError && (
            <EmptyState title="Couldn't load your organization" description={loadError} action={{ label: "Retry", onClick: load }} />
          )}

          {!loading && !loadError && overview && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-2xl font-semibold text-fg-primary">{overview.name}</h1>
                  <Badge tone="success">{overview.status}</Badge>
                  <Badge tone="neutral">{overview.soc_mode === "managed" ? "Managed SOC" : "In-house SOC"}</Badge>
                </div>
                <div className="flex gap-2">
                  <Button variant="secondary" icon={<UserPlus size={16} />} onClick={() => navigate("/organization/members")}>
                    Invite member
                  </Button>
                  <Button variant="secondary" icon={<Layers size={16} />} onClick={() => navigate("/organization/access")}>
                    Manage access
                  </Button>
                </div>
              </div>

              {overview.soc_mode === "managed" && (
                <div className="rounded-card border border-brand-500/20 bg-brand-500/5 p-4 text-sm text-brand-300">
                  SentinelX's platform SOC team monitors this organization's alerts and incidents. Your own
                  soc_analyst members (if any) have read-only oversight until you switch to in-house SOC.
                </div>
              )}

              <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
                <KpiCard label="Members" value={overview.members ?? 0} link="/organization/members" />
                <KpiCard label="Pending invites" value={overview.pending_invitations ?? 0} link="/organization/members" />
                <KpiCard label="Assets" value={overview.assets ?? 0} />
                <KpiCard
                  label="Open incidents"
                  value={overview.open_incidents ?? 0}
                  tone={(overview.open_incidents ?? 0) > 0 ? "high" : "neutral"}
                />
                <KpiCard
                  label="Open tickets"
                  value={overview.open_tickets ?? 0}
                  tone={(overview.open_tickets ?? 0) > 0 ? "medium" : "neutral"}
                />
              </section>

              <section aria-label="Recent activity" className="rounded-card border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold text-fg-primary">Recent activity</h2>
                {!overview.recent_activity || overview.recent_activity.length === 0 ? (
                  <div className="mt-3">
                    <EmptyState title="No activity yet" description="Actions taken in your organization will show up here." />
                  </div>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {overview.recent_activity.map((entry) => (
                      <li
                        key={entry.id}
                        className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-xs"
                      >
                        <span className="font-medium text-fg-primary">{entry.action}</span>
                        <span className="text-fg-muted">
                          {entry.created_at ? new Date(entry.created_at).toLocaleString() : "--"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default OwnerDashboard
