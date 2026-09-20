import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function SocIncidents() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Incidents"
        description="Open and past incidents will appear here once incident data is connected."
      />
    </div>
  )
}

export default SocIncidents
