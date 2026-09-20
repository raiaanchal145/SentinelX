import type { ReactNode } from "react"

type Tone = "brand" | "neutral" | "danger" | "success"

type BadgeProps = {
  children: ReactNode
  tone?: Tone
  className?: string
}

const TONE_CLASSES: Record<Tone, string> = {
  brand: "border-brand-500/20 bg-brand-500/10 text-brand-300",
  neutral: "border-line bg-surface-hover text-fg-subtle",
  danger: "border-danger/20 bg-danger/10 text-danger-fg",
  success: "border-success/20 bg-success/10 text-success-fg",
}

function Badge({ children, tone = "neutral", className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-pill border px-2 py-0.5 text-[11px] font-semibold ${TONE_CLASSES[tone]} ${className}`.trim()}
    >
      {children}
    </span>
  )
}

export default Badge
