import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Bell } from "lucide-react"

import IconButton from "../ui/IconButton"
import DropdownMenu, { type DropdownMenuItem } from "../ui/DropdownMenu"
import { apiListNotifications, apiMarkAllNotificationsRead, apiMarkNotificationRead, type NotificationRow } from "../../lib/notifications"
import { notificationEventLabel } from "../../lib/notifications"

const POLL_MS = 30_000

/** The top bar's notification bell: a live unread count (polled) and a
 * dropdown of the newest notifications. Clicking one marks it read and
 * navigates to the full page; "Mark all read" clears the badge. Uses the
 * existing DropdownMenu/IconButton primitives only. */
function NotificationBell() {
  const navigate = useNavigate()
  const [unread, setUnread] = useState(0)
  const [rows, setRows] = useState<NotificationRow[]>([])
  const [failed, setFailed] = useState(false)

  const load = useCallback(async function load() {
    try {
      const res = await apiListNotifications({ limit: 8 })
      setRows(res.notifications)
      setUnread(res.unread_count)
      setFailed(false)
    } catch (err) {
      // The bell stays quiet when the backend is down -- the page itself
      // surfaces errors; the poll just retries.
      setFailed(true)
    }
  }, [])

  useEffect(() => {
    void load()
    const interval = setInterval(() => void load(), POLL_MS)
    return () => clearInterval(interval)
  }, [load])

  async function open(row: NotificationRow) {
    if (!row.read_at) {
      try {
        await apiMarkNotificationRead(row.id)
      } catch {
        // read-state is best-effort in the dropdown
      }
    }
    void load()
    navigate("/notifications")
  }

  const items: DropdownMenuItem[] = failed
    ? [{ key: "error", label: "Notifications unavailable", onSelect: () => {}, disabled: true }]
    : rows.length === 0
      ? [{ key: "empty", label: "No notifications", onSelect: () => {}, disabled: true }]
      : [
          ...rows.slice(0, 6).map<DropdownMenuItem>((row) => ({
            key: row.id,
            label: (
              <span className="flex min-w-0 flex-col">
                <span className={`truncate text-xs ${row.read_at ? "font-normal text-fg-muted" : "font-semibold text-fg-primary"}`}>
                  {row.title}
                </span>
                <span className="truncate text-[11px] text-fg-faint">{notificationEventLabel(row.template_key)}</span>
              </span>
            ),
            onSelect: () => void open(row),
          })),
          {
            key: "mark-all",
            label: <span className="text-xs text-brand-400">Mark all read</span>,
            onSelect: () => {
              void apiMarkAllNotificationsRead()
                .then(load)
                .catch(() => {})
            },
          },
        ]

  return (
    <DropdownMenu
      label="Notifications"
      align="right"
      items={items}
      trigger={
        <span className="relative inline-flex">
          <IconButton icon={Bell} label={`Notifications${unread > 0 ? ` (${unread} unread)` : ""}`} onClick={() => void load()} />
          {unread > 0 && (
            <span
              aria-hidden="true"
              className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-pill bg-critical px-1 text-[10px] font-bold text-fg-primary"
            >
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </span>
      }
    />
  )
}

export default NotificationBell
