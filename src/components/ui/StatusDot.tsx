type Status = "operational" | "degraded" | "offline"

const STATUS_CONFIG: Record<Status, { dot: string; label: string }> = {
  operational: { dot: "bg-success", label: "Operational" },
  degraded: { dot: "bg-medium", label: "Degraded" },
  offline: { dot: "bg-critical", label: "Offline" },
}

type StatusDotProps = {
  status: Status
  showLabel?: boolean
  className?: string
}

function StatusDot({ status, showLabel = true, className = "" }: StatusDotProps) {
  const config = STATUS_CONFIG[status]

  return (
    <span
      role="status"
      aria-live="polite"
      className={`inline-flex items-center gap-2 text-xs text-fg-muted ${className}`.trim()}
    >
      <span className={`h-2 w-2 rounded-pill ${config.dot}`} aria-hidden="true" />
      {showLabel ? (
        <span>{config.label}</span>
      ) : (
        <span className="sr-only">System status: {config.label}</span>
      )}
    </span>
  )
}

export default StatusDot
export type { Status }
