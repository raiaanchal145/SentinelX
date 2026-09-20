import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function ItTickets() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Tickets"
        description="Tickets handed off from the SOC will appear here."
      />
    </div>
  )
}

export default ItTickets
