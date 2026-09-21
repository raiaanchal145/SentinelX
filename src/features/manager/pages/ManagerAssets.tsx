import AssetsPage from "../../assets/AssetsPage"
import { useMe } from "../../../lib/me"

/** Security manager's assets: full write (backend role default). */
function ManagerAssets() {
  const { me } = useMe()
  const access = me?.effective_modules?.assets === "write" ? "write" : "read"

  return (
    <div className="p-6 lg:p-8">
      <AssetsPage
        access={access}
        title="Assets"
        description="Your organization's asset inventory."
      />
    </div>
  )
}

export default ManagerAssets
