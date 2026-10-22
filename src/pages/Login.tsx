import {
  type FormEvent,
  useState,
} from "react"

import {
  Eye,
  EyeOff,
  KeyRound,
  ShieldCheck,
} from "lucide-react"

import { useNavigate } from "react-router-dom"

import { apiLogin, apiLogin2fa, ApiError } from "../lib/api"
import { homePathFor } from "../lib/auth"

// Same allow-list the backend enforces: only the standard set of
// characters a real email address can contain.
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

function Login() {
  const navigate = useNavigate()

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [infoMessage, setInfoMessage] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // Two-Factor Authentication state
  const [step, setStep] = useState<"credentials" | "2fa">("credentials")
  const [tempToken, setTempToken] = useState("")
  const [twoFactorCode, setTwoFactorCode] = useState("")

  const handleLogin = async (
    e: FormEvent<HTMLFormElement>,
  ) => {
    e.preventDefault()
    setError("")
    setInfoMessage("")

    if (!EMAIL_PATTERN.test(email)) {
      setError(
        "Please enter a valid email address (letters, numbers, and . _ % + - only).",
      )
      return
    }

    setSubmitting(true)

    try {
      const loginRes = await apiLogin(email, password)

      if (loginRes.requires_2fa && loginRes.temp_token) {
        setTempToken(loginRes.temp_token)
        setStep("2fa")
        setInfoMessage(loginRes.message || "A security verification code has been sent to your email.")
        return
      }

      if (!loginRes.access_token || !loginRes.user) {
        setError("Invalid response from server. Please try again.")
        return
      }

      completeLogin(loginRes.access_token, loginRes.user)
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

  const handle2faSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError("")

    const code = twoFactorCode.trim()
    if (!code) {
      setError("Please enter the 6-digit verification code.")
      return
    }

    setSubmitting(true)
    try {
      const loginRes = await apiLogin2fa(tempToken, code)
      if (!loginRes.access_token || !loginRes.user) {
        setError("Invalid response from server. Please try again.")
        return
      }
      completeLogin(loginRes.access_token, loginRes.user)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError("Invalid or expired verification code.")
      }
    } finally {
      setSubmitting(false)
    }
  }

  const completeLogin = (token: string, user: { role: string; name: string; email: string; account_type: string }) => {
    localStorage.setItem("sentinelx_token", token)
    localStorage.setItem("sentinelx_logged_in", "true")
    localStorage.setItem("sentinelx_role", user.role)
    localStorage.setItem("sentinelx_name", user.name)
    localStorage.setItem("sentinelx_email", user.email)
    localStorage.setItem("sentinelx_account_type", user.account_type)

    window.dispatchEvent(new Event("sentinelx_auth_change"))
    navigate(homePathFor(user.role))
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
              {step === "credentials" ? (
                <>
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
                </>
              ) : (
                <>
                  <div className="mb-4 inline-flex rounded-xl bg-brand-500/10 p-3 text-brand-400">
                    <KeyRound size={26} aria-hidden="true" />
                  </div>
                  <h2 className="text-2xl font-semibold">
                    Two-Factor Authentication
                  </h2>

                  <p className="mt-2 text-sm text-fg-muted">
                    {infoMessage || "Enter the 6-digit security code sent to your email to verify your identity."}
                  </p>

                  <form
                    onSubmit={handle2faSubmit}
                    className="mt-6 space-y-5"
                  >
                    <div>
                      <label className="mb-2 block text-sm text-fg-secondary">
                        Security verification code
                      </label>

                      <input
                        type="text"
                        maxLength={6}
                        pattern="[0-9]{6}"
                        inputMode="numeric"
                        autoFocus
                        value={twoFactorCode}
                        onChange={(e) =>
                          setTwoFactorCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                        }
                        placeholder="123456"
                        className="w-full text-center text-2xl tracking-[0.3em] font-mono rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
                        required
                      />
                    </div>

                    {error && (
                      <div className="rounded-xl border border-danger/20 bg-danger/10 p-3 text-sm text-danger-fg">
                        {error}
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={submitting || twoFactorCode.trim().length !== 6}
                      className="w-full rounded-xl bg-brand-600 py-3 font-medium transition hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {submitting ? "Verifying..." : "Verify and Sign In"}
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setStep("credentials")
                        setError("")
                        setTwoFactorCode("")
                      }}
                      className="w-full rounded-xl border border-white/10 bg-surface-sunken py-2.5 text-sm font-medium text-fg-subtle hover:text-fg-primary hover:bg-surface-hover"
                    >
                      Back to login
                    </button>
                  </form>
                </>
              )}

              <div className="mt-6 text-center text-sm text-fg-muted">

                Access to SentinelX is by invitation. Contact your organization administrator.

              </div>

            </div>

          </div>

        </div>

      </div>

    </div>
  )
}

export default Login
