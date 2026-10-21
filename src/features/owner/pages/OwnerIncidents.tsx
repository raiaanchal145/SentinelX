import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import IncidentOversightView from "../../soc/components/IncidentOversightView"

/** The organization owner's incident oversight (module `incidents` read,
 * both soc modes; read-only everywhere -- the backend refuses owner
 * writes outright). A managed org's timeline arrives shared-only from the
 * API, matching the security manager's view. */
function OwnerIncidents() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <IncidentOversightView
            basePath="/organization/incidents"
            intro="Read-only oversight of your organization's incident lifecycle."
          />
        </div>
      </main>
    </div>
  )
}

export default OwnerIncidents
