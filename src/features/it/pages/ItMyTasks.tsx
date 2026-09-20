import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ItMyTasks() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="My Tasks"
        description="Your assigned remediation work will appear here once ticket data is connected."
      />
    </div>
  )
}

export default ItMyTasks
