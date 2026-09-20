type BarStripItem = { label: string; value: number; tone?: "critical" | "high" | "medium" | "low" | "info" | "neutral" }

type BarStripProps = {
  items: BarStripItem[]
  summary: string
}

const TONE_BAR: Record<string, string> = {
  critical: "bg-critical",
  high: "bg-high",
  medium: "bg-medium",
  low: "bg-low",
  info: "bg-info",
  neutral: "bg-brand-500",
}

/** A labelled horizontal bar strip -- used for "funnel" style breakdowns
 * (tickets by status) and rule/analyst counts. Values are always shown as
 * text alongside the bar, never color-only. */
function BarStrip({ items, summary }: BarStripProps) {
  const max = Math.max(1, ...items.map((i) => i.value))

  return (
    <div role="img" aria-label={summary} className="space-y-2">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-3">
          <span className="w-32 shrink-0 truncate text-xs text-fg-subtle">{item.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-pill bg-surface-hover">
            <div
              className={`h-full rounded-pill ${TONE_BAR[item.tone ?? "neutral"]}`}
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          <span className="w-8 shrink-0 text-right text-xs font-medium text-fg-primary">{item.value}</span>
        </div>
      ))}
    </div>
  )
}

export default BarStrip
