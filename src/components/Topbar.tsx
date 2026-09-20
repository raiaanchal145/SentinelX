import {
  Bell,
  LogOut,
  Search,
} from "lucide-react"

import { useNavigate } from "react-router-dom"

function Topbar() {
  const navigate = useNavigate()

  const name =
    localStorage.getItem(
      "sentinelx_name",
    ) || "User"

  const role =
    localStorage.getItem(
      "sentinelx_role",
    ) || ""

  const logout = () => {
    localStorage.removeItem(
      "sentinelx_logged_in",
    )

    localStorage.removeItem(
      "sentinelx_role",
    )

    localStorage.removeItem(
      "sentinelx_name",
    )

    navigate("/login")
  }

  const formattedRole =
    role === "super_admin"
      ? "Super Administrator"
      : role === "soc_analyst"
        ? "SOC Analyst"
        : "IT / Developer"

  return (
    <header className="flex h-20 items-center justify-between border-b border-white/10 bg-surface-sunken px-6">

      <div className="hidden items-center gap-3 rounded-xl border border-white/10 bg-surface px-4 py-2 md:flex">

        <Search
          size={18}
          className="text-fg-muted"
        />

        <input
          placeholder="Search..."
          className="w-64 bg-transparent text-sm text-white outline-none placeholder:text-fg-faint"
        />

      </div>

      <div className="ml-auto flex items-center gap-4">

        <button className="rounded-xl border border-white/10 bg-surface p-2.5 text-fg-subtle transition hover:text-brand-400">

          <Bell size={19} />

        </button>

        <div className="hidden text-right sm:block">

          <p className="text-sm font-medium text-white">
            {name}
          </p>

          <p className="text-xs text-fg-muted">
            {formattedRole}
          </p>

        </div>

        <button
          onClick={logout}
          className="rounded-xl border border-danger/20 bg-danger/5 p-2.5 text-danger-fg transition hover:bg-danger/10"
        >

          <LogOut size={18} />

        </button>

      </div>

    </header>
  )
}

export default Topbar