import { type FormEvent, useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"
import SegmentedControl from "../../../components/ui/SegmentedControl"
import { apiCreateOrganization, ApiError, type OrganizationRow } from "../../../lib/api"

const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

type CreateOrganizationDialogProps = {
  open: boolean
  onClose: () => void
  onCreated: (organization: OrganizationRow) => void
}

/**
 * Platform admin's "create organization" dialog (Prompt B section A2).
 * Creates an ACTIVE organization directly and sends the owner an
 * invitation email -- there's no owner account until they accept it.
 * See docs/API_CONTRACT.md ("POST /admin/organizations").
 */
function CreateOrganizationDialog({ open, onClose, onCreated }: CreateOrganizationDialogProps) {
  const [name, setName] = useState("")
  const [industry, setIndustry] = useState("")
  const [ownerEmail, setOwnerEmail] = useState("")
  const [socMode, setSocMode] = useState<"managed" | "in_house">("managed")
  const [maxMembers, setMaxMembers] = useState("")

  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  function reset() {
    setName("")
    setIndustry("")
    setOwnerEmail("")
    setSocMode("managed")
    setMaxMembers("")
    setError("")
  }

  function handleClose() {
    if (submitting) return
    reset()
    onClose()
  }

  async function submit() {
    setError("")

    if (!name.trim() || !ownerEmail.trim()) {
      setError("Please fill in the organization name and owner email.")
      return
    }

    if (!EMAIL_PATTERN.test(ownerEmail.trim())) {
      setError("Please enter a valid owner email address.")
      return
    }

    const parsedMaxMembers = maxMembers.trim() ? Number(maxMembers) : undefined
    if (parsedMaxMembers !== undefined && (!Number.isInteger(parsedMaxMembers) || parsedMaxMembers < 1)) {
      setError("Member limit must be a whole number of at least 1.")
      return
    }

    setSubmitting(true)

    try {
      const organization = await apiCreateOrganization({
        name: name.trim(),
        owner_email: ownerEmail.trim().toLowerCase(),
        soc_mode: socMode,
        industry: industry.trim() || undefined,
        max_members: parsedMaxMembers,
      })
      onCreated(organization)
      reset()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the organization.")
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
      title="Create organization"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} loading={submitting} disabled={submitting}>
            Create organization
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Organization name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            required
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">
            Industry <span className="text-fg-faint">(optional)</span>
          </label>
          <input
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Owner email</label>
          <input
            type="email"
            value={ownerEmail}
            onChange={(e) => setOwnerEmail(e.target.value)}
            placeholder="owner@example.com"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            required
          />
          <p className="mt-1.5 text-xs text-fg-muted">
            The owner receives an invitation email to set their password and sign in.
          </p>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">SOC mode</label>
          <SegmentedControl
            ariaLabel="SOC mode"
            value={socMode}
            onChange={setSocMode}
            options={[
              { value: "managed", label: "Managed" },
              { value: "in_house", label: "In-house" },
            ]}
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">
            Member limit <span className="text-fg-faint">(optional)</span>
          </label>
          <input
            type="number"
            min={1}
            value={maxMembers}
            onChange={(e) => setMaxMembers(e.target.value)}
            placeholder="No limit"
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

export default CreateOrganizationDialog
