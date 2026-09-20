import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function AuditorIncidents() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Incidents"
        description="A read-only view of incidents will appear here."
      />
    </div>
  )
}

export default AuditorIncidents
