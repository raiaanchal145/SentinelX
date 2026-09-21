import AssetsPage from "../../assets/AssetsPage"
import { useMe } from "../../../lib/me"

/** Auditor's assets: read-only (backend role default). */
function AuditorAssets() {
  const { me } = useMe()
  const access = me?.effective_modules?.assets === "write" ? "write" : "read"

  return (
    <div className="p-6 lg:p-8">
      <AssetsPage
        access={access}
        title="Assets"
        description="A read-only view of the organization's asset inventory."
      />
    </div>
  )
}

export default AuditorAssets
