import AssetsPage from "../../../assets/AssetsPage"

/** Read-only view of one organization's assets for the platform admin's
 * organization detail -- backed by GET /admin/organizations/{id}/assets
 * (super_admin-only; the write-capable /assets endpoints reject platform
 * accounts, so access is always "read" here). */
function AssetsTab({ organizationId }: { organizationId: string }) {
  return (
    <AssetsPage
      access="read"
      organizationId={organizationId}
      title="Assets"
      description="Read-only view of this organization's asset inventory."
    />
  )
}

export default AssetsTab
