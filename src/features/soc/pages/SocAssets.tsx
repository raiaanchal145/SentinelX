import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function SocAssets() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Assets"
        description="Monitored assets, criticality and agent status will appear here."
      />
    </div>
  )
}

export default SocAssets
