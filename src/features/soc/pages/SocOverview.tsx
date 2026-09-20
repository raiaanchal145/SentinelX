import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function SocOverview() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Overview"
        description="Your triage queue and KPIs will appear here once alert data is connected."
      />
    </div>
  )
}

export default SocOverview
