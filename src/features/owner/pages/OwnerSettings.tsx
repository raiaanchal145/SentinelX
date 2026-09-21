import { useEffect, useState } from "react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import EmptyState from "../../../components/EmptyState"
import Skeleton from "../../../components/ui/Skeleton"
import { apiGetOrganizationOverview, ApiError, type OrganizationOverview } from "../../../lib/api"

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="mt-1 text-sm text-fg-primary">{value}</p>
    </div>
  )
}

/** Organization owner: read-only settings (Prompt B section B5) --
 * these fields are platform-controlled; the owner can view but not
 * change them (compare to the platform admin's editable equivalent on
 * the organization detail page's Settings tab). */
function OwnerSettings() {
  const [overview, setOverview] = useState<OrganizationOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  function load() {
    setLoading(true)
    setLoadError("")
    apiGetOrganizationOverview()
      .then(setOverview)
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
          <div>
            <h1 className="text-2xl font-semibold text-fg-primary">Settings</h1>
            <p className="mt-1 text-xs text-fg-muted">
              These details are set by SentinelX. Contact a platform administrator to change them.
            </p>
          </div>

          {loading ? (
            <Skeleton count={4} className="h-10 w-full" />
          ) : loadError || !overview ? (
            <EmptyState title="Couldn't load your organization" description={loadError} action={{ label: "Retry", onClick: load }} />
          ) : (
            <div className="max-w-xl space-y-5 rounded-card border border-line bg-surface p-5">
              <Field label="Organization name" value={overview.name} />
              <Field label="Industry" value={overview.industry || "Not set"} />
              <Field label="Member limit" value={overview.max_members ? String(overview.max_members) : "No limit"} />
              <div>
                <p className="text-xs text-fg-muted">Status</p>
                <div className="mt-1">
                  <Badge tone="success">{overview.status}</Badge>
                </div>
              </div>
              <div>
                <p className="text-xs text-fg-muted">SOC mode</p>
                <div className="mt-1">
                  <Badge tone="neutral">{overview.soc_mode === "managed" ? "Managed" : "In-house"}</Badge>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default OwnerSettings
