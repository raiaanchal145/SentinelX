import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function IncidentDetail() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Incident detail"
        description="The incident timeline, evidence and response actions will appear here."
      />
    </div>
  )
}

export default IncidentDetail
