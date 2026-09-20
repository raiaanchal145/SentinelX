import { FlaskConical } from "lucide-react"

/** Marks a page as backed by mock data, per the "never present mock data as real" rule. */
function DemoDataChip() {
  return (
    <span
      title="This page is backed by mock data for the demo -- not live production data."
      className="inline-flex items-center gap-1 rounded-pill border border-line bg-surface-hover px-2 py-0.5 text-[11px] font-medium text-fg-muted"
    >
      <FlaskConical size={11} aria-hidden="true" />
      Demo data
    </span>
  )
}

export default DemoDataChip
