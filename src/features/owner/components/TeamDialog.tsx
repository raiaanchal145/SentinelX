import { type FormEvent, useEffect, useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"
import { apiCreateTeam, apiPatchTeam, ApiError, type Team } from "../../../lib/api"

type TeamDialogProps = {
  open: boolean
  onClose: () => void
  onSaved: () => void
  /** Present to edit that team; absent to create a new one. */
  team: Team | null
}

/** Create-or-edit dialog for a team (Prompt B section B3). */
function TeamDialog({ open, onClose, onSaved, team }: TeamDialogProps) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open) {
      setName(team?.name ?? "")
      setDescription(team?.description ?? "")
      setError("")
    }
  }, [open, team])

  function handleClose() {
    if (submitting) return
    onClose()
  }

  async function submit() {
    setError("")
    if (!name.trim()) {
      setError("Please enter a team name.")
      return
    }
    setSubmitting(true)
    try {
      if (team) {
        await apiPatchTeam(team.id, { name: name.trim(), description: description.trim() })
      } else {
        await apiCreateTeam(name.trim(), description.trim() || undefined)
      }
      onSaved()
      handleClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this team.")
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    void submit()
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title={team ? "Rename team" : "Create team"}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} loading={submitting} disabled={submitting}>
            {team ? "Save changes" : "Create team"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Team name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            required
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">
            Description <span className="text-fg-faint">(optional)</span>
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>

        {error && (
          <div className="rounded-control border border-danger/20 bg-danger/10 p-3 text-sm text-danger-fg">
            {error}
          </div>
        )}
      </form>
    </Dialog>
  )
}

export default TeamDialog
