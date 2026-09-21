import AssetsPage from "../../assets/AssetsPage"
import { useMe } from "../../../lib/me"

/** IT developer's assets: module-level write, row-scoped by the backend
 * to assets they own or that sit on their team (per-row can_edit). */
function ItAssets() {
  const { me } = useMe()
  const access = me?.effective_modules?.assets === "write" ? "write" : "read"

  return (
    <div className="p-6 lg:p-8">
      <AssetsPage
        access={access}
        title="Assets"
        description="Assets you own or that belong to your team are editable; everything else is read-only."
      />
    </div>
  )
}

export default ItAssets
