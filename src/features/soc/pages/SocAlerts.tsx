import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function SocAlerts() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Alerts"
        description="The alert queue will appear here once alert data is connected."
      />
    </div>
  )
}

export default SocAlerts
