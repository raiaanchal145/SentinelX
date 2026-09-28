import { useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"

type IncidentNoteDialogProps = {
  open: boolean
  onClose: () => void
  onConfirm: (body: string, visibility: "internal" | "shared") => void
  loading?: boolean
}

/** Add a timeline note: internal (SOC-only, the default) or shared (also
 * readable by the organization / visible to IT developers). */
function IncidentNoteDialog({ open, onClose, onConfirm, loading = false }: IncidentNoteDialogProps) {
  const [body, setBody] = useState("")
  const [visibility, setVisibility] = useState<"internal" | "shared">("internal")

  function handleClose() {
    setBody("")
    setVisibility("internal")
    onClose()
  }

  function handleConfirm() {
    if (!body.trim()) return
    onConfirm(body.trim(), visibility)
    handleClose()
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Add note"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleConfirm} disabled={!body.trim() || loading} loading={loading}>
            Add note
          </Button>
        </>
      }
    >
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-fg-muted">Note</span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={4}
          aria-required="true"
          autoFocus
          className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        />
      </label>

      <fieldset className="mt-3">
        <legend className="mb-1 block text-xs font-medium text-fg-muted">Visibility</legend>
        <div className="flex gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-fg-secondary">
            <input
              type="radio"
              name="note-visibility"
              checked={visibility === "internal"}
              onChange={() => setVisibility("internal")}
              className="accent-brand-500"
            />
            Internal (SOC only)
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-fg-secondary">
            <input
              type="radio"
              name="note-visibility"
              checked={visibility === "shared"}
              onChange={() => setVisibility("shared")}
              className="accent-brand-500"
            />
            Shared with the organization
          </label>
        </div>
      </fieldset>
    </Dialog>
  )
}

export default IncidentNoteDialog
