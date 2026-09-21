import { Clock } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { useMe } from "../lib/me"
import { logout } from "../lib/auth"

/**
 * Shown to an organization owner whose organization is still `pending`
 * platform approval. Per Prompt B section B1, this is the ONLY thing a
 * pending organization's owner sees after logging in -- no dashboard,
 * no nav. See docs/API_CONTRACT.md ("A pending organization's owner is
 * allowed to log in").
 */
function OrganizationPending() {
  const navigate = useNavigate()
  const { me, loading } = useMe()

  const handleSignOut = () => {
    logout()
    navigate("/login", { replace: true })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6 text-white">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-surface p-8 text-center">
        <div className="mx-auto mb-6 w-fit rounded-full bg-brand-500/10 p-4">
          <Clock className="text-brand-400" size={32} />
        </div>

        <h1 className="text-2xl font-bold">Waiting for approval</h1>

        <p className="mt-3 text-sm leading-6 text-fg-muted">
          {loading ? (
            "Checking your organization's status..."
          ) : (
            <>
              {me?.organization?.name ? `"${me.organization.name}" is` : "Your organization is"}{" "}
              pending review by a SentinelX platform administrator. You'll get full access as soon
              as it's approved -- no action is needed from you in the meantime.
            </>
          )}
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

export default OrganizationPending
