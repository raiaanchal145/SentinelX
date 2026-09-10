import {
  FormEvent,
  useState,
} from "react"

import {
  Eye,
  EyeOff,
  ShieldCheck,
} from "lucide-react"

import { useNavigate } from "react-router-dom"

import { apiLogin } from "../lib/api"

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

      if (user.role === "super_admin") {
        navigate("/admin")
      } else if (user.role === "organization_admin") {
        navigate("/organization-dashboard")
      } else if (user.role === "soc_analyst") {
        navigate("/soc-dashboard")
      } else if (user.role === "it_developer") {
        navigate("/it-dashboard")
      } else {
        // auditor and any future roles without a dedicated dashboard yet
        navigate("/soc-dashboard")
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Invalid email or password.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#021325] text-white">

      <div className="flex min-h-screen">

        <div className="hidden flex-1 items-center justify-center border-r border-white/10 bg-[#061727] lg:flex">

          <div className="max-w-xl px-14">

            <div className="mb-8 flex items-center gap-3">

              <div className="rounded-xl bg-blue-500/10 p-3">

                <ShieldCheck
                  size={32}
                  className="text-blue-400"
                />

              </div>

              <div>

                <h1 className="text-3xl font-bold">

                  Sentinel
                  <span className="text-blue-400">
                    X
                  </span>

                </h1>

                <p className="text-sm text-slate-500">
                  AI-Powered Security Operations
                </p>

              </div>

            </div>

            <h2 className="text-5xl font-semibold leading-tight">

              Security operations,
              <br />

              <span className="text-blue-400">
                simplified.
              </span>

            </h2>

            <p className="mt-6 text-base leading-7 text-slate-400">

              Monitor security events, investigate
              incidents, analyze threats and manage
              remediation from a centralized security
              operations platform.

            </p>

          </div>

        </div>

        <div className="flex w-full items-center justify-center px-6 lg:w-[520px]">

          <div className="w-full max-w-md">

            <div className="rounded-2xl border border-white/10 bg-[#0b1f33] p-8 shadow-2xl">

              <h2 className="text-2xl font-semibold">
                Welcome back
              </h2>

              <p className="mt-2 text-sm text-slate-500">
                Sign in to SentinelX.
              </p>

              <form
                onSubmit={handleLogin}
                className="mt-8 space-y-5"
              >

                <div>

                  <label className="mb-2 block text-sm text-slate-300">
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
                    className="w-full rounded-xl border border-white/10 bg-[#061727] px-4 py-3 outline-none focus:border-blue-500"
                    required
                  />

                </div>

                <div>

                  <label className="mb-2 block text-sm text-slate-300">
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
                      placeholder="Enter password"
                      className="w-full rounded-xl border border-white/10 bg-[#061727] px-4 py-3 pr-12 outline-none focus:border-blue-500"
                      required
                    />

                    <button
                      type="button"
                      onClick={() =>
                        setShowPassword(
                          !showPassword,
                        )
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500"
                    >

                      {showPassword
                        ? <EyeOff size={18} />
                        : <Eye size={18} />
                      }

                    </button>

                  </div>

                </div>

                {error && (

                  <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-400">
                    {error}
                  </div>

                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full rounded-xl bg-blue-600 py-3 font-medium transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {submitting ? "Signing in..." : "Sign in"}
                </button>

              </form>

              <div className="mt-6 text-center text-sm text-slate-500">

                Need an account?{" "}

                <button
                  onClick={() =>
                    navigate(
                      "/register",
                    )
                  }
                  className="text-blue-400 hover:text-blue-300"
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
