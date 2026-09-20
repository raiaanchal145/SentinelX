type ProgressBarProps = {
  value: number
  max: number
  label?: string
}

function ProgressBar({ value, max, label }: ProgressBarProps) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0

  return (
    <div>
      {label && (
        <p className="mb-1 text-[11px] text-fg-muted">
          {label} ({value}/{max})
        </p>
      )}
      <div
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label}
        className="h-1.5 w-full overflow-hidden rounded-pill bg-surface-hover"
      >
        <div
          className="h-full rounded-pill bg-brand-500 transition-[width] duration-200"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default ProgressBar
