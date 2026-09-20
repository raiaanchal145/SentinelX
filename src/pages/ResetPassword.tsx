import {
  type FormEvent,
  useState,
} from "react"

import {
  Eye,
  EyeOff,
  ShieldCheck,
} from "lucide-react"

import {
  useLocation,
  useNavigate,
} from "react-router-dom"

import {
  apiForgotPassword,
  apiResetPassword,
} from "../lib/api"

const CODE_PATTERN = /^[0-9]{6}$/

function ResetPassword() {
  const navigate = useNavigate()
  const location = useLocation()

  const stateEmail =
    (location.state as { email?: string } | null)?.email || ""

  const [email, setEmail] = useState(stateEmail)
  const [code, setCode] = useState("")

  const [newPassword, setNewPassword] = useState("")
  const [confirmNewPassword, setConfirmNewPassword] = useState("")

  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmNewPassword, setShowConfirmNewPassword] =
    useState(false)

  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  const [submitting, setSubmitting] = useState(false)
  const [resending, setResending] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    setError("")
    setSuccess("")

    if (!email.trim()) {
      setError("Please enter your account email.")
      return
    }

    if (!CODE_PATTERN.test(code.trim())) {
      setError("Please enter the 6-digit code from your email.")
      return
    }

    if (newPassword.length < 6) {
      setError("Password must contain at least 6 characters.")
      return
    }

    if (newPassword !== confirmNewPassword) {
      setError("Passwords do not match.")
      return
    }

    setSubmitting(true)

    try {
      await apiResetPassword(
        email.trim().toLowerCase(),
        code.trim(),
        newPassword,
      )

      setSuccess("Password reset. You can now sign in.")

      setTimeout(() => {
        navigate("/login")
      }, 1000)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not reset the password. Please try again.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleResend = async () => {
    setError("")
    setSuccess("")

    if (!email.trim()) {
      setError("Please enter your account email.")
      return
    }

    setResending(true)

    try {
      await apiForgotPassword(email.trim().toLowerCase())
      setSuccess("A new password reset code has been sent.")
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not resend the code. Please try again.",
      )
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6 text-white">

      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-surface p-8">

        <div className="mb-8 flex items-center gap-3">

          <div className="rounded-xl bg-brand-500/10 p-3">

            <ShieldCheck
              className="text-brand-400"
              size={28}
            />

          </div>

          <div>

            <h1 className="text-2xl font-bold">
              Reset Password
            </h1>

            <p className="text-sm text-fg-muted">
              Enter the code and your new password
            </p>

          </div>

        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-5"
        >

          <div>

            <label className="mb-2 block text-sm">
              Email
            </label>

            <input
              type="email"
              value={email}
              onChange={(e) =>
                setEmail(e.target.value)
              }
              className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
              required
            />

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Reset Code
            </label>

            <input
              value={code}
              onChange={(e) =>
                setCode(e.target.value)
              }
              placeholder="6-digit code"
              inputMode="numeric"
              maxLength={6}
              className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 tracking-[0.5em] outline-none focus:border-brand-500"
              required
            />

          </div>

          <div>

            <label className="mb-2 block text-sm">
              New Password
            </label>

            <div className="relative">

              <input
                type={
                  showNewPassword
                    ? "text"
                    : "password"
                }
                value={newPassword}
                onChange={(e) =>
                  setNewPassword(e.target.value)
                }
                className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 pr-12 outline-none focus:border-brand-500"
                required
              />

              <button
                type="button"
                onClick={() =>
                  setShowNewPassword(!showNewPassword)
                }
                className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted"
                tabIndex={-1}
              >

                {showNewPassword
                  ? <EyeOff size={18} />
                  : <Eye size={18} />
                }

              </button>

            </div>

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Confirm New Password
            </label>

            <div className="relative">

              <input
                type={
                  showConfirmNewPassword
                    ? "text"
                    : "password"
                }
                value={confirmNewPassword}
                onChange={(e) =>
                  setConfirmNewPassword(e.target.value)
                }
                className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 pr-12 outline-none focus:border-brand-500"
                required
              />

              <button
                type="button"
                onClick={() =>
                  setShowConfirmNewPassword(
                    !showConfirmNewPassword,
                  )
                }
                className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted"
                tabIndex={-1}
              >

                {showConfirmNewPassword
                  ? <EyeOff size={18} />
                  : <Eye size={18} />
                }

              </button>

            </div>

          </div>

          {error && (
            <div className="rounded-xl bg-danger/10 p-3 text-sm text-danger-fg">
              {error}
            </div>
          )}

          {success && (
            <div className="rounded-xl bg-success/10 p-3 text-sm text-success-fg">
              {success}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-brand-600 py-3 font-medium hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Resetting..." : "Reset Password"}
          </button>

        </form>

        <div className="mt-6 text-center text-sm text-fg-muted">

          Didn't get a code?{" "}

          <button
            onClick={handleResend}
            disabled={resending}
            className="text-brand-400 disabled:opacity-60"
          >
            {resending ? "Sending..." : "Resend code"}
          </button>

        </div>

      </div>

    </div>
  )
}

export default ResetPassword
