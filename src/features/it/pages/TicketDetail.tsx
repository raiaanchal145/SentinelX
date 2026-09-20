import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function TicketDetail() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Ticket detail"
        description="The remediation checklist, runbook and comment thread will appear here."
      />
    </div>
  )
}

export default TicketDetail
