import {
  type FormEvent,
  useState,
} from "react"

import {
  ShieldCheck,
} from "lucide-react"

import {
  useLocation,
  useNavigate,
} from "react-router-dom"

import {
  apiResendVerification,
  apiVerifyEmail,
} from "../lib/api"

// Only digits are ever valid in a 6-digit code.
const CODE_PATTERN = /^[0-9]{6}$/

function VerifyEmail() {
  const navigate = useNavigate()
  const location = useLocation()

  const routeState = location.state as
    | { email?: string; notice?: string }
    | null

  const stateEmail = routeState?.email || ""

  const [email, setEmail] = useState(stateEmail)
  const [code, setCode] = useState("")

  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")
  const [notice] = useState(routeState?.notice || "")

  const [submitting, setSubmitting] = useState(false)
  const [resending, setResending] = useState(false)

  const handleVerify = async (e: FormEvent) => {
    e.preventDefault()

    setError("")
    setSuccess("")

    if (!email.trim()) {
      setError("Please enter the email on your account.")
      return
    }

    if (!CODE_PATTERN.test(code.trim())) {
      setError("Please enter the 6-digit code from your email.")
      return
    }

    setSubmitting(true)

    try {
      await apiVerifyEmail(email.trim().toLowerCase(), code.trim())

      setSuccess("Account verified. You can now sign in.")

      setTimeout(() => {
        navigate("/login")
      }, 1000)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not verify this code. Please try again.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleResend = async () => {
    setError("")
    setSuccess("")

    if (!email.trim()) {
      setError("Please enter the email on your account.")
      return
    }

    setResending(true)

    try {
      await apiResendVerification(email.trim().toLowerCase())
      setSuccess("A new verification code has been sent.")
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
              Verify Your Account
            </h1>

            <p className="text-sm text-fg-muted">
              Your account was locked after too many sign-in attempts. Enter the 6-digit code we
              emailed you to unlock it.
            </p>

          </div>

        </div>

        {notice && (
          <div className="mb-5 rounded-xl border border-brand-500/20 bg-brand-500/10 p-3 text-sm text-brand-300">
            {notice}
          </div>
        )}

        <form
          onSubmit={handleVerify}
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
              Verification Code
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
            {submitting ? "Verifying..." : "Verify Email"}
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

export default VerifyEmail
