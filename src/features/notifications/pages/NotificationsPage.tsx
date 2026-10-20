import { useCallback, useEffect, useMemo, useState } from "react"
import { RefreshCw } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import IconButton from "../../../components/ui/IconButton"
import { ApiError } from "../../../lib/api"
import {
  apiListNotifications,
  apiMarkAllNotificationsRead,
  apiMarkNotificationRead,
  notificationEventLabel,
  type NotificationRow,
} from "../../../lib/notifications"

const PAGE_SIZE = 30

const selectClass =
  "rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-secondary focus:border-brand-500 focus:outline-none"

function timeAgo(iso: string | null): string {
  if (!iso) return "--"
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/** The full notifications page (the bell's dropdown links here):
 * unread-first feed with filters, per-row mark-read, and read-all. */
function NotificationsPage() {
  const [rows, setRows] = useState<NotificationRow[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [eventKey, setEventKey] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListNotifications({ unread_only: unreadOnly || undefined, limit: PAGE_SIZE })
        const filtered = eventKey ? res.notifications.filter((n) => n.template_key === eventKey) : res.notifications
        setRows(filtered)
        setUnreadCount(res.unread_count)
        setNextCursor(res.next_cursor)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load notifications.")
      } finally {
        setLoading(false)
      }
    },
    [unreadOnly],
  )

  useEffect(() => {
    load()
  }, [load])

  const eventOptions = useMemo(() => {
    const keys = Array.from(new Set(rows.map((r) => r.template_key).filter((k): k is string => Boolean(k))))
    return keys.sort()
  }, [rows])

  async function markRead(row: NotificationRow) {
    if (!row.read_at) {
      try {
        await apiMarkNotificationRead(row.id)
        load()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not mark the notification read.")
      }
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Notifications</h1>
          <p className="mt-0.5 text-xs text-fg-muted">
            {unreadCount > 0 ? `${unreadCount} unread.` : "Everything is read."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {unreadCount > 0 && (
            <Button variant="secondary" onClick={() => void apiMarkAllNotificationsRead().then(load).catch(() => setError("Could not mark all read."))}>
              Mark all read
            </Button>
          )}
          <IconButton icon={RefreshCw} label="Refresh notifications" onClick={load} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-3">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
            className="accent-brand-500"
          />
          Unread only
        </label>
        <select aria-label="Filter by event type" value={eventKey} onChange={(e) => setEventKey(e.target.value)} className={selectClass}>
          <option value="">All events</option>
          {eventOptions.map((key) => (
            <option key={key} value={key}>
              {notificationEventLabel(key)}
            </option>
          ))}
        </select>
        {(unreadOnly || eventKey) && (
          <button
            type="button"
            onClick={() => {
              setUnreadOnly(false)
              setEventKey("")
            }}
            className="text-xs text-brand-400 hover:text-brand-300"
          >
            Clear filters
          </button>
        )}
      </div>

      {error ? (
        <div className="rounded-card border border-danger-fg/30 bg-surface p-6 text-center">
          <p className="text-sm text-danger-fg">{error}</p>
          <button type="button" onClick={load} className="mt-3 rounded-control border border-line px-3 py-1.5 text-xs text-fg-secondary hover:border-line-strong">
            Try again
          </button>
        </div>
      ) : loading ? (
        <div className="space-y-2" role="status" aria-label="Loading notifications">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-control bg-surface-hover" style={{ animationDuration: "1.6s" }} />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          title={unreadOnly ? "No unread notifications" : "No notifications"}
          description="You will hear from us here when your tickets, approvals and alerts need attention."
        />
      ) : (
        <ul className="divide-y divide-line/60 rounded-card border border-line bg-surface">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => void markRead(row)}
                className={`flex w-full flex-col gap-0.5 p-3 text-left transition hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400 ${
                  row.read_at ? "" : "bg-brand-500/5"
                }`}
              >
                <span className="flex flex-wrap items-center gap-2">
                  {!row.read_at && <span aria-label="Unread" className="h-1.5 w-1.5 rounded-full bg-brand-400" />}
                  <span className={`text-sm ${row.read_at ? "text-fg-secondary" : "font-semibold text-fg-primary"}`}>{row.title}</span>
                  <Badge tone="neutral">{notificationEventLabel(row.template_key)}</Badge>
                  <span className="ml-auto text-[11px] text-fg-faint">{timeAgo(row.created_at)}</span>
                </span>
                {row.body && <span className="text-xs text-fg-muted">{row.body}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {!loading && !error && nextCursor && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={async () => {
              try {
                const res = await apiListNotifications({ unread_only: unreadOnly || undefined, cursor: nextCursor, limit: PAGE_SIZE })
                setRows((prev) => {
                  const merged = [...prev, ...res.notifications.filter((n) => !prev.some((p) => p.id === n.id))]
                  return eventKey ? merged.filter((n) => n.template_key === eventKey) : merged
                })
                setNextCursor(res.next_cursor)
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Could not load more notifications.")
              }
            }}
            className="rounded-control border border-line bg-surface px-4 py-2 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  )
}

export default NotificationsPage
