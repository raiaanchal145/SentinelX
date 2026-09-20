import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ManagerAudit() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Audit"
        description="A read-only view of the audit log will appear here."
      />
    </div>
  )
}

export default ManagerAudit
