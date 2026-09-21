import AssetsPage from "../../assets/AssetsPage"
import { useMe } from "../../../lib/me"

/** SOC analyst's assets: read-only -- soc_analyst investigates assets
 * but doesn't manage the inventory (backend role default is read). */
function SocAssets() {
  const { me } = useMe()
  const access = me?.effective_modules?.assets === "write" ? "write" : "read"

  return (
    <div className="p-6 lg:p-8">
      <AssetsPage
        access={access}
        title="Assets"
        description="Monitored assets, criticality and environment -- read-only."
      />
    </div>
  )
}

export default SocAssets
