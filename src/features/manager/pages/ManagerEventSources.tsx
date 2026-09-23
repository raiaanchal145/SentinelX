import EventSourcesPage from "../../events/EventSourcesPage"

/** Security manager's event sources: full manage rights (backend's
 * dedicated owner+security_manager rule -- docs/DECISIONS.md). */
function ManagerEventSources() {
  return <EventSourcesPage title="Event sources" />
}

export default ManagerEventSources
