import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function AuditorAuditLogs() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Audit Logs"
        description="The full, exportable audit trail will appear here."
      />
    </div>
  )
}

export default AuditorAuditLogs
