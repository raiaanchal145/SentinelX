import { useRef } from "react"
import { CheckCheck, XCircle } from "lucide-react"

import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import EmptyState from "../../../components/EmptyState"
import type { AlertRow } from "../../../lib/api"
import { SEVERITY_ORDER } from "../../../types/common"

import { ageLabel } from "./alertShared"

type TriageQueueProps = {
  alerts: AlertRow[]
  loading: boolean
  /** Client-side map of alert.asset_id -> criticality (from the assets
   * summary when available; unknown assets rank lowest). */
  criticalityOf?: (assetId: string | null) => number
  onOpen: (alert: AlertRow) => void
  onAcknowledge: (alert: AlertRow) => void
  onDismiss: (alert: AlertRow) => void
  canWrite: boolean
  emptyTitle?: string
  emptyDescription?: string
}

/**
 * The most-urgent-first queue: severity, then asset criticality, then age.
 * Keyboard operation: j/k move the selection, Enter opens, "a" acknowledges
 * with confirmation (the confirmation dialog is the page's job -- this
 * component just calls onAcknowledge).
 */
function TriageQueue({
  alerts,
  loading,
  criticalityOf,
  onOpen,
  onAcknowledge,
  onDismiss,
  canWrite,
  emptyTitle = "No alerts need triage",
  emptyDescription = "Nothing is waiting. New alerts appear here as the detection rules fire.",
}: TriageQueueProps) {
  const listRef = useRef<HTMLUListElement>(null)

  function moveFocus(delta: 1 | -1) {
    const list = listRef.current
    if (!list) return
    const items = Array.from(list.querySelectorAll<HTMLButtonElement>("li > button"))
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = Math.min(Math.max((current === -1 ? 0 : current) + delta, 0), items.length - 1)
    items[next]?.focus()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, alert: AlertRow) {
    if (event.key === "j") {
      event.preventDefault()
      moveFocus(1)
    } else if (event.key === "k") {
      event.preventDefault()
      moveFocus(-1)
    } else if (event.key === "Enter") {
      onOpen(alert)
    } else if (event.key === "a" && canWrite && alert.status === "new") {
      event.preventDefault()
      onAcknowledge(alert)
    }
  }

  if (loading) {
    return (
      <div className="space-y-2" role="status" aria-label="Loading triage queue">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-control" />
        ))}
      </div>
    )
  }

  if (alerts.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }

  const sorted = [...alerts].sort((a, b) => {
    const sev = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
    if (sev !== 0) return sev
    const crit =
      (criticalityOf?.(a.asset_id) ?? 0) - (criticalityOf?.(b.asset_id) ?? 0)
    if (crit !== 0) return -crit
    const aAge = a.first_seen_at ? new Date(a.first_seen_at).getTime() : 0
    const bAge = b.first_seen_at ? new Date(b.first_seen_at).getTime() : 0
    return aAge - bAge
  })

  return (
    <ul ref={listRef} className="space-y-2" aria-label="Triage queue">
      {sorted.map((alert) => (
        <li key={alert.id}>
          <button
            type="button"
            onClick={() => onOpen(alert)}
            onKeyDown={(e) => handleKeyDown(e, alert)}
            className="w-full rounded-control border border-line bg-surface p-2.5 text-left transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          >
            <span className="flex items-center gap-2">
              <SeverityBadge severity={alert.severity} showIcon />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-fg-primary" title={alert.title}>
                {alert.title}
              </span>
              <Badge tone="neutral">{alert.status === "triaged" ? "acknowledged" : alert.status}</Badge>
              <span className="shrink-0 text-xs text-fg-muted" title={alert.first_seen_at ? new Date(alert.first_seen_at).toString() : undefined}>
                {ageLabel(alert.first_seen_at)}
              </span>
            </span>
            <span className="mt-1 flex items-center justify-between gap-2 text-xs text-fg-muted">
              <span className="truncate">
                {[alert.rule_name, alert.username, alert.source_ip].filter(Boolean).join(" · ") || "--"}
              </span>
              {canWrite && (
                <span className="flex shrink-0 items-center gap-1">
                  {alert.status === "new" && (
                    <IconButton
                      icon={CheckCheck}
                      label={`Acknowledge ${alert.title}`}
                      size={14}
                      className="h-7 w-7"
                      onClick={(e) => {
                        e.stopPropagation()
                        onAcknowledge(alert)
                      }}
                    />
                  )}
                  {alert.status !== "dismissed" && alert.status !== "converted" && (
                    <IconButton
                      icon={XCircle}
                      label={`Dismiss ${alert.title}`}
                      size={14}
                      className="h-7 w-7"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDismiss(alert)
                      }}
                    />
                  )}
                </span>
              )}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

export default TriageQueue
