import { useEffect, useState } from "react"
import {
  Bell,
  LogOut,
  Search,
  ShieldAlert,
  User as UserIcon,
} from "lucide-react"

import { Link, useNavigate } from "react-router-dom"

import { apiListApprovals } from "../lib/approvalsApi"
import { logout as clearSession, roleLabel } from "../lib/auth"

function Topbar() {
  const navigate = useNavigate()

  const name =
    localStorage.getItem(
      "sentinelx_name",
    ) || "User"

  const role =
    localStorage.getItem(
      "sentinelx_role",
    ) || ""

  const [pendingApprovals, setPendingApprovals] = useState(0)
  const canApprove = role === "security_manager" || role === "organization_admin"

  useEffect(() => {
    if (!canApprove) return

    let cancelled = false
    function fetchPending() {
      apiListApprovals("pending")
        .then((res) => {
          if (!cancelled) {
            setPendingApprovals(res.approvals.length)
          }
        })
        .catch(() => {
          // Non-blocking for topbar
        })
    }

    fetchPending()

    const onApprovalsChange = () => fetchPending()
    window.addEventListener("sentinelx_approvals_change", onApprovalsChange)
    window.addEventListener("focus", onApprovalsChange)

    return () => {
      cancelled = true
      window.removeEventListener("sentinelx_approvals_change", onApprovalsChange)
      window.removeEventListener("focus", onApprovalsChange)
    }
  }, [canApprove])

  const logout = () => {
    // Shared logout clears every session key (token, email, account type
    // included) -- the old inline version left stale values behind.
    clearSession()
    navigate("/login")
  }

  // roleLabel maps every role to its real label; the old inline ternary
  // defaulted organization_admin (and anything unknown) to "IT / Developer".
  const formattedRole = roleLabel(role)

  return (
    <header className="flex h-20 items-center justify-between border-b border-white/10 bg-surface-sunken px-6">

      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent("open_command_palette"))}
        className="hidden items-center gap-3 rounded-xl border border-white/10 bg-surface px-4 py-2 md:flex text-fg-muted hover:border-white/20 transition cursor-pointer text-left"
        aria-label="Open command palette"
      >
        <Search
          size={18}
          className="text-fg-muted"
        />
        <span className="w-52 text-sm text-fg-faint">Search or press Ctrl+K...</span>
        <kbd className="rounded border border-white/10 bg-surface-sunken px-1.5 py-0.5 text-[10px] text-fg-muted font-mono">
          Ctrl K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-4">

        {canApprove && pendingApprovals > 0 && (
          <Link
            to="/manager/approvals"
            title={`${pendingApprovals} approval${pendingApprovals === 1 ? "" : "s"} awaiting review`}
            className="flex items-center gap-1.5 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs font-semibold text-warning-fg transition hover:bg-warning/20"
          >
            <ShieldAlert size={15} aria-hidden="true" />
            <span>{pendingApprovals} Pending Approval{pendingApprovals === 1 ? "" : "s"}</span>
          </Link>
        )}

        <button className="rounded-xl border border-white/10 bg-surface p-2.5 text-fg-subtle transition hover:text-brand-400">
          <Bell size={19} />
        </button>

        <Link
          to="/profile"
          className="rounded-xl border border-white/10 bg-surface p-2.5 text-fg-subtle transition hover:text-brand-400"
          title="Account Profile & Settings"
        >
          <UserIcon size={18} />
        </Link>

        <Link
          to="/profile"
          className="hidden text-right sm:block group transition hover:opacity-90"
          title="Account profile and settings"
        >
          <p className="text-sm font-medium text-white group-hover:text-brand-300 transition">
            {name}
          </p>

          <p className="text-xs text-fg-muted">
            {formattedRole}
          </p>
        </Link>

        <button
          onClick={logout}
          className="rounded-xl border border-danger/20 bg-danger/5 p-2.5 text-danger-fg transition hover:bg-danger/10"
        >

          <LogOut size={18} />

        </button>

      </div>

    </header>
  )
}

export default Topbar