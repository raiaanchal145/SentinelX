import IncidentOversightView from "../../soc/components/IncidentOversightView"

/** The organization owner's incident oversight (module `incidents` read,
 * both soc modes; read-only everywhere -- the backend refuses owner
 * writes outright). A managed org's timeline arrives shared-only from the
 * API, matching the security manager's view. */
function OwnerIncidents() {
  return (
    <IncidentOversightView
      basePath="/organization/incidents"
      intro="Read-only oversight of your organization's incident lifecycle."
    />
  )
}

export default OwnerIncidents
