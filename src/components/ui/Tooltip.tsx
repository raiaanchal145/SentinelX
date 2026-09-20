import { useId, useState, type ReactNode } from "react"

type TooltipProps = {
  label: string
  children: ReactNode
  side?: "top" | "bottom"
}

function Tooltip({ label, children, side = "top" }: TooltipProps) {
  const [open, setOpen] = useState(false)
  const id = useId()

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open && (
        <span
          id={id}
          role="tooltip"
          className={`pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-control border border-line bg-surface-raised px-2 py-1 text-xs text-fg-secondary shadow-lg ${
            side === "top" ? "-top-2 -translate-y-full" : "-bottom-2 translate-y-full"
          }`}
        >
          {label}
        </span>
      )}
    </span>
  )
}

export default Tooltip
