import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react"

export type DropdownMenuItem = {
  key: string
  label: ReactNode
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
}

type DropdownMenuProps = {
  /** Accessible name for the menu itself (announced by screen readers). */
  label: string
  trigger: ReactNode
  items: DropdownMenuItem[]
  align?: "left" | "right"
  className?: string
}

function DropdownMenu({
  label,
  trigger,
  items,
  align = "right",
  className = "",
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    function onDocClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setOpen(false)
    }

    document.addEventListener("mousedown", onDocClick)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDocClick)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  function handleTriggerKeyDown(event: KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      setOpen(true)
      setActiveIndex(0)
    }
  }

  function handleMenuKeyDown(event: KeyboardEvent) {
    const enabled = items
      .map((item, index) => ({ item, index }))
      .filter((entry) => !entry.item.disabled)

    if (event.key === "ArrowDown") {
      event.preventDefault()
      const next = enabled.find((entry) => entry.index > activeIndex) ?? enabled[0]
      if (next) setActiveIndex(next.index)
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      const reversed = [...enabled].reverse()
      const prev = reversed.find((entry) => entry.index < activeIndex) ?? reversed[0]
      if (prev) setActiveIndex(prev.index)
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      const current = items[activeIndex]
      if (current && !current.disabled) {
        current.onSelect()
        setOpen(false)
      }
    } else if (event.key === "Escape") {
      setOpen(false)
    }
  }

  return (
    <div ref={rootRef} className={`relative inline-block ${className}`.trim()}>
      <span
        onClick={() => setOpen((value) => !value)}
        onKeyDown={handleTriggerKeyDown}
        role="button"
        tabIndex={0}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
      >
        {trigger}
      </span>

      {open && (
        <div
          role="menu"
          aria-label={label}
          onKeyDown={handleMenuKeyDown}
          className={`absolute z-50 mt-2 min-w-[210px] rounded-panel border border-line bg-surface-raised p-1 shadow-xl ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {items.map((item, index) => (
            <button
              key={item.key}
              role="menuitem"
              type="button"
              disabled={item.disabled}
              tabIndex={-1}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => {
                item.onSelect()
                setOpen(false)
              }}
              className={`flex w-full items-center gap-2 rounded-control px-3 py-2 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
                index === activeIndex ? "bg-surface-hover" : ""
              } ${item.danger ? "text-danger-fg" : "text-fg-secondary"}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default DropdownMenu
