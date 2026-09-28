import IncidentOversightView from "../../soc/components/IncidentOversightView"

/** The security manager's incident oversight (module `incidents` read,
 * both soc modes). Read-only: the backend refuses every write except the
 * manager's own ESCALATED request, which the incident detail offers
 * straight from allowed_next_states. A managed org's timeline arrives
 * shared-only (server-side filter). */
function ManagerIncidents() {
  return (
    <IncidentOversightView
      basePath="/manager/incidents"
      intro="Read-only oversight of your organization's incident lifecycle."
    />
  )
}

export default ManagerIncidents
