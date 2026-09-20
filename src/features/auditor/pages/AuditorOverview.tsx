import EmptyState from "../../../components/EmptyState"
import DemoDataChip from "../../../components/shared/DemoDataChip"

function AuditorOverview() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <DemoDataChip />
      </div>

      <EmptyState
        title="Overview"
        description="A summary of organization security activity will appear here."
      />
    </div>
  )
}

export default AuditorOverview
