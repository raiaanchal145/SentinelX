import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { useNavigate } from "react-router-dom"
import {
  AlertTriangle,
  Clock,
  Command,
  Search,
  Server,
  ShieldAlert,
  Ticket,
  User as UserIcon,
  X,
} from "lucide-react"

import { ROLE_NAV } from "../lib/roleNav"
import { getSession } from "../lib/auth"
import { useMe } from "../lib/me"
import {
  apiSearchPalette,
  type PaletteAlertItem,
  type PaletteAssetItem,
  type PaletteIncidentItem,
  type PaletteTicketItem,
} from "../lib/api"
import Badge from "./ui/Badge"

type RecentPaletteItem = {
  id: string
  title: string
  category: "page" | "alert" | "incident" | "ticket" | "asset"
  path: string
  subtitle?: string
}

const RECENT_STORAGE_KEY = "sentinelx_palette_recent"
const MAX_RECENT = 6

export default function CommandPalette() {
  const navigate = useNavigate()
  const { loggedIn, role } = getSession()
  const { me } = useMe()
  const effectiveModules = me?.effective_modules

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)

  // Remote search results
  const [alerts, setAlerts] = useState<PaletteAlertItem[]>([])
  const [incidents, setIncidents] = useState<PaletteIncidentItem[]>([])
  const [tickets, setTickets] = useState<PaletteTicketItem[]>([])
  const [assets, setAssets] = useState<PaletteAssetItem[]>([])

  // Recent items from localStorage
  const [recentItems, setRecentItems] = useState<RecentPaletteItem[]>(() => {
    try {
      const stored = localStorage.getItem(RECENT_STORAGE_KEY)
      return stored ? JSON.parse(stored) : []
    } catch {
      return []
    }
  })

  // Keyboard navigation index
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // Accessible navigation pages for the current user
  const accessiblePages = useMemo(() => {
    if (!loggedIn || !role) return []
    const items = ROLE_NAV[role] ?? []
    const filtered = items.filter(
      (item) => !item.module || (effectiveModules && item.module in effectiveModules),
    )
    return [
      ...filtered,
      { label: "Account Profile", path: "/profile", icon: UserIcon },
    ]
  }, [loggedIn, role, effectiveModules])

  // Filtered pages based on query
  const matchingPages = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return accessiblePages
    return accessiblePages.filter(
      (p) => p.label.toLowerCase().includes(q) || p.path.toLowerCase().includes(q),
    )
  }, [accessiblePages, query])

  // Listen to Global Shortcut Ctrl+K / Cmd+K and custom event
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen((prev) => !prev)
      } else if (e.key === "Escape" && open) {
        e.preventDefault()
        setOpen(false)
      }
    }

    const handleCustomOpen = () => {
      setOpen(true)
    }

    window.addEventListener("keydown", handleKeyDown)
    window.addEventListener("open_command_palette", handleCustomOpen)

    return () => {
      window.removeEventListener("keydown", handleKeyDown)
      window.removeEventListener("open_command_palette", handleCustomOpen)
    }
  }, [open])

  // Reset state when opening
  useEffect(() => {
    if (open) {
      setQuery("")
      setSelectedIndex(0)
      setAlerts([])
      setIncidents([])
      setTickets([])
      setAssets([])
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  // Perform search query when typing 2+ chars
  useEffect(() => {
    const trimmed = query.trim()
    if (trimmed.length < 2) {
      setAlerts([])
      setIncidents([])
      setTickets([])
      setAssets([])
      setLoading(false)
      return
    }

    let active = true
    setLoading(true)

    const timer = setTimeout(() => {
      apiSearchPalette(trimmed, 5)
        .then((res) => {
          if (!active) return
          setAlerts(res.alerts || [])
          setIncidents(res.incidents || [])
          setTickets(res.tickets || [])
          setAssets(res.assets || [])
        })
        .catch(() => {
          if (!active) return
          setAlerts([])
          setIncidents([])
          setTickets([])
          setAssets([])
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }, 180)

    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [query])

  // Save item to recent list
  const recordRecent = (item: RecentPaletteItem) => {
    setRecentItems((prev) => {
      const next = [item, ...prev.filter((p) => p.id !== item.id)].slice(0, MAX_RECENT)
      try {
        localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // Ignore quota errors
      }
      return next
    })
  }

  const clearRecent = (e: React.MouseEvent) => {
    e.stopPropagation()
    setRecentItems([])
    localStorage.removeItem(RECENT_STORAGE_KEY)
  }

  const handleSelect = (item: {
    id: string
    title: string
    path: string
    category: RecentPaletteItem["category"]
    subtitle?: string
  }) => {
    recordRecent({
      id: item.id,
      title: item.title,
      category: item.category,
      path: item.path,
      subtitle: item.subtitle,
    })
    setOpen(false)
    navigate(item.path)
  }

  // Linear list of all currently active interactive items for arrow-key navigation
  type ActionItem = {
    id: string
    title: string
    path: string
    category: RecentPaletteItem["category"]
    subtitle?: string
    badge?: ReactNode
    icon: ReactNode
  }

  const allItems: ActionItem[] = useMemo(() => {
    const list: ActionItem[] = []

    // 1. If searching, show matching pages first
    if (query.trim().length > 0) {
      for (const p of matchingPages) {
        const Icon = p.icon
        list.push({
          id: `page-${p.path}`,
          title: p.label,
          path: p.path,
          category: "page",
          subtitle: p.path,
          icon: <Icon size={16} className="text-brand-400" />,
        })
      }
      for (const inc of incidents) {
        list.push({
          id: `inc-${inc.id}`,
          title: inc.title,
          path: role === "super_admin" || role === "platform_soc_analyst" ? `/admin/soc-queue` : `/soc/incidents/${inc.id}`,
          category: "incident",
          subtitle: `Incident · ${inc.status}`,
          badge: <Badge tone="danger">{inc.severity}</Badge>,
          icon: <ShieldAlert size={16} className="text-danger-fg" />,
        })
      }
      for (const a of alerts) {
        list.push({
          id: `alert-${a.id}`,
          title: a.title,
          path: `/soc/alerts`,
          category: "alert",
          subtitle: `Alert · ${a.status}`,
          badge: <Badge tone="brand">{a.severity}</Badge>,
          icon: <AlertTriangle size={16} className="text-warning-fg" />,
        })
      }
      for (const t of tickets) {
        list.push({
          id: `ticket-${t.id}`,
          title: `${t.ticket_number ? `#${t.ticket_number} ` : ""}${t.title}`,
          path: `/it/tickets/${t.id}`,
          category: "ticket",
          subtitle: `Ticket · ${t.status}`,
          badge: <Badge tone="neutral">{t.priority}</Badge>,
          icon: <Ticket size={16} className="text-fg-subtle" />,
        })
      }
      for (const ast of assets) {
        list.push({
          id: `asset-${ast.id}`,
          title: ast.name,
          path: role === "super_admin" ? `/admin/assets` : `/organization/assets`,
          category: "asset",
          subtitle: `${ast.asset_type} · ${ast.ip_address || ast.hostname || "No IP"}`,
          icon: <Server size={16} className="text-brand-400" />,
        })
      }
    } else {
      // 2. Query is empty: show recent items, then navigation pages
      for (const r of recentItems) {
        list.push({
          id: `recent-${r.id}`,
          title: r.title,
          path: r.path,
          category: r.category,
          subtitle: r.subtitle,
          icon: <Clock size={16} className="text-fg-muted" />,
        })
      }
      for (const p of accessiblePages) {
        const Icon = p.icon
        list.push({
          id: `page-${p.path}`,
          title: p.label,
          path: p.path,
          category: "page",
          subtitle: p.path,
          icon: <Icon size={16} className="text-brand-400" />,
        })
      }
    }

    return list
  }, [query, matchingPages, incidents, alerts, tickets, assets, recentItems, accessiblePages, role])

  // Handle keyboard arrows and Enter
  const handleInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setSelectedIndex((prev) => (allItems.length ? (prev + 1) % allItems.length : 0))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setSelectedIndex((prev) => (allItems.length ? (prev - 1 + allItems.length) % allItems.length : 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      if (allItems[selectedIndex]) {
        handleSelect(allItems[selectedIndex])
      }
    }
  }

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 p-4 pt-16 sm:pt-24 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={() => setOpen(false)}
    >
      <div
        className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-line bg-surface-sunken shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Bar */}
        <div className="flex items-center gap-3 border-b border-line px-4 py-3.5 bg-surface">
          <Search size={18} className="text-brand-400 shrink-0" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleInputKeyDown}
            placeholder="Type a command or search alerts, incidents, tickets, assets..."
            className="w-full bg-transparent text-sm text-fg-primary outline-none placeholder:text-fg-faint"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="rounded-control p-1 text-fg-muted hover:text-fg-primary"
              aria-label="Clear search query"
            >
              <X size={16} />
            </button>
          ) : (
            <kbd className="hidden sm:inline-block rounded-control border border-line-strong bg-surface-sunken px-1.5 py-0.5 text-[10px] text-fg-muted font-mono">
              ESC
            </kbd>
          )}
        </div>

        {/* Results Body */}
        <div className="max-h-[60vh] overflow-y-auto p-2">
          {loading && (
            <div className="flex items-center justify-center py-8 text-xs text-fg-muted">
              Searching scoped entities...
            </div>
          )}

          {!loading && allItems.length === 0 && (
            <div className="py-12 text-center text-sm text-fg-muted">
              No results found for &ldquo;<span className="text-fg-primary">{query}</span>&rdquo; within your scope.
            </div>
          )}

          {!loading && query.trim().length === 0 && recentItems.length > 0 && (
            <div className="mb-2 px-2 pt-1 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
              <span>Recent</span>
              <button
                type="button"
                onClick={clearRecent}
                className="text-fg-faint hover:text-fg-subtle lowercase font-normal"
              >
                clear
              </button>
            </div>
          )}

          {!loading &&
            allItems.map((item, idx) => {
              const isSelected = idx === selectedIndex
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm transition ${
                    isSelected ? "bg-surface-hover text-brand-300" : "text-fg-secondary hover:bg-surface"
                  }`}
                >
                  <div className="flex items-center gap-3 truncate">
                    <div className="shrink-0">{item.icon}</div>
                    <div className="truncate">
                      <p className="truncate font-medium text-fg-primary">{item.title}</p>
                      {item.subtitle && (
                        <p className="truncate text-xs text-fg-muted">{item.subtitle}</p>
                      )}
                    </div>
                  </div>
                  {item.badge && <div className="ml-2 shrink-0">{item.badge}</div>}
                </button>
              )
            })}
        </div>

        {/* Footer shortcuts help */}
        <div className="flex items-center justify-between border-t border-line bg-surface px-4 py-2 text-[11px] text-fg-muted">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="rounded border border-line-strong bg-surface-sunken px-1 font-mono">↑</kbd>{" "}
              <kbd className="rounded border border-line-strong bg-surface-sunken px-1 font-mono">↓</kbd> to navigate
            </span>
            <span>
              <kbd className="rounded border border-line-strong bg-surface-sunken px-1 font-mono">↵</kbd> to select
            </span>
            <span>
              <kbd className="rounded border border-line-strong bg-surface-sunken px-1 font-mono">esc</kbd> to close
            </span>
          </div>
          <div className="hidden sm:flex items-center gap-1 text-fg-faint">
            <Command size={12} />
            <span>Command Palette</span>
          </div>
        </div>
      </div>
    </div>
  )
}
