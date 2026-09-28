import { useState } from "react"

import Dialog from "../../../components/ui/Dialog"
import Button from "../../../components/ui/Button"
import SeverityBadge from "../../../components/SeverityBadge"
import { useToast } from "../../../components/ui/Toast"
import { ApiError, apiCreateIncidentFromAlerts, type AlertRow, type IncidentRow } from "../../../lib/api"

type CreateIncidentDialogProps = {
  open: boolean
  onClose: () => void
  /** The selected alerts (must all belong to ONE organization -- the
   * backend 400s otherwise; the pages only ever select within one). */
  alerts: AlertRow[]
  onCreated: (incident: IncidentRow) => void
}

/** Create an incident from 1+ selected alerts. The severity defaults to
 * the max of the alerts (computed server-side, previewed here), the
 * alerts become TRIAGED and follow the incident from then on. */
function CreateIncidentDialog({ open, onClose, alerts, onCreated }: CreateIncidentDialogProps) {
  const toast = useToast()
  const [title, setTitle] = useState("")
  const [busy, setBusy] = useState(false)

  const orgs = new Set(alerts.map((a) => a.organization_id))
  const crossOrg = orgs.size > 1
  const maxSeverity = alerts.reduce(
    (max, a) => (["critical", "high", "medium", "low", "info"].indexOf(a.severity) < ["critical", "high", "medium", "low", "info"].indexOf(max) ? a.severity : max),
    "info" as AlertRow["severity"],
  )

  async function handleCreate() {
    if (alerts.length === 0 || crossOrg) return
    setBusy(true)
    try {
      const incident = await apiCreateIncidentFromAlerts({
        alert_ids: alerts.map((a) => a.id),
        title: title.trim() || undefined,
      })
      toast.show(`Incident created from ${alerts.length} alert${alerts.length === 1 ? "" : "s"}.`, { tone: "success" })
      setTitle("")
      onCreated(incident)
      onClose()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not create the incident.", { tone: "danger" })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Create incident from alerts"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void handleCreate()} disabled={alerts.length === 0 || crossOrg} loading={busy}>
            Create incident
          </Button>
        </>
      }
    >
      <p>
        Links <strong className="text-fg-primary">{alerts.length}</strong> alert{alerts.length === 1 ? "" : "s"} and their
        supporting events into one incident. The alerts become triaged and follow the incident's outcome.
      </p>

      <div className="mt-3 flex items-center gap-2 text-xs text-fg-muted">
        Highest severity <SeverityBadge severity={maxSeverity} showIcon />
      </div>

      <label className="mt-3 block">
        <span className="mb-1 block text-xs font-medium text-fg-muted">Title (optional)</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder='Defaults to "Incident from N alert(s)"'
          className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        />
      </label>

      {crossOrg && (
        <p className="mt-3 text-xs text-danger-fg">
          The selection spans multiple organizations -- an incident can only contain alerts of one organization.
        </p>
      )}
    </Dialog>
  )
}

export default CreateIncidentDialog
