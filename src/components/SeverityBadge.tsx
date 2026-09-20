import type { LucideIcon } from "lucide-react"
import {
  AlertOctagon,
  AlertTriangle,
  AlertCircle,
  ArrowDownCircle,
  Info,
} from "lucide-react"

/**
 * Canonical (lowercase) severity levels. New code should always use these.
 */
export type Severity = "critical" | "high" | "medium" | "low" | "info"

// The admin dashboards (AdminDashboard/OrganizationDashboard) pass
// Title-Case literals ("Critical", "High", ...). That doesn't match the
// lowercase `.severity-*` classes in index.css, so those specific badges
// have always rendered without their color tint -- a pre-existing
// cosmetic quirk, not something introduced here. Per instructions to fix
// TypeScript errors without changing admin-side appearance, this type is
// only WIDENED to accept that casing; the render logic below is
// unchanged for it, so those call sites look exactly as they do today.
type LegacySeverityCasing = "Critical" | "High" | "Medium" | "Low" | "Info"

type SeverityBadgeProps = {
  severity: Severity | LegacySeverityCasing
  /**
   * Adds a small icon ahead of the label so severity is never conveyed by
   * color alone. Defaults to off so existing (admin) call sites keep
   * rendering exactly as before; new SOC/IT/Manager/Auditor UI should
   * pass `showIcon` together with a canonical lowercase Severity value.
   */
  showIcon?: boolean
  className?: string
}

const SEVERITY_ICON: Record<string, LucideIcon> = {
  critical: AlertOctagon,
  high: AlertTriangle,
  medium: AlertCircle,
  low: ArrowDownCircle,
  info: Info,
}

function SeverityBadge({
  severity,
  showIcon = false,
  className = "",
}: SeverityBadgeProps) {
  const Icon = showIcon ? SEVERITY_ICON[severity.toLowerCase()] : null

  return (
    <span
      className={`severity-badge severity-${severity} gap-1 ${className}`.trim()}
    >
      {Icon && <Icon size={12} aria-hidden="true" />}
      {severity}
    </span>
  )
}

export default SeverityBadge
