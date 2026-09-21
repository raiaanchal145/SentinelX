import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  Search,
  ShieldCheck,
} from "lucide-react"

import IconButton from "../components/ui/IconButton"
import DropdownMenu, { type DropdownMenuItem } from "../components/ui/DropdownMenu"
import Drawer from "../components/ui/Drawer"
import Breadcrumbs, { type Crumb } from "../components/ui/Breadcrumbs"
import StatusDot from "../components/ui/StatusDot"
import ConnectivityBanner from "../components/shared/ConnectivityBanner"
import { useHealthStatus } from "../hooks/useHealthStatus"
import { ROLE_NAV } from "../lib/roleNav"
import { getSession, logout, roleLabel } from "../lib/auth"
import { useMe } from "../lib/me"

type PageChromeContextValue = {
  setBreadcrumbs: (crumbs: Crumb[] | null) => void
  setActions: (node: ReactNode) => void
}

const PageChromeContext = createContext<PageChromeContextValue | null>(null)

/**
 * Lets a page rendered inside UserLayout customise the sub-bar: its own
 * breadcrumb trail (e.g. "Incidents / INC-1042") and an actions slot on
 * the right (filters, a primary button, ...). Call once per page; it
 * cleans up automatically when the page unmounts so the next route falls
 * back to the default (nav-label) breadcrumb.
 */
