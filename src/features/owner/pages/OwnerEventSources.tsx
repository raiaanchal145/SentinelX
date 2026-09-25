import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import EventSourcesPage from "../../events/EventSourcesPage"

/** Organization owner's event sources: the backend's dedicated role rule
 * (owner + security_manager only -- docs/DECISIONS.md) is the authority;
 * this wrapper is just the owner layout around the shared page. */
function OwnerEventSources() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <EventSourcesPage title="Event sources" />
      </main>
    </div>
  )
}

export default OwnerEventSources
