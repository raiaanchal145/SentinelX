import { type FormEvent, useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"
import { roleLabel } from "../../../lib/auth"
import { apiCreateMemberInvitation, ApiError, type Team } from "../../../lib/api"

const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

type InviteMemberDialogProps = {
  open: boolean
  onClose: () => void
  onInvited: () => void
  teams: Team[]
  /** SOC Analyst only appears while this organization runs its own SOC
   * (soc_mode = in_house) -- see docs/API_CONTRACT.md's
   * soc_analyst_requires_in_house. */
  socModeInHouse: boolean
}

function InviteMemberDialog({ open, onClose, onInvited, teams, socModeInHouse }: InviteMemberDialogProps) {
  const assignableRoles = [
    ...(socModeInHouse ? ["soc_analyst"] : []),
    "security_manager",
    "it_developer",
    "auditor",
  ]

  const [email, setEmail] = useState("")
  const [role, setRole] = useState(assignableRoles[0])
  const [teamId, setTeamId] = useState("")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  function reset() {
    setEmail("")
    setRole(assignableRoles[0])
    setTeamId("")
    setError("")
  }

  function handleClose() {
    if (submitting) return
    reset()
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
      await apiCreateMemberInvitation(email.trim().toLowerCase(), role, teamId || undefined)
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
      title="Invite member"
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
            placeholder="teammate@example.com"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            required
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          >
            {assignableRoles.map((value) => (
              <option key={value} value={value}>
                {roleLabel(value)}
              </option>
            ))}
          </select>
          {!socModeInHouse && (
            <p className="mt-1.5 text-xs text-fg-muted">
              SOC Analyst appears here once this organization switches to in-house SOC.
            </p>
          )}
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">
            Team <span className="text-fg-faint">(optional)</span>
          </label>
          <select
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          >
            <option value="">No team</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
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

export default InviteMemberDialog
