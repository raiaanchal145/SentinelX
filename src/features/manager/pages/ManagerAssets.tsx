import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ManagerAssets() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Assets"
        description="A read-only view of organization assets will appear here."
      />
    </div>
  )
}

export default ManagerAssets
