import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ItRunbooks() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Runbooks"
        description="Remediation guides will appear here."
      />
    </div>
  )
}

export default ItRunbooks
