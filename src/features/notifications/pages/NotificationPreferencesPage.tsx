import { useCallback, useEffect, useState } from "react"

import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Skeleton from "../../../components/ui/Skeleton"
import { ApiError } from "../../../lib/api"
import {
  apiGetNotificationPreferences,
  apiPutNotificationPreferences,
  notificationEventLabel,
  type NotificationPreferenceRow,
} from "../../../lib/notifications"

/** Per-event channel switches (docs/API_CONTRACT.md "Notifications").
 * Defaults are all-on and opt-out: a switch the user never touched
 * resolves to ON; saving only stores the deviations. Email delivery
 * failures never block the triggering action -- they retry in the
 * worker and are logged. */
function NotificationPreferencesPage() {
  const [prefs, setPrefs] = useState<NotificationPreferenceRow[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)

  const load = useCallback(async function load() {
    try {
      const res = await apiGetNotificationPreferences()
      setPrefs(res.preferences)
      setDirty(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your preferences.")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function toggle(key: string, channel: "in_app" | "email") {
    if (!prefs) return
    setPrefs(prefs.map((p) => (p.event_key === key ? { ...p, [channel]: !p[channel] } : p)))
    setDirty(true)
    setSaved(false)
  }

  async function save() {
    if (!prefs) return
    setSaving(true)
    setError("")
    try {
      const res = await apiPutNotificationPreferences(prefs)
      setPrefs(res.preferences)
      setDirty(false)
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your preferences.")
    } finally {
      setSaving(false)
    }
  }

  if (error && !prefs) {
    return <EmptyState title="Could not load preferences" description={error} action={{ label: "Try again", onClick: load }} />
  }

  if (!prefs) {
    return (
      <div className="space-y-2" role="status" aria-label="Loading preferences">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-card" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-fg-primary">Notification preferences</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-fg-muted">
          Choose which events reach you in-app, by email, or both. Everything is on until you turn it off; email
          delivery failures never block the underlying action.
        </p>
      </div>

      <ul className="divide-y divide-line/60 rounded-card border border-line bg-surface">
        {prefs.map((pref) => (
          <li key={pref.event_key} className="flex flex-wrap items-center justify-between gap-3 p-3">
            <p className="text-sm text-fg-primary">{notificationEventLabel(pref.event_key)}</p>
            <div className="flex items-center gap-4">
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-fg-secondary">
                <input
                  type="checkbox"
                  checked={pref.in_app}
                  onChange={() => toggle(pref.event_key, "in_app")}
                  className="accent-brand-500"
                />
                In-app
              </label>
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-fg-secondary">
                <input
                  type="checkbox"
                  checked={pref.email}
                  onChange={() => toggle(pref.event_key, "email")}
                  className="accent-brand-500"
                />
                Email
              </label>
              {!pref.in_app && !pref.email && <Badge tone="neutral">Muted</Badge>}
            </div>
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-3">
        <Button variant="primary" loading={saving} disabled={!dirty} onClick={() => void save()}>
          Save preferences
        </Button>
        {saved && !dirty && <span className="text-xs text-success-fg">Saved.</span>}
        {dirty && !saved && <span className="text-xs text-fg-muted">Unsaved changes.</span>}
      </div>
    </div>
  )
}

export default NotificationPreferencesPage
