import { useEffect, useMemo, useState } from "react"

import Drawer from "../../../components/ui/Drawer"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import { useToast } from "../../../components/ui/Toast"
import { ApiError, apiGetEvent, type EventRow } from "../../../lib/api"
import { RefreshCw } from "lucide-react"

/**
 * The normalized + raw view of one security event. Extracted from
 * SocEvents so the alert drawer can open a supporting event in place
 * (no navigation) -- both read the same GET /events/{id} endpoint, so
 * the drawer is self-fetching: hand it an event id or null (closed).
 */
function EventDetailDrawer({ eventId, onClose }: { eventId: string | null; onClose: () => void }) {
  const [event, setEvent] = useState<EventRow | null>(null)
  const [error, setError] = useState("")
  const { show: showToast } = useToast()

  useEffect(() => {
    if (!eventId) {
      setEvent(null)
      setError("")
      return
    }
    setEvent(null)
    setError("")
    apiGetEvent(eventId)
      .then(setEvent)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load this event."))
  }, [eventId])

  const rawJson = useMemo(() => (event?.raw_data != null ? JSON.stringify(event.raw_data, null, 2) : ""), [event])

  async function copyRaw() {
    try {
      await navigator.clipboard.writeText(rawJson)
      showToast("Raw JSON copied.", { tone: "success" })
    } catch {
      showToast("Could not copy to the clipboard.", { tone: "danger" })
    }
  }

  const normalized = event?.normalized_data as Record<string, unknown> | null | undefined
  const asset = normalized?.asset as Record<string, unknown> | null | undefined

  return (
    <Drawer open={eventId !== null} onClose={onClose} title="Event detail" side="right" widthClassName="w-[480px] max-w-[95vw]">
      {error ? (
        <div className="p-4">
          <p className="text-xs text-danger-fg">{error}</p>
          <IconButton icon={RefreshCw} label="Retry" onClick={() => eventId && apiGetEvent(eventId).then(setEvent).catch(() => undefined)} className="mt-3" />
        </div>
      ) : !event ? (
        <div className="space-y-3 p-4">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton count={4} className="h-4 w-full" />
        </div>
      ) : (
        <div className="space-y-5 p-4 text-sm">
          <div className="flex items-center justify-between gap-2">
            <SeverityBadge severity={event.severity as "critical" | "high" | "medium" | "low" | "info"} showIcon />
            <Badge tone="neutral">{event.event_type}</Badge>
          </div>

          <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-xs">
            <dt className="text-fg-muted">Occurred</dt>
            <dd className="text-fg-primary">{event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "--"}</dd>
            <dt className="text-fg-muted">Ingested</dt>
            <dd className="text-fg-primary">{event.ingested_at ? new Date(event.ingested_at).toLocaleString() : "--"}</dd>
            <dt className="text-fg-muted">Host</dt>
            <dd className="text-fg-primary">{String(normalized?.host ?? "--")}</dd>
            <dt className="text-fg-muted">User</dt>
            <dd className="text-fg-primary">{event.username ?? "--"}</dd>
            <dt className="text-fg-muted">IP</dt>
            <dd className="text-fg-primary">{event.source_ip ?? "--"}</dd>
            <dt className="text-fg-muted">Process</dt>
            <dd className="text-fg-primary">{String(normalized?.process ?? "--")}</dd>
            <dt className="text-fg-muted">Source type</dt>
            <dd className="text-fg-primary">{String(normalized?.source_type ?? "--")}</dd>
            <dt className="text-fg-muted">Asset</dt>
            <dd className="text-fg-primary">
              {asset?.id
                ? `${String(asset.criticality ?? "unknown")} criticality${asset.owner ? ` · owner ${String(asset.owner)}` : ""}`
                : "--"}
            </dd>
            <dt className="text-fg-muted">Message</dt>
            <dd className="break-words text-fg-primary">{String(normalized?.message ?? "--")}</dd>
          </dl>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-fg-primary">Raw JSON</h3>
              <button
                type="button"
                onClick={copyRaw}
                className="rounded-control border border-line px-2 py-1 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
              >
                Copy
              </button>
            </div>
            <pre className="max-h-72 overflow-auto rounded-control border border-line bg-surface-sunken p-3 text-[11px] leading-relaxed text-fg-secondary">
              {rawJson || "--"}
            </pre>
          </div>
        </div>
      )}
    </Drawer>
  )
}

export default EventDetailDrawer
