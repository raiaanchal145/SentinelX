import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react"

export type TabItem = {
  id: string
  label: string
  content: ReactNode
  /** Optional trailing badge/count, e.g. a pending-approval count. */
  badge?: ReactNode
  disabled?: boolean
}

type TabsProps = {
  tabs: TabItem[]
  ariaLabel: string
  /** Controlled active tab id. Omit to let Tabs manage its own state. */
  value?: string
  /** Initial active tab id when uncontrolled. Defaults to the first tab. */
  defaultValue?: string
  onChange?: (id: string) => void
  className?: string
}

/**
 * Minimal ARIA tablist (single-select, automatic activation): arrow keys
 * move focus and select in one step, Home/End jump to the first/last
 * enabled tab. Only the active panel is rendered, so tab content that
 * fetches its own data doesn't mount until it's selected.
 */
function Tabs({ tabs, ariaLabel, value, defaultValue, onChange, className = "" }: TabsProps) {
  const baseId = useId()
  const [internalValue, setInternalValue] = useState(defaultValue ?? tabs[0]?.id)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  const activeId = value ?? internalValue
  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0]

  function selectTab(id: string) {
    if (value === undefined) {
      setInternalValue(id)
    }
    onChange?.(id)
  }

  function focusAndSelect(id: string) {
    tabRefs.current[id]?.focus()
    selectTab(id)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const enabled = tabs
      .map((tab, i) => ({ tab, i }))
      .filter(({ tab }) => !tab.disabled)
    if (enabled.length === 0) return

    const currentPos = enabled.findIndex(({ i }) => i === index)

    let targetPos: number | null = null
    switch (event.key) {
      case "ArrowRight":
        targetPos = currentPos === -1 ? 0 : (currentPos + 1) % enabled.length
        break
      case "ArrowLeft":
        targetPos = currentPos === -1 ? 0 : (currentPos - 1 + enabled.length) % enabled.length
        break
      case "Home":
        targetPos = 0
        break
      case "End":
        targetPos = enabled.length - 1
        break
      default:
        return
    }

    event.preventDefault()
    focusAndSelect(enabled[targetPos].tab.id)
  }

  return (
    <div className={className}>
      <div role="tablist" aria-label={ariaLabel} className="flex items-center gap-1 border-b border-line">
        {tabs.map((tab, index) => {
          const selected = tab.id === activeId
          return (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[tab.id] = el
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${tab.id}`}
              aria-disabled={tab.disabled || undefined}
              tabIndex={selected ? 0 : -1}
              disabled={tab.disabled}
              onClick={() => selectTab(tab.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
                selected
                  ? "border-brand-500 text-fg-primary"
                  : "border-transparent text-fg-muted hover:text-fg-primary"
              }`}
            >
              {tab.label}
              {tab.badge}
            </button>
          )
        })}
      </div>
      {activeTab && (
        <div
          role="tabpanel"
          id={`${baseId}-panel-${activeTab.id}`}
          aria-labelledby={`${baseId}-tab-${activeTab.id}`}
          tabIndex={0}
          className="pt-4"
        >
          {activeTab.content}
        </div>
      )}
    </div>
  )
}

export default Tabs
