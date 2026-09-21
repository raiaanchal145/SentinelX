import { ShieldOff } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { getSession, homePathFor, logout } from "../lib/auth"

/**
 * The 403 state for a route/module the current account isn't allowed
 * to see -- e.g. a direct URL to a page a module was turned off for.
 * Shown instead of a blank page (Prompt B section C5).
 */
function NoAccess() {
  const navigate = useNavigate()
  const { role } = getSession()

  const handleSignOut = () => {
    logout()
    navigate("/login", { replace: true })
  }

  const handleGoHome = () => {
    navigate(homePathFor(role), { replace: true })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6 text-white">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-surface p-8 text-center">
        <div className="mx-auto mb-6 w-fit rounded-full bg-surface-sunken p-4">
          <ShieldOff className="text-fg-muted" size={32} />
        </div>

        <h1 className="text-2xl font-bold">You don't have access to this page</h1>

        <p className="mt-3 text-sm leading-6 text-fg-muted">
          This page isn't enabled for your account. If you think this is a mistake, contact your
          organization owner or a SentinelX administrator.
        </p>

        <div className="mt-6 space-y-3">
          <button
            type="button"
            onClick={handleGoHome}
            className="w-full rounded-xl bg-brand-600 py-3 font-medium hover:bg-brand-500"
          >
            Go to my dashboard
          </button>

          <button
            type="button"
            onClick={handleSignOut}
            className="w-full rounded-xl border border-white/10 bg-surface-sunken py-3 font-medium hover:bg-surface-hover"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}

export default NoAccess
