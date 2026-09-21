import {
  type FormEvent,
  useState,
} from "react"

import {
  Eye,
  EyeOff,
  ShieldCheck,
} from "lucide-react"

import { useNavigate } from "react-router-dom"

import { apiLogin, ApiError } from "../lib/api"
import { homePathFor } from "../lib/auth"

// Same allow-list the backend enforces: only the standard set of
// characters a real email address can contain.
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

function Login() {
  const navigate = useNavigate()

  const [email, setEmail] = useState("")
  const [password, setPassword] =
    useState("")

  const [
    showPassword,
    setShowPassword,
  ] = useState(false)

  const [error, setError] =
    useState("")

  const [submitting, setSubmitting] =
    useState(false)

  const handleLogin = async (
    e: FormEvent<HTMLFormElement>,
  ) => {
    e.preventDefault()

    setError("")

    if (!EMAIL_PATTERN.test(email)) {
      setError(
        "Please enter a valid email address (letters, numbers, and . _ % + - only).",
      )
      return
    }

    setSubmitting(true)

    try {
      const { access_token, user } =
        await apiLogin(email, password)

      localStorage.setItem(
        "sentinelx_token",
        access_token,
      )

      localStorage.setItem(
        "sentinelx_logged_in",
        "true",
      )

      localStorage.setItem(
        "sentinelx_role",
        user.role,
      )

      localStorage.setItem(
        "sentinelx_name",
        user.name,
      )

      localStorage.setItem(
        "sentinelx_email",
        user.email,
      )

      // TODO: replace with real auth (backend already issues a JWT) --
      // kept alongside the existing mock-session keys above.
      localStorage.setItem(
        "sentinelx_account_type",
        user.account_type,
      )

      // A pending organization's owner is allowed to log in (the
      // backend needs a session for /auth/me), but sees only the
      // "waiting for approval" screen -- never the real dashboard.
      // Suspended/archived organizations are rejected by /auth/login
      // itself (see the ApiError handling below), so those two
      // statuses can't reach this branch.
      if (user.organization?.status === "pending") {
        navigate("/organization-pending")
        return
      }

      navigate(homePathFor(user.role))
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "organization_suspended" || err.code === "organization_archived") {
          navigate("/organization-suspended", {
            state: {
              status: err.code === "organization_archived" ? "archived" : "suspended",
            },
          })
          return
        }

        if (err.message.toLowerCase().includes("verify")) {
          navigate("/verify-email", {
            state: {
              email: email.trim().toLowerCase(),
              notice: err.message,
            },
          })
          return
        }

        setError(err.message)
      } else {
        setError("Invalid email or password.")
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-canvas text-white">

      <div className="flex min-h-screen">

        <div className="hidden flex-1 items-center justify-center border-r border-white/10 bg-surface-sunken lg:flex">

          <div className="max-w-xl px-14">

            <div className="mb-8 flex items-center gap-3">

              <div className="rounded-xl bg-brand-500/10 p-3">

                <ShieldCheck
                  size={32}
                  className="text-brand-400"
                />

              </div>

              <div>

                <h1 className="text-3xl font-bold">

                  Sentinel
                  <span className="text-brand-400">
                    X
                  </span>

                </h1>

                <p className="text-sm text-fg-muted">
                  AI-Powered Security Operations
                </p>

              </div>

            </div>

            <h2 className="text-5xl font-semibold leading-tight">

              Security operations,
              <br />

              <span className="text-brand-400">
                simplified.
              </span>

            </h2>

            <p className="mt-6 text-base leading-7 text-fg-subtle">

              Monitor security events, investigate
              incidents, analyze threats and manage
              remediation from a centralized security
              operations platform.

            </p>

          </div>

        </div>

        <div className="flex w-full items-center justify-center px-6 lg:w-[520px]">

          <div className="w-full max-w-md">

            <div className="rounded-2xl border border-white/10 bg-surface p-8 shadow-2xl">

              <h2 className="text-2xl font-semibold">
                Welcome back
              </h2>

              <p className="mt-2 text-sm text-fg-muted">
                Sign in to SentinelX.
              </p>

              <form
                onSubmit={handleLogin}
                className="mt-8 space-y-5"
              >

                <div>

                  <label className="mb-2 block text-sm text-fg-secondary">
                    Email address
                  </label>

                  <input
                    type="email"
                    value={email}
                    onChange={(e) =>
                      setEmail(
                        e.target.value,
                      )
                    }
                    placeholder="you@example.com"
                    className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
                    required
                  />

                </div>

                <div>

                  <div className="mb-2 flex items-center justify-between">

                    <label className="text-sm text-fg-secondary">
                      Password
                    </label>

                    <button
                      type="button"
                      onClick={() =>
                        navigate("/forgot-password")
                      }
                      className="text-xs text-brand-400 hover:text-brand-300"
                    >
                      Forgot password?
                    </button>

                  </div>

                  <div className="relative">

                    <input
                      type={
                        showPassword
                          ? "text"
                          : "password"
                      }
                      value={password}
                      onChange={(e) =>
                        setPassword(
                          e.target.value,
                        )
                      }
                      placeholder="Enter password"
                      className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 pr-12 outline-none focus:border-brand-500"
                      required
                    />

                    <button
                      type="button"
                      onClick={() =>
                        setShowPassword(
                          !showPassword,
                        )
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted"
                    >

                      {showPassword
                        ? <EyeOff size={18} />
                        : <Eye size={18} />
                      }

                    </button>

                  </div>

                </div>

                {error && (

                  <div className="rounded-xl border border-danger/20 bg-danger/10 p-3 text-sm text-danger-fg">
                    {error}
                  </div>

                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full rounded-xl bg-brand-600 py-3 font-medium transition hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {submitting ? "Signing in..." : "Sign in"}
                </button>

              </form>

              <div className="mt-6 text-center text-sm text-fg-muted">

                Need an account?{" "}

                <button
                  onClick={() =>
                    navigate(
                      "/register",
                    )
                  }
                  className="text-brand-400 hover:text-brand-300"
                >
                  Register
                </button>

              </div>

            </div>

          </div>

        </div>

      </div>

    </div>
  )
}

export default Login
