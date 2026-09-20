import { useEffect, useState } from "react"

type CountdownChipProps = {
  dueAt: string | null
  /** When true, this represents a completed/closed item -- shown neutrally. */
  done?: boolean
}

function formatDelta(ms: number): string {
  const abs = Math.abs(ms)
  const totalMinutes = Math.round(abs / 60_000)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

/** Steps through the existing severity tokens as time runs out -- never a
 * new color, just which token applies. */
function CountdownChip({ dueAt, done = false }: CountdownChipProps) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (done || !dueAt) return
    const interval = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(interval)
  }, [done, dueAt])

  if (done) {
    return (
      <span className="inline-flex items-center rounded-pill border border-line bg-surface-hover px-2 py-0.5 text-[11px] font-medium text-fg-muted">
        Done
      </span>
    )
  }

  if (!dueAt) {
    return (
      <span className="inline-flex items-center rounded-pill border border-line bg-surface-hover px-2 py-0.5 text-[11px] font-medium text-fg-faint">
        No SLA
      </span>
    )
  }

  const msLeft = new Date(dueAt).getTime() - now
  const overdue = msLeft < 0
  const hoursLeft = msLeft / (60 * 60 * 1000)

  const tone = overdue
    ? "border-critical/25 bg-critical/10 text-critical-fg"
    : hoursLeft < 1
      ? "border-high/25 bg-high/10 text-high-fg"
      : hoursLeft < 4
        ? "border-medium/25 bg-medium/10 text-medium-fg"
        : "border-line bg-surface-hover text-fg-muted"

  return (
    <span className={`inline-flex items-center gap-1 rounded-pill border px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      {overdue ? `Overdue ${formatDelta(msLeft)}` : `${formatDelta(msLeft)} left`}
    </span>
  )
}

export default CountdownChip
