import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function SocEvents() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Events"
        description="Raw and normalized security events will appear here once event ingestion is connected."
      />
    </div>
  )
}

export default SocEvents
