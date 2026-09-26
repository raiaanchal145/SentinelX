import { useEffect, useState } from "react"
import { CheckCheck, Link2, Siren, UserPlus, XCircle } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import Drawer from "../../../components/ui/Drawer"
import Skeleton from "../../../components/ui/Skeleton"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiAcknowledgeAlert,
  apiAssignAlert,
  apiDismissAlert,
  apiGetAlert,
  apiReopenAlert,
  type AlertDetail,
  type AlertRow,
} from "../../../lib/api"

import { ageLabel, ALERT_STATUS_LABELS, historyActionLabel } from "./alertShared"
import EventDetailDrawer from "./EventDetailDrawer"

type AlertDrawerProps = {
  /** The list-row snapshot; the drawer refetches full detail itself. */
  alert: AlertRow | null
  onClose: () => void
  /** False for read-only viewers (managed-mode owner/security_manager):
   * action buttons are hidden entirely. */
  canWrite: boolean
  /** Assign targets for this queue (already scoped server-side by role). */
  assignees: { account_type: "admin" | "user"; account_id: string; label: string }[]
  /** Called after any successful mutation so the page can refetch its list. */
  onChanged: () => void
}

/** Detail drawer for one alert: summary, why it fired (rule + correlation
 * reasoning), supporting events (each opens the shared event drawer in
 * place), and the alert's history -- with inline acknowledge/assign/
 * dismiss (reason required)/reopen for queues the caller may write. */
