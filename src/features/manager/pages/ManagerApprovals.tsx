import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ManagerApprovals() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Approvals"
        description="Requests awaiting your approval will appear here."
      />
    </div>
  )
}

export default ManagerApprovals
