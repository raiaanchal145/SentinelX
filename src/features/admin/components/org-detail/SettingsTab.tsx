import { useState } from "react"

import Button from "../../../../components/ui/Button"
import ConfirmDialog from "../../../../components/ui/ConfirmDialog"
import { useToast } from "../../../../components/ui/Toast"
import {
  apiArchiveOrganization,
  apiPatchOrganization,
  apiReactivateOrganization,
  apiSuspendOrganization,
  ApiError,
  type OrganizationDetail,
} from "../../../../lib/api"

type SettingsTabProps = {
  detail: OrganizationDetail
  onSaved: () => void
}

type LifecycleAction = "suspend" | "reactivate" | "archive"

/** Platform admin's editable settings for one organization (Prompt B
 * section A3, "Settings") -- distinct from the owner's READ-ONLY
 * settings page (section B5); the platform admin is the one account
 * type allowed to change these fields or the organization's lifecycle
 * status directly. */
function SettingsTab({ detail, onSaved }: SettingsTabProps) {
  const toast = useToast()
  const [name, setName] = useState(detail.name)
  const [industry, setIndustry] = useState(detail.industry ?? "")
  const [maxMembers, setMaxMembers] = useState(detail.max_members?.toString() ?? "")
  const [saving, setSaving] = useState(false)

  const [lifecycleAction, setLifecycleAction] = useState<LifecycleAction | null>(null)
  const [actionBusy, setActionBusy] = useState(false)

  const dirty =
    name.trim() !== detail.name ||
    industry.trim() !== (detail.industry ?? "") ||
    maxMembers.trim() !== (detail.max_members?.toString() ?? "")

  async function handleSave() {
    setSaving(true)
    try {
      const parsedMaxMembers = maxMembers.trim() ? Number(maxMembers) : undefined
      await apiPatchOrganization(detail.id, {
        name: name.trim(),
        industry: industry.trim(),
        max_members: parsedMaxMembers,
      })
      toast.show("Organization settings saved.", { tone: "success" })
      onSaved()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not save settings.", { tone: "danger" })
    } finally {
      setSaving(false)
    }
  }

  async function handleLifecycleConfirm(reason?: string) {
    if (!lifecycleAction) return
    setActionBusy(true)
    try {
      if (lifecycleAction === "suspend") {
        await apiSuspendOrganization(detail.id, reason ?? "")
        toast.show(`${detail.name} suspended.`, { tone: "success" })
      } else if (lifecycleAction === "reactivate") {
        await apiReactivateOrganization(detail.id)
        toast.show(`${detail.name} reactivated.`, { tone: "success" })
      } else {
        await apiArchiveOrganization(detail.id)
        toast.show(`${detail.name} archived.`, { tone: "success" })
      }
      onSaved()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not complete this action.", { tone: "danger" })
    } finally {
      setActionBusy(false)
      setLifecycleAction(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-4 rounded-card border border-line bg-surface p-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Organization name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full max-w-md rounded-control border border-line bg-surface-sunken px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Industry</label>
          <input
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="w-full max-w-md rounded-control border border-line bg-surface-sunken px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-fg-muted">Member limit</label>
          <input
            type="number"
            min={1}
            value={maxMembers}
            onChange={(e) => setMaxMembers(e.target.value)}
            placeholder="No limit"
            className="w-full max-w-md rounded-control border border-line bg-surface-sunken px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>
        <Button variant="primary" disabled={!dirty || saving} onClick={() => void handleSave()}>
          {saving ? "Saving..." : "Save settings"}
        </Button>
      </div>

      <div className="rounded-card border border-line bg-surface p-4">
        <p className="text-sm font-medium text-fg-primary">Organization status</p>
        <p className="mt-1 text-xs text-fg-muted">Current status: {detail.status}</p>

        <div className="mt-3 flex flex-wrap gap-2">
          {(detail.status === "active" || detail.status === "pending") && (
            <Button variant="danger" onClick={() => setLifecycleAction("suspend")}>
              Suspend
            </Button>
          )}
          {detail.status === "suspended" && (
            <Button variant="primary" onClick={() => setLifecycleAction("reactivate")}>
              Reactivate
            </Button>
          )}
          {detail.status !== "archived" && (
            <Button variant="danger" onClick={() => setLifecycleAction("archive")}>
              Archive
            </Button>
          )}
          {detail.status === "archived" && <p className="text-xs text-fg-muted">Archived organizations are terminal.</p>}
        </div>
      </div>

      <ConfirmDialog
        open={lifecycleAction !== null}
        onClose={() => setLifecycleAction(null)}
        onConfirm={(reason) => void handleLifecycleConfirm(reason)}
        title={
          lifecycleAction === "suspend"
            ? `Suspend ${detail.name}?`
            : lifecycleAction === "reactivate"
              ? `Reactivate ${detail.name}?`
              : `Archive ${detail.name}?`
        }
        impact={
          lifecycleAction === "suspend"
            ? "Members of this organization will not be able to sign in until it's reactivated."
            : lifecycleAction === "reactivate"
              ? "Members will be able to sign in again."
              : "Archiving is terminal and cannot be undone."
        }
        requireReason={lifecycleAction === "suspend"}
        confirmLabel={actionBusy ? "Working..." : "Confirm"}
        danger={lifecycleAction !== "reactivate"}
      />
    </div>
  )
}

export default SettingsTab
