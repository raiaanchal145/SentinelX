import { useCallback, useEffect, useState } from "react"
import { useParams } from "react-router-dom"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import Breadcrumbs from "../../../components/ui/Breadcrumbs"
import EmptyState from "../../../components/EmptyState"
import Skeleton from "../../../components/ui/Skeleton"
import Tabs from "../../../components/ui/Tabs"
import { apiGetOrganizationDetail, ApiError, type OrganizationDetail as OrganizationDetailType } from "../../../lib/api"

import OverviewTab from "../components/org-detail/OverviewTab"
import MembersTab from "../components/org-detail/MembersTab"
import AccessModulesTab from "../components/org-detail/AccessModulesTab"
import SocTab from "../components/org-detail/SocTab"
import AssetsTab from "../components/org-detail/AssetsTab"
import ActivityTab from "../components/org-detail/ActivityTab"
import SettingsTab from "../components/org-detail/SettingsTab"

const STATUS_TONE: Record<OrganizationDetailType["status"], "brand" | "success" | "danger" | "neutral"> = {
  active: "success",
  suspended: "danger",
  archived: "neutral",
}

/** Platform admin's organization detail page (Prompt B section A3):
 * six tabs over one organization. Each tab lazily fetches its own data
 * (Tabs only renders the active panel), and any tab that mutates state
 * calls back into `reload()` here so every tab reflects the latest
 * organization row after a change made in another tab. */
function OrganizationDetail() {
  const { id } = useParams<{ id: string }>()

  const [detail, setDetail] = useState<OrganizationDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const reload = useCallback(() => {
    if (!id) return
    setLoading(true)
    setLoadError("")
    apiGetOrganizationDetail(id)
      .then(setDetail)
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load this organization."))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(reload, [reload])

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <Breadcrumbs
            items={[
              { label: "Organizations", path: "/admin/organizations" },
              { label: detail?.name ?? "Organization" },
            ]}
          />

          {loading && <Skeleton count={4} className="h-10 w-full" />}

          {!loading && loadError && (
            <EmptyState title="Couldn't load this organization" description={loadError} action={{ label: "Retry", onClick: reload }} />
          )}

          {!loading && !loadError && detail && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold text-fg-primary">{detail.name}</h1>
                <Badge tone={STATUS_TONE[detail.status]}>{detail.status}</Badge>
                <Badge tone="neutral">{detail.soc_mode === "managed" ? "Managed SOC" : "In-house SOC"}</Badge>
              </div>

              <Tabs
                ariaLabel="Organization detail"
                tabs={[
                  { id: "overview", label: "Overview", content: <OverviewTab detail={detail} /> },
                  { id: "members", label: "Members", content: <MembersTab organizationId={detail.id} /> },
                  {
                    id: "access",
                    label: "Access and modules",
                    content: <AccessModulesTab detail={detail} onSaved={reload} />,
                  },
                  { id: "soc", label: "SOC", content: <SocTab detail={detail} onSaved={reload} /> },
                  { id: "assets", label: "Assets", content: <AssetsTab organizationId={detail.id} /> },
                  { id: "activity", label: "Activity", content: <ActivityTab organizationId={detail.id} /> },
                  { id: "settings", label: "Settings", content: <SettingsTab detail={detail} onSaved={reload} /> },
                ]}
              />
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default OrganizationDetail
