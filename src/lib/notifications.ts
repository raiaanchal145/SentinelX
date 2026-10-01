// ---------------------------------------------------------------------------
// Notifications (P16): the caller's in-app feed, read state, and the
// per-event channel preferences. docs/API_CONTRACT.md "Notifications".
// ---------------------------------------------------------------------------

import { request } from "./api"

export type NotificationRow = {
  id: string
  title: string
  body: string | null
  template_key: string | null
  related_type: string | null
  related_id: string | null
  read_at: string | null
  created_at: string | null
}

export type NotificationListResponse = {
  notifications: NotificationRow[]
  unread_count: number
  next_cursor: string | null
}

export type NotificationPreferenceRow = {
  event_key: string
  in_app: boolean
  email: boolean
}

export function apiListNotifications(params: { unread_only?: boolean; cursor?: string; limit?: number } = {}) {
  const query = new URLSearchParams()
  if (params.unread_only) query.set("unread_only", "true")
  if (params.cursor) query.set("cursor", params.cursor)
  if (params.limit) query.set("limit", String(params.limit))
  const qs = query.toString()
  return request<NotificationListResponse>(`/notifications${qs ? `?${qs}` : ""}`)
}

export function apiMarkNotificationRead(notificationId: string) {
  return request<NotificationRow>(`/notifications/${notificationId}/read`, { method: "POST" })
}

export function apiMarkAllNotificationsRead() {
  return request<{ updated: number }>("/notifications/read-all", { method: "POST" })
}

export function apiGetNotificationPreferences() {
  return request<{ preferences: NotificationPreferenceRow[] }>("/notifications/preferences")
}

export function apiPutNotificationPreferences(preferences: NotificationPreferenceRow[]) {
  return request<{ updated: number; preferences: NotificationPreferenceRow[] }>("/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify({ preferences }),
  })
}

/** Human labels for the event keys (the preferences page + feed icons).
 * Keep in sync with app/notifications.py EVENTS. */
export const NOTIFICATION_EVENT_LABELS: Record<string, string> = {
  "ticket.assigned": "Ticket assigned to me",
  "ticket.needs_verification": "Ticket awaits verification",
  "ticket.verification_failed": "Ticket failed verification",
  "ticket.reopened": "Ticket reopened",
  "ticket.sla_at_risk": "Ticket SLA at risk",
  "ticket.sla_breached": "Ticket SLA breached",
  "approval.requested": "Approval requested",
  "approval.decided": "Approval decided",
  "invitation.resend": "Invitation re-sent",
  "alert.high_severity": "High-severity alert",
}

export function notificationEventLabel(key: string | null): string {
  if (!key) return "Notification"
  return NOTIFICATION_EVENT_LABELS[key] ?? key
}
