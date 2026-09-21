import { type FormEvent, useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"
import { apiInviteSocAnalyst, ApiError } from "../../../lib/api"

const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

type InviteSocAnalystDialogProps = {
  open: boolean
  onClose: () => void
  onInvited: () => void
}

function InviteSocAnalystDialog({ open, onClose, onInvited }: InviteSocAnalystDialogProps) {
  const [email, setEmail] = useState("")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  function handleClose() {
    if (submitting) return
    setEmail("")
    setError("")
    onClose()
  }

  async function submit() {
    setError("")
    if (!EMAIL_PATTERN.test(email.trim())) {
      setError("Please enter a valid email address.")
      return
    }
    setSubmitting(true)
    try {
      await apiInviteSocAnalyst(email.trim().toLowerCase())
      onInvited()
      handleClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the invitation.")
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
      title="Invite platform SOC analyst"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} loading={submitting} disabled={submitting}>
            Send invitation
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="analyst@sentinelx.example"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            required
          />
          <p className="mt-1.5 text-xs text-fg-muted">
            They receive an invitation email to set their password and sign in as a platform SOC analyst.
          </p>
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

export default InviteSocAnalystDialog
