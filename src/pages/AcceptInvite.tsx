import { type FormEvent, useEffect, useState } from "react"
import { Eye, EyeOff, ShieldCheck } from "lucide-react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { apiAcceptInvitation, apiGetInvitation, ApiError, type InvitationDetail } from "../lib/api"
import { homePathFor, roleLabel } from "../lib/auth"

/**
 * Public, unauthenticated page reached from an emailed invitation link
 * (?token=...). Validates the token, shows the organization/role/email
 * read-only, collects a name + password, and signs the new account in
 * on success. See docs/API_CONTRACT.md ("Public: /api/v1/invitations").
 */
function AcceptInvite() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get("token") ?? ""

  const [invitation, setInvitation] = useState<InvitationDetail | null>(null)
  const [loadError, setLoadError] = useState("")
  const [loading, setLoading] = useState(true)

  const [fullName, setFullName] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!token) {
      setLoadError("This invitation link is missing its token.")
      setLoading(false)
      return
    }

    let cancelled = false

    apiGetInvitation(token)
      .then((detail) => {
        if (cancelled) return
        setInvitation(detail)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(
          err instanceof ApiError
            ? "This invitation link is invalid or has expired. Ask whoever sent it for a new one."
            : "Could not load this invitation. Please try again.",
        )
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [token])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError("")

    if (!fullName.trim() || !password.trim() || !confirmPassword.trim()) {
      setError("Please complete all fields.")
      return
    }

    if (password.length < 6) {
      setError("Password must contain at least 6 characters.")
      return
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.")
      return
    }

    setSubmitting(true)

    try {
      const { access_token, user } = await apiAcceptInvitation(token, fullName.trim(), password)

      localStorage.setItem("sentinelx_token", access_token)
      localStorage.setItem("sentinelx_logged_in", "true")
      localStorage.setItem("sentinelx_role", user.role)
      localStorage.setItem("sentinelx_name", user.name)
      localStorage.setItem("sentinelx_email", user.email)
      localStorage.setItem("sentinelx_account_type", user.account_type)

      navigate(homePathFor(user.role), { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not create your account. Please try again.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6 text-white">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-surface p-8">
        <div className="mb-8 flex items-center gap-3">
          <div className="rounded-xl bg-brand-500/10 p-3">
            <ShieldCheck className="text-brand-400" size={28} />
          </div>

          <div>
            <h1 className="text-2xl font-bold">Accept Invitation</h1>
            <p className="text-sm text-fg-muted">Set up your SentinelX account</p>
          </div>
        </div>

        {loading && (
          <div className="rounded-xl border border-white/10 bg-surface-sunken p-4 text-sm text-fg-muted">
            Checking your invitation...
          </div>
        )}

        {!loading && loadError && (
          <div className="space-y-4">
            <div className="rounded-xl bg-danger/10 p-3 text-sm text-danger-fg">{loadError}</div>
            <button
              type="button"
              onClick={() => navigate("/login")}
              className="w-full rounded-xl border border-white/10 bg-surface-sunken py-3 font-medium hover:bg-surface-hover"
            >
              Back to sign in
            </button>
          </div>
        )}

        {!loading && !loadError && invitation && (
          <>
            <div className="mb-6 space-y-2 rounded-xl border border-white/10 bg-surface-sunken p-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-fg-muted">Email</span>
                <span className="font-medium">{invitation.email}</span>
              </div>

              {invitation.organization_name && (
                <div className="flex items-center justify-between">
                  <span className="text-fg-muted">Organization</span>
                  <span className="font-medium">{invitation.organization_name}</span>
                </div>
              )}

              <div className="flex items-center justify-between">
                <span className="text-fg-muted">Role</span>
                <span className="font-medium">{roleLabel(invitation.role)}</span>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="mb-2 block text-sm">Full Name</label>
                <input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
                  required
                />
              </div>

              <div>
                <label className="mb-2 block text-sm">Password</label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 pr-12 outline-none focus:border-brand-500"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm">Confirm Password</label>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 pr-12 outline-none focus:border-brand-500"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted"
                    tabIndex={-1}
                  >
                    {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="rounded-xl bg-danger/10 p-3 text-sm text-danger-fg">{error}</div>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-xl bg-brand-600 py-3 font-medium hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "Creating account..." : "Accept & Sign In"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

export default AcceptInvite
