import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ManagerOverview() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Overview"
        description="Pending approvals, critical incidents and team workload will appear here."
      />
    </div>
  )
}

export default ManagerOverview
