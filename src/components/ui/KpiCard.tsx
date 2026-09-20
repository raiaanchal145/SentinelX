import { TrendingDown, TrendingUp } from "lucide-react"
import { Link } from "react-router-dom"
import type { ReactNode } from "react"

type Tone = "critical" | "high" | "medium" | "low" | "info" | "neutral"

const TONE_ACCENT: Record<Tone, string> = {
  critical: "border-l-critical",
  high: "border-l-high",
  medium: "border-l-medium",
  low: "border-l-low",
  info: "border-l-info",
  neutral: "border-l-line-strong",
}

type KpiCardProps = {
  label: string
  value: ReactNode
  link?: string
  tone?: Tone
  trend?: { direction: "up" | "down" | "flat"; label: string; good: boolean }
}

/** Extends StatCard's pattern for the role dashboards -- StatCard itself is
 * left alone since admin pages still use it directly. */
function KpiCard({ label, value, link, tone = "neutral", trend }: KpiCardProps) {
  const content = (
    <div
      className={`h-full rounded-card border border-line border-l-4 bg-surface p-4 transition ${TONE_ACCENT[tone]} ${
        link ? "hover:border-line-strong hover:bg-surface-hover" : ""
      }`}
    >
      <p className="text-xs font-medium text-fg-muted">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-fg-primary">{value}</p>
      {trend && (
        <p className={`mt-1 flex items-center gap-1 text-xs ${trend.good ? "text-success-fg" : "text-danger-fg"}`}>
          {trend.direction === "down" ? (
            <TrendingDown size={12} aria-hidden="true" />
          ) : (
            <TrendingUp size={12} aria-hidden="true" />
          )}
          {trend.label}
        </p>
      )}
    </div>
  )

  if (!link) return content

  return (
    <Link to={link} className="block h-full rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400">
      {content}
    </Link>
  )
}

export default KpiCard
