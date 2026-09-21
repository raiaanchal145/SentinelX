import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import AssetsPage from "../../assets/AssetsPage"
import { useMe } from "../../../lib/me"

/** Organization owner's assets: every platform-enabled module is write
 * for the owner, so this is write unless the platform disabled assets. */
function OwnerAssets() {
  const { me } = useMe()
  const access = me?.effective_modules?.assets === "write" ? "write" : "read"

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="p-6 lg:p-8">
          <AssetsPage
            access={access}
            title="Assets"
            description="Your organization's asset inventory -- events, alerts, incidents and tickets all point at these."
          />
        </div>
      </main>
    </div>
  )
}

export default OwnerAssets
