import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ManagerReports() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Reports"
        description="Reports arrive with the reporting phase."
      />
    </div>
  )
}

export default ManagerReports
