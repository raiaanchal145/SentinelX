import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Clock, Laptop, Monitor, RefreshCw } from "lucide-react"

import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { apiGetDevicesSummary, type DevicesSummary } from "../../../lib/devicesApi"

export default function AgentHealthWidget() {
  const [summary, setSummary] = useState<DevicesSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  function load() {
    setLoading(true)
    setError("")
    apiGetDevicesSummary()
      .then(setSummary)
      .catch(() => setError("Device health metrics unavailable"))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <section aria-label="Device and agent health" className="rounded-card border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-fg-primary flex items-center gap-2">
          <Monitor size={16} className="text-brand-400" />
          Agent &amp; Device Health
        </h2>
        <IconButton icon={RefreshCw} label="Refresh agent health" onClick={load} />
      </div>

      {loading && !summary ? (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : error ? (
        <div className="mt-3 text-xs text-danger">{error}</div>
      ) : !summary || summary.total === 0 ? (
        <div className="mt-3 rounded-control border border-dashed border-line bg-surface-sunken p-3 text-xs text-fg-muted flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            <Laptop size={14} />
            No endpoint agents enrolled yet.
          </span>
          <Link to="/devices" className="text-brand hover:underline font-medium">
            Enroll device
          </Link>
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-control bg-emerald-500/10 border border-emerald-500/20 p-2">
              <div className="flex items-center justify-center gap-1 text-[11px] text-emerald-400 font-medium">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                Connected
              </div>
              <div className="mt-1 text-lg font-bold text-emerald-400">{summary.connected}</div>
            </div>

            <div className="rounded-control bg-amber-500/10 border border-amber-500/20 p-2">
              <div className="flex items-center justify-center gap-1 text-[11px] text-amber-400 font-medium">
                <Clock size={12} />
                Stale
              </div>
              <div className="mt-1 text-lg font-bold text-amber-400">{summary.stale}</div>
            </div>

            <div className="rounded-control bg-surface-sunken border border-line p-2">
              <div className="text-[11px] text-fg-muted font-medium">Offline</div>
              <div className="mt-1 text-lg font-bold text-fg-muted">{summary.offline}</div>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs pt-1 border-t border-line/50">
            <span className="text-fg-muted">
              {summary.total} total endpoint{summary.total === 1 ? "" : "s"}
              {summary.pending_consent > 0 ? ` (${summary.pending_consent} pending consent)` : ""}
            </span>
            <Link to="/devices" className="text-brand hover:underline font-medium">
              View all &rarr;
            </Link>
          </div>
        </div>
      )}
    </section>
  )
}