export function usePageChrome(crumbs: Crumb[], actions: ReactNode = null) {
  const ctx = useContext(PageChromeContext)
  const crumbKey = crumbs.map((crumb) => `${crumb.label}|${crumb.path ?? ""}`).join(">")

  useEffect(() => {
    ctx?.setBreadcrumbs(crumbs)
    return () => {
      ctx?.setBreadcrumbs(null)
    }
    // Re-run only when the breadcrumb trail itself actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crumbKey])

  useEffect(() => {
    ctx?.setActions(actions)
    return () => {
      ctx?.setActions(null)
    }
  })
}

function UserLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const session = getSession()
  const role = session.role
  const { me } = useMe()
  const effectiveModules = me?.effective_modules
  // A nav item with no `module` (every role's Overview/home) is always
  // shown; one that names a module needs it in the account's
  // effective_modules (docs/API_CONTRACT.md's GET /auth/me) -- this is
  // what keeps a disabled module's link from appearing at all, per
  // Prompt B section C4 ("Top-nav shows only permitted modules").
  const navItems = useMemo(() => {
    const items = role ? ROLE_NAV[role] ?? [] : []
    if (!effectiveModules) return items
    return items.filter((item) => !item.module || item.module in effectiveModules)
  }, [role, effectiveModules])
  const orgName = me?.organization?.name ?? "Your Organization"
  const health = useHealthStatus()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [customCrumbs, setCustomCrumbs] = useState<Crumb[] | null>(null)
  const [actions, setActions] = useState<ReactNode>(null)
  const mainRef = useRef<HTMLDivElement>(null)

  // Focus moves to the main landmark on every route change, per the
  // accessibility requirements (keyboard users land somewhere sensible).
  useEffect(() => {
    mainRef.current?.focus()
  }, [location.pathname])

  const defaultCrumbs = useMemo<Crumb[]>(() => {
    const match = navItems.find((item) =>
      item.end ? location.pathname === item.path : location.pathname.startsWith(item.path),
    )
    return match ? [{ label: match.label }] : []
  }, [navItems, location.pathname])

  const breadcrumbs = customCrumbs ?? defaultCrumbs

  const chromeValue = useMemo<PageChromeContextValue>(
    () => ({ setBreadcrumbs: setCustomCrumbs, setActions }),
    [],
  )

  const userMenuItems: DropdownMenuItem[] = [
    { key: "profile", label: "Profile", onSelect: () => {}, disabled: true },
    {
      key: "sign-out",
      label: (
        <span className="flex items-center gap-2">
          <LogOut size={14} aria-hidden="true" />
          Sign out
        </span>
      ),
      onSelect: () => {
        logout()
        navigate("/login")
      },
    },
  ]

  const notificationItems: DropdownMenuItem[] = [
    { key: "empty", label: "No new notifications", onSelect: () => {}, disabled: true },
  ]
  const unreadCount = 0

  return (
    <div className="flex min-h-screen flex-col bg-canvas text-fg-primary">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-control focus:bg-brand-500 focus:px-4 focus:py-2 focus:text-fg-primary"
      >
        Skip to content
      </a>

      <ConnectivityBanner status={health} />

      <header className="sticky top-0 z-40 flex h-16 shrink-0 items-center gap-3 border-b border-line bg-sidebar px-4 lg:px-6">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation menu"
          className="rounded-control p-2 text-fg-subtle hover:bg-surface-hover hover:text-fg-primary lg:hidden"
        >
          <Menu size={22} aria-hidden="true" />
        </button>

        <div className="flex items-center gap-2.5">
          <div className="rounded-panel bg-brand-500/10 p-2">
            <ShieldCheck size={20} className="text-brand-400" aria-hidden="true" />
          </div>
          <div className="hidden leading-tight sm:block">
            <p className="text-sm font-bold text-fg-primary">
              Sentinel<span className="text-brand-400">X</span>
            </p>
            <p className="text-[11px] text-fg-muted">
              Security Operations · {orgName}
            </p>
          </div>
        </div>

        <nav aria-label="Primary" className="ml-4 hidden items-center gap-1 lg:flex">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.end}
              className={({ isActive }) =>
                `rounded-control px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-brand-500/10 text-brand-400"
                    : "text-fg-subtle hover:bg-surface-hover hover:text-fg-primary"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            // TODO: phase 6 -- wire this up to the real CommandPalette overlay.
            onClick={() => {}}
            aria-label="Open command palette"
            className="hidden items-center gap-2 rounded-control border border-line bg-surface px-3 py-2 text-xs text-fg-muted transition hover:border-line-strong hover:text-fg-subtle sm:flex"
          >
            <Search size={14} aria-hidden="true" />
            <span>Search</span>
            <kbd className="rounded-control border border-line-strong bg-surface-sunken px-1.5 py-0.5 text-[10px]">
              Ctrl K
            </kbd>
          </button>

          <DropdownMenu
            label="Notifications"
            align="right"
            items={notificationItems}
            trigger={
              <span className="relative inline-flex">
                <IconButton icon={Bell} label="Notifications" />
                {unreadCount > 0 && (
                  <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-pill bg-critical px-1 text-[10px] font-bold text-fg-primary">
                    {unreadCount}
                  </span>
                )}
              </span>
            }
          />

          <StatusDot status={health} showLabel={false} className="hidden md:inline-flex" />

          <DropdownMenu
            label="User menu"
            align="right"
            items={userMenuItems}
            trigger={
              <span className="flex items-center gap-2 rounded-control border border-line bg-surface px-2 py-1.5 transition hover:border-line-strong">
                <span className="hidden text-right sm:block">
                  <span className="block text-xs font-medium text-fg-primary">
                    {session.name ?? "User"}
                  </span>
                  <span className="block text-[11px] text-fg-muted">{roleLabel(role)}</span>
                </span>
                <ChevronDown size={14} className="text-fg-muted" aria-hidden="true" />
              </span>
            }
          />
        </div>
      </header>

      <div className="flex min-h-[44px] items-center justify-between gap-4 border-b border-line bg-surface px-4 py-2 lg:px-6">
        <Breadcrumbs items={breadcrumbs} />
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Navigation">
        <nav aria-label="Primary" className="flex flex-col gap-1">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.end}
                onClick={() => setDrawerOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-control px-3 py-2.5 text-sm ${
                    isActive
                      ? "bg-brand-500/10 text-brand-400"
                      : "text-fg-subtle hover:bg-surface-hover hover:text-fg-primary"
                  }`
                }
              >
                <Icon size={18} aria-hidden="true" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      </Drawer>

      <main
        id="main-content"
        ref={mainRef}
        tabIndex={-1}
        className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 outline-none lg:px-6"
      >
        <PageChromeContext.Provider value={chromeValue}>
          <Outlet />
        </PageChromeContext.Provider>
      </main>
    </div>
  )
}

export default UserLayout
