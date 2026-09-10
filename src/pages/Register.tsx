import {
  FormEvent,
  useState,
} from "react"

import {
  ShieldCheck,
} from "lucide-react"

import { useNavigate } from "react-router-dom"

import { apiRegister } from "../lib/api"

function Register() {
  const navigate = useNavigate()

  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] =
    useState("")

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
      !password.trim()
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

    setSubmitting(true)

    try {
      const user = await apiRegister(
        name.trim(),
        email.trim().toLowerCase(),
        password,
        role,
      )

      setSuccess(
        user.role === "super_admin"
          ? "Super Administrator account created successfully."
          : "Account created successfully.",
      )

      setTimeout(() => {
        navigate("/login")
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
    <div className="flex min-h-screen items-center justify-center bg-[#021325] px-6 text-white">

      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0b1f33] p-8">

        <div className="mb-8 flex items-center gap-3">

          <div className="rounded-xl bg-blue-500/10 p-3">

            <ShieldCheck
              className="text-blue-400"
              size={28}
            />

          </div>

          <div>

            <h1 className="text-2xl font-bold">
              Create Account
            </h1>

            <p className="text-sm text-slate-500">
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
              className="w-full rounded-xl border border-white/10 bg-[#061727] px-4 py-3 outline-none focus:border-blue-500"
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
              className="w-full rounded-xl border border-white/10 bg-[#061727] px-4 py-3 outline-none focus:border-blue-500"
              required
            />

          </div>

          <div>

            <label className="mb-2 block text-sm">
              Password
            </label>

            <input
              type="password"
              value={password}
              onChange={(e) =>
                setPassword(
                  e.target.value,
                )
              }
              className="w-full rounded-xl border border-white/10 bg-[#061727] px-4 py-3 outline-none focus:border-blue-500"
              required
            />

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
              className="w-full rounded-xl border border-white/10 bg-[#061727] px-4 py-3 outline-none focus:border-blue-500"
            >

              <option value="soc_analyst">
                SOC Analyst
              </option>

              <option value="it_developer">
                IT / Developer
              </option>

            </select>

            <p className="mt-2 text-xs text-slate-500">
              Super Administrator access is
              automatically assigned only to the
              three configured administrator emails.
            </p>

          </div>

          {error && (
            <div className="rounded-xl bg-red-500/10 p-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {success && (
            <div className="rounded-xl bg-green-500/10 p-3 text-sm text-green-400">
              {success}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-blue-600 py-3 font-medium hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Creating account..." : "Create Account"}
          </button>

        </form>

        <div className="mt-6 text-center text-sm text-slate-500">

          Already have an account?{" "}

          <button
            onClick={() =>
              navigate("/login")
            }
            className="text-blue-400"
          >
            Sign in
          </button>

        </div>

      </div>

    </div>
  )
}

export default Register
