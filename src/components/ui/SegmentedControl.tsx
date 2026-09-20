type SegmentedControlProps<T extends string> = {
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
  ariaLabel: string
}

function SegmentedControl<T extends string>({ options, value, onChange, ariaLabel }: SegmentedControlProps<T>) {
  return (
    <div role="group" aria-label={ariaLabel} className="inline-flex rounded-control border border-line bg-surface p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`rounded-[calc(var(--radius-control)-2px)] px-3 py-1.5 text-xs font-medium transition ${
            value === option.value
              ? "bg-brand-500/10 text-brand-400"
              : "text-fg-muted hover:text-fg-primary"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export default SegmentedControl
