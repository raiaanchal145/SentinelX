import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import SecurityActivity from "../../soc/pages/SecurityActivity"

/** Organization owner's read-only security activity oversight (Prompt B):
 * the owner sees their organization's alert counts and details with full
 * sidebar and topbar layout. */
function OwnerSecurityActivity() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <SecurityActivity />
        </div>
      </main>
    </div>
  )
}

export default OwnerSecurityActivity

