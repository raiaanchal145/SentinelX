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

import { apiRegister } from "../lib/api"

// Same allow-lists the backend enforces.
const NAME_PATTERN = /^[A-Za-z\s'-]+$/
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

function Register() {
  const navigate = useNavigate()

  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] =
    useState("")

  const [confirmPassword, setConfirmPassword] =
    useState("")

  const [showPassword, setShowPassword] =
    useState(false)

  const [showConfirmPassword, setShowConfirmPassword] =
    useState(false)

  const [role, setRole] =
    useState("soc_analyst")

  const [error, setError] =
    useState("")

  const [success, setSuccess] =
    useState("")

  const [submitting, setSubmitting] =
    useState(false)

  const handleRegister = async (
    e: FormEvent,
  ) => {
    e.preventDefault()

    setError("")
    setSuccess("")

    if (
      !name.trim() ||
      !email.trim() ||
      !password.trim() ||
      !confirmPassword.trim()
    ) {
      setError(
        "Please complete all fields.",
      )
      return
    }

    if (password.length < 6) {
      setError(
        "Password must contain at least 6 characters.",
      )
      return
    }

    if (password !== confirmPassword) {
      setError(
        "Passwords do not match.",
      )
      return
    }

    if (!NAME_PATTERN.test(name.trim())) {
      setError(
        "Name can only contain letters, spaces, apostrophes and hyphens.",
      )
      return
    }

    if (!EMAIL_PATTERN.test(email.trim())) {
      setError(
        "Please enter a valid email address (letters, numbers, and . _ % + - only).",
      )
      return
    }

    setSubmitting(true)

    try {
      const registeredEmail = email.trim().toLowerCase()

      await apiRegister(
        name.trim(),
        registeredEmail,
        password,
        role,
      )

      setSuccess(
        "Verification code sent. Check your email to finish creating your account...",
      )

      setTimeout(() => {
        navigate("/verify-email", {
          state: { email: registeredEmail },
        })
      }, 1000)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not create the account. Please try again.",
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
              Create Account
            </h1>

            <p className="text-sm text-fg-muted">
              Join SentinelX
            </p>

          </div>

        </div>

        <form
          onSubmit={handleRegister}
          className="space-y-5"
        >

          <div>

            <label className="mb-2 block text-sm">
              Full Name
            </label>

            <input
              value={name}
              onChange={(e) =>
                setName(
                  e.target.value,
                )
              }
              className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
              required
            />

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Email
            </label>

            <input
              type="email"
              value={email}
              onChange={(e) =>
                setEmail(
                  e.target.value,
                )
              }
              className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
              required
            />

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Password
            </label>

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
                tabIndex={-1}
              >

                {showPassword
                  ? <EyeOff size={18} />
                  : <Eye size={18} />
                }

              </button>

            </div>

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Confirm Password
            </label>

            <div className="relative">

              <input
                type={
                  showConfirmPassword
                    ? "text"
                    : "password"
                }
                value={confirmPassword}
                onChange={(e) =>
                  setConfirmPassword(
                    e.target.value,
                  )
                }
                className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 pr-12 outline-none focus:border-brand-500"
                required
              />

              <button
                type="button"
                onClick={() =>
                  setShowConfirmPassword(
                    !showConfirmPassword,
                  )
                }
                className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted"
                tabIndex={-1}
              >

                {showConfirmPassword
                  ? <EyeOff size={18} />
                  : <Eye size={18} />
                }

              </button>

            </div>

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Role
            </label>

            <select
              value={role}
              onChange={(e) =>
                setRole(
                  e.target.value,
                )
              }
              className="w-full rounded-xl border border-white/10 bg-surface-sunken px-4 py-3 outline-none focus:border-brand-500"
            >

              <option value="soc_analyst">
                SOC Analyst
              </option>

              <option value="it_developer">
                IT / Developer
              </option>

            </select>

            <p className="mt-2 text-xs text-fg-muted">
              Super Administrator access is
              automatically assigned only to the
              three configured administrator emails.
            </p>

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
            {submitting ? "Sending code..." : "Create Account"}
          </button>

        </form>

        <div className="mt-6 text-center text-sm text-fg-muted">

          Already have an account?{" "}

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

export default Register
