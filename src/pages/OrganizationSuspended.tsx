import { Ban } from "lucide-react"
import { useLocation, useNavigate } from "react-router-dom"

import { useMe } from "../lib/me"
import { logout } from "../lib/auth"

type RouteState = {
  // Set by Login.tsx when the login attempt itself was rejected with
  // organization_suspended/organization_archived (no session exists
  // yet in that case). Falls back to useMe() for an already-logged-in
  // session whose organization changed status underneath it.
  status?: "suspended" | "archived"
}

/**
 * Shown for a suspended or archived organization -- either because
 * login itself was rejected (docs/API_CONTRACT.md: login's
 * organization_suspended/organization_archived codes) or because an
 * already-logged-in session's organization changed status. Reachable
 * with or without an active session, so "sign out" always just clears
 * local state and returns to /login.
 */
function OrganizationSuspended() {
  const navigate = useNavigate()
  const location = useLocation()
  const { me } = useMe()

  const routeState = location.state as RouteState | null
  const status = routeState?.status ?? me?.organization?.status
  const isArchived = status === "archived"

  const handleSignOut = () => {
    logout()
    navigate("/login", { replace: true })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6 text-white">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-surface p-8 text-center">
        <div className="mx-auto mb-6 w-fit rounded-full bg-danger/10 p-4">
          <Ban className="text-danger-fg" size={32} />
        </div>

        <h1 className="text-2xl font-bold">
          Organization {isArchived ? "archived" : "suspended"}
        </h1>

        <p className="mt-3 text-sm leading-6 text-fg-muted">
          {isArchived
            ? "This organization has been archived and is no longer active. If you believe this is a mistake, contact a SentinelX platform administrator."
            : "This organization has been suspended. If you believe this is a mistake, contact a SentinelX platform administrator."}
        </p>

        <button
          type="button"
          onClick={handleSignOut}
          className="mt-6 w-full rounded-xl border border-white/10 bg-surface-sunken py-3 font-medium hover:bg-surface-hover"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}

export default OrganizationSuspended
