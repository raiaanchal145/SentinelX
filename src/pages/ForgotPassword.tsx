import {
  FormEvent,
  useState,
} from "react"

import {
  ShieldCheck,
} from "lucide-react"

import { useNavigate } from "react-router-dom"

import { apiForgotPassword } from "../lib/api"

const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

function ForgotPassword() {
  const navigate = useNavigate()

  const [email, setEmail] = useState("")

  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    setError("")
    setSuccess("")

    if (!EMAIL_PATTERN.test(email.trim())) {
      setError(
        "Please enter a valid email address (letters, numbers, and . _ % + - only).",
      )
      return
    }

    setSubmitting(true)

    try {
      const targetEmail = email.trim().toLowerCase()

      await apiForgotPassword(targetEmail)

      setSuccess(
        "Check your email for a 6-digit password reset code...",
      )

      setTimeout(() => {
        navigate("/reset-password", {
          state: { email: targetEmail },
        })
      }, 1000)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not send a reset code. Please try again.",
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

            <ShieldCheck
              className="text-brand-400"
              size={28}
            />

          </div>

          <div>

            <h1 className="text-2xl font-bold">
              Forgot Password
            </h1>

            <p className="text-sm text-fg-muted">
              We'll email you a reset code
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
              placeholder="you@example.com"
              className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
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
            {submitting ? "Sending code..." : "Send Reset Code"}
          </button>

        </form>

        <div className="mt-6 text-center text-sm text-fg-muted">

          Remembered your password?{" "}

          <button
            onClick={() =>
              navigate("/login")
            }
            className="text-brand-400"
          >
            Sign in
          </button>

        </div>

      </div>

    </div>
  )
}

export default ForgotPassword
