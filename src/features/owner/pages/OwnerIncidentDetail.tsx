import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import IncidentDetail from "../../soc/pages/IncidentDetail"

/** Organization owner's read-only incident detail view with sidebar and topbar shell. */
function OwnerIncidentDetail() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <IncidentDetail />
        </div>
      </main>
    </div>
  )
}

export default OwnerIncidentDetail
