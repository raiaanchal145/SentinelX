import { AlertTriangle } from "lucide-react"
import type { ConnectivityStatus } from "../../hooks/useHealthStatus"

function ConnectivityBanner({ status }: { status: ConnectivityStatus }) {
  if (status === "operational") return null

  const message =
    status === "offline"
      ? "Cannot reach the SentinelX server - data may be out of date."
      : "The SentinelX server is responding slowly - some data may be delayed."

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex items-center gap-2 border-b border-medium/30 bg-medium/10 px-4 py-2 text-sm text-medium-fg"
    >
      <AlertTriangle size={16} aria-hidden="true" />
      {message}
    </div>
  )
}

export default ConnectivityBanner
