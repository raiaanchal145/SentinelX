type Severity =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "info"

type SeverityBadgeProps = {
  severity: Severity
}

function SeverityBadge({
  severity,
}: SeverityBadgeProps) {
  return (
    <span
      className={`severity-badge severity-${severity}`}
    >
      {severity}
    </span>
  )
}

export default SeverityBadge