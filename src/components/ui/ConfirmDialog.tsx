import { useState } from "react"
import Dialog from "./Dialog"
import Button from "./Button"

type ConfirmDialogProps = {
  open: boolean
  onClose: () => void
  onConfirm: (reason?: string) => void
  title: string
  impact: string
  /** When set, the confirm button stays disabled until the user types this
   * exact text -- for the highest-risk actions. */
  requireTypedText?: string
  /** When set, shows a free-text reason field (e.g. dismiss reason). */
  requireReason?: boolean
  confirmLabel?: string
  danger?: boolean
}

function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  impact,
  requireTypedText,
  requireReason = false,
  confirmLabel = "Confirm",
  danger = true,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("")
  const [reason, setReason] = useState("")

  const canConfirm = requireTypedText ? typed.trim() === requireTypedText : true

  function handleClose() {
    setTyped("")
    setReason("")
    onClose()
  }

  function handleConfirm() {
    onConfirm(requireReason ? reason : undefined)
    handleClose()
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={handleConfirm} disabled={!canConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p>{impact}</p>

      {requireReason && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Reason</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>
      )}

      {requireTypedText && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">
            Type <strong className="text-fg-primary">{requireTypedText}</strong> to confirm
          </span>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>
      )}
    </Dialog>
  )
}

export default ConfirmDialog