function AlertDrawer({ alert, onClose, canWrite, assignees, onChanged }: AlertDrawerProps) {
  const [detail, setDetail] = useState<AlertDetail | null>(null)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busy, setBusy] = useState(false)
  const [dismissOpen, setDismissOpen] = useState(false)
  const [ackOpen, setAckOpen] = useState(false)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const toast = useToast()

  useEffect(() => {
    if (!alert) {
      setDetail(null)
      setError("")
      setActionError("")
      return
    }
    setDetail(null)
    setError("")
    setActionError("")
    apiGetAlert(alert.id)
      .then(setDetail)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load this alert."))
  }, [alert])

  if (!alert) return null

  async function runAction(action: () => Promise<unknown>, successMessage: string) {
    setBusy(true)
    setActionError("")
    try {
      await action()
      toast.show(successMessage, { tone: "success" })
      const fresh = await apiGetAlert(alert!.id)
      setDetail(fresh)
      onChanged()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "The action failed. Try again.")
    } finally {
      setBusy(false)
    }
  }

  const row = detail?.alert ?? alert
  const rule = detail?.rule ?? null
  const correlation = detail?.correlation ?? null
  const isDismissed = row.status === "dismissed"

  return (
    <>
      <Drawer open onClose={onClose} title="Alert detail" side="right" widthClassName="w-[520px] max-w-[95vw]">
        {error ? (
          <div className="p-4">
            <p className="text-sm text-danger-fg">{error}</p>
            <Button variant="secondary" className="mt-3" onClick={() => alert && apiGetAlert(alert.id).then(setDetail).catch(() => undefined)}>
              Try again
            </Button>
          </div>
        ) : !detail ? (
          <div className="space-y-4 p-4">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton count={3} className="h-4 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <div className="space-y-5 p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={row.severity} showIcon />
              <Badge tone={row.status === "new" ? "brand" : "neutral"}>{ALERT_STATUS_LABELS[row.status]}</Badge>
              <Badge tone={row.kind === "correlation" ? "danger" : "neutral"}>{row.kind}</Badge>
              <span className="ml-auto text-xs text-fg-muted" title={row.first_seen_at ? new Date(row.first_seen_at).toString() : undefined}>
                age {ageLabel(row.first_seen_at)}
              </span>
            </div>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Summary</h3>
              <p className="mt-1 text-fg-secondary">{row.summary}</p>
            </section>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Why it fired</h3>
              {rule ? (
                <div className="mt-1 rounded-control border border-line bg-surface-sunken p-3 text-xs">
                  <p className="font-medium text-fg-primary">
                    {rule.name}
                    {rule.mitre_technique && <span className="ml-2 font-normal text-fg-muted">{rule.mitre_technique}</span>}
                  </p>
                  {rule.description && <p className="mt-1 text-fg-secondary">{rule.description}</p>}
                </div>
              ) : (
                <p className="mt-1 text-xs text-fg-muted">{row.rule_name ?? "No detection rule (correlated alert)."}</p>
              )}
              {correlation && (
                <div className="mt-2 rounded-panel border border-brand-500/20 bg-brand-500/5 p-3 text-xs">
                  <p className="flex items-center gap-1.5 font-medium text-brand-300">
                    <Link2 size={12} aria-hidden="true" />
                    {correlation.title}
                  </p>
                  <p className="mt-1 text-fg-secondary">{correlation.reasoning}</p>
                  <p className="mt-1 text-fg-muted">
                    Groups {correlation.grouped_alerts.length} alert{correlation.grouped_alerts.length === 1 ? "" : "s"} ·{" "}
                    {correlation.event_count} events
                  </p>
                </div>
              )}
            </section>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
                Supporting events ({detail.events.length})
              </h3>
              {detail.events.length === 0 ? (
                <p className="mt-1 text-xs text-fg-muted">No supporting events stored on this alert.</p>
              ) : (
                <ul className="mt-2 max-h-64 space-y-1.5 overflow-y-auto pr-1">
                  {detail.events.map((event) => (
                    <li key={event.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedEventId(event.id)}
                        className="w-full rounded-control border border-line bg-surface-sunken p-2 text-left text-xs transition hover:border-line-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="font-medium text-fg-primary">{event.event_type}</span>
                          <span className="text-fg-muted">{event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "--"}</span>
                        </span>
                        <span className="mt-0.5 block truncate text-fg-muted">
                          {[event.username, event.source_ip].filter(Boolean).join(" · ") || "--"}
                        </span>
                        {event.message && <span className="mt-0.5 block truncate text-fg-secondary">{event.message}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">History</h3>
              <ul className="mt-2 space-y-1 text-xs">
                {detail.history.map((entry, i) => (
                  <li key={i} className="flex items-start justify-between gap-3 rounded-control bg-surface-sunken px-2 py-1.5">
                    <span className="text-fg-secondary">
                      {historyActionLabel(entry.action)}
                      {entry.detail?.reason ? `: "${String(entry.detail.reason)}"` : ""}
                      {entry.detail?.assigned_account_type ? ` (${String(entry.detail.assigned_account_type)})` : ""}
                    </span>
                    <span className="shrink-0 text-fg-faint">
                      {entry.actor_type} · {entry.created_at ? new Date(entry.created_at).toLocaleString() : "--"}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="rounded-control border border-line bg-surface-sunken p-3 text-xs text-fg-secondary">
              <p>
                <span className="text-fg-muted">User:</span> {row.username ?? "--"} · <span className="text-fg-muted">IP:</span>{" "}
                {row.source_ip ?? "--"} · <span className="text-fg-muted">Events:</span> {row.event_count}
              </p>
              {isDismissed && row.dismissed_reason && (
                <p className="mt-1">
                  <span className="text-fg-muted">Dismissal reason:</span> {row.dismissed_reason}
                </p>
              )}
            </section>

            {actionError && <p className="text-xs text-danger-fg">{actionError}</p>}

            {canWrite && (
              <div className="flex flex-wrap gap-2">
                {row.status === "new" && (
                  <Button variant="primary" icon={<CheckCheck size={14} />} loading={busy} onClick={() => setAckOpen(true)}>
                    Acknowledge
                  </Button>
                )}
                {assignees.length > 0 && (
                  <label className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
                    <UserPlus size={13} aria-hidden="true" />
                    <span className="sr-only">Assign this alert</span>
                    <select
                      aria-label="Assign this alert to"
                      value=""
                      disabled={busy}
                      onChange={(e) => {
                        const target = assignees.find((a) => `${a.account_type}:${a.account_id}` === e.target.value)
                        if (target) {
                          void runAction(
                            () => apiAssignAlert(row.id, { account_type: target.account_type, account_id: target.account_id }),
                            "Alert assigned.",
                          )
                        }
                      }}
                      className="rounded-control border border-line bg-surface px-2.5 py-2 text-xs text-fg-secondary focus:border-brand-500 focus:outline-none"
                    >
                      <option value="" disabled>
                        Assign to…
                      </option>
                      {assignees.map((a) => (
                        <option key={`${a.account_type}:${a.account_id}`} value={`${a.account_type}:${a.account_id}`}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {!isDismissed && row.status !== "converted" && (
                  <Button variant="secondary" icon={<XCircle size={14} />} loading={busy} onClick={() => setDismissOpen(true)}>
                    Dismiss
                  </Button>
                )}
                {isDismissed && (
                  <Button variant="secondary" icon={<Siren size={14} />} loading={busy} onClick={() => void runAction(() => apiReopenAlert(row.id), "Alert reopened.")}>
                    Reopen
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={ackOpen}
        onClose={() => setAckOpen(false)}
        onConfirm={() => {
          setAckOpen(false)
          if (row) void runAction(() => apiAcknowledgeAlert(row.id), "Alert acknowledged.")
        }}
        title="Acknowledge alert"
        impact="Moves this alert from new to acknowledged (triaged). You can still dismiss or work it afterwards."
        confirmLabel="Acknowledge"
        danger={false}
      />

      <ConfirmDialog
        open={dismissOpen}
        onClose={() => setDismissOpen(false)}
        onConfirm={(reason) => {
          setDismissOpen(false)
          if (row && reason && reason.trim()) {
            void runAction(() => apiDismissAlert(row.id, reason.trim()), "Alert dismissed.")
          }
        }}
        title="Dismiss alert"
        impact="Marks this alert as a false positive. A reason is required and stored in the alert's history."
        requireReason
        confirmLabel="Dismiss"
      />

      <EventDetailDrawer eventId={selectedEventId} onClose={() => setSelectedEventId(null)} />
    </>
  )
}

export default AlertDrawer
