import { useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"

import {
  TRANSITION_LABELS,
  isDestructiveTransition,
  transitionRequiresReason,
  transitionRequiresSummary,
} from "./incidentShared"

type IncidentTransitionDialogProps = {
  open: boolean
  onClose: () => void
  onConfirm: (payload: { reason?: string; resolution_summary?: string; parent_incident_id?: string }) => void
  /** The target status, exactly as it came from the detail's
   * allowed_next_states -- never a hard-coded map. */
  target: string
  incidentTitle: string
  loading?: boolean
}

/**
 * The one dialog behind every incident status change. Required fields
 * follow the target (the backend 422s otherwise, so the form mirrors
 * it): FALSE_POSITIVE/DUPLICATE need a reason, DUPLICATE also the parent
 * incident id, CLOSED the resolution summary. Destructive targets
 * (CLOSED, FALSE_POSITIVE, DUPLICATE -- all terminal or irreversible
 * story-wise) additionally require typing CONFIRM.
 */
function IncidentTransitionDialog({
  open,
  onClose,
  onConfirm,
  target,
  incidentTitle,
  loading = false,
}: IncidentTransitionDialogProps) {
  const [reason, setReason] = useState("")
  const [summary, setSummary] = useState("")
  const [parent, setParent] = useState("")
  const [typed, setTyped] = useState("")

  const needsReason = transitionRequiresReason(target)
  const needsSummary = transitionRequiresSummary(target)
  const needsParent = target === "DUPLICATE"
  const destructive = isDestructiveTransition(target)
  const canConfirm =
    (!needsReason || reason.trim().length > 0) &&
    (!needsSummary || summary.trim().length > 0) &&
    (!needsParent || parent.trim().length > 0) &&
    (!destructive || typed.trim() === "CONFIRM")

  function handleClose() {
    setReason("")
    setSummary("")
    setParent("")
    setTyped("")
    onClose()
  }

  function handleConfirm() {
    if (!canConfirm) return
    onConfirm({
      ...(needsReason ? { reason: reason.trim() } : {}),
      ...(needsSummary ? { resolution_summary: summary.trim() } : {}),
      ...(needsParent ? { parent_incident_id: parent.trim() } : {}),
    })
    handleClose()
  }

  const label = TRANSITION_LABELS[target] ?? target

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title={`Move to ${label}`}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={handleConfirm}
            disabled={!canConfirm || loading}
            loading={loading}
          >
            {`Move to ${label}`}
          </Button>
        </>
      }
    >
      <p>
        Moves <strong className="text-fg-primary">{incidentTitle}</strong> to{" "}
        <strong className="text-fg-primary">{label}</strong>.
        {destructive && " This closes the incident's working story -- linked alerts follow the verdict."}
      </p>

      {needsSummary && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Resolution summary (required)</span>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={3}
            aria-required="true"
            placeholder="What was done, what fixed it, how it was confirmed."
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>
      )}

      {needsReason && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Reason (required)</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            aria-required="true"
            placeholder={target === "DUPLICATE" ? "Why this is a duplicate." : "Why this is a false positive."}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>
      )}

      {needsParent && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Parent incident id (required)</span>
          <input
            value={parent}
            onChange={(e) => setParent(e.target.value)}
            aria-required="true"
            placeholder="The id of the incident this duplicates"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>
      )}

      {destructive && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">
            Type <strong className="text-fg-primary">CONFIRM</strong> to confirm
          </span>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            aria-required="true"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>
      )}
    </Dialog>
  )
}

export default IncidentTransitionDialog
