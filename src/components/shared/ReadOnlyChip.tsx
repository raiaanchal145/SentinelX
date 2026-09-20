import { Lock } from "lucide-react"

/** Persistent indicator for the Auditor role: every mutating control is hidden, not just disabled. */
function ReadOnlyChip() {
  return (
    <span className="inline-flex items-center gap-1 rounded-pill border border-line-strong bg-surface-hover px-2.5 py-1 text-xs font-medium text-fg-subtle">
      <Lock size={12} aria-hidden="true" />
      Read-only access
    </span>
  )
}

export default ReadOnlyChip
