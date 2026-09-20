import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ItAssets() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Assets"
        description="Assets you own or are assigned will appear here."
      />
    </div>
  )
}

export default ItAssets
