import { useCallback, useEffect, useState } from "react"
import { UserPlus } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiAutoAssignTicket,
  apiCreateTicket,
  apiListTickets,
  apiTransitionTicket,
  apiVerifyTicket,
  type IncidentRow,
  type TicketRow,
} from "../../../lib/api"

import { computeTicketPriorityPreview } from "./incidentShared"

type IncidentTicketPanelProps = {
  incident: IncidentRow
  /** Detail assets carry criticality -- the first one feeds the preview. */
  assetCriticality: string | null
  canWrite: boolean
  onChanged: () => void
}

const SLA_TONE: Record<string, "brand" | "neutral" | "danger" | "success"> = {
  on_track: "success",
  at_risk: "brand",
  breached: "danger",
  none: "neutral",
}

/** The Ticket tab: for an incident without an open ticket, the SOC-side
 * writer can create one for the organization's IT (priority preview from
 * the documented formula; the SOC can override). With a ticket, it shows
 * status/SLA/assignment and the SOC actions: verify (from VERIFICATION)
 * and reopen. IT's own working moves stay on the IT pages. */
function IncidentTicketPanel({ incident, assetCriticality, canWrite, onChanged }: IncidentTicketPanelProps) {
  const toast = useToast()
  const [ticket, setTicket] = useState<TicketRow | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [acting, setActing] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("")
  const [priorityOverride, setPriorityOverride] = useState<"" | "P1" | "P2" | "P3" | "P4">("")
  const [verifyTarget, setVerifyTarget] = useState<{ result: "verified" | "failed" | "reopened"; label: string } | null>(null)
  const [reopenOpen, setReopenOpen] = useState(false)

  const load = useCallback(
    async function load() {
      setLoading(true)
      try {
        const res = await apiListTickets({ incident_id: incident.id, limit: 1 })
        setTicket(res.tickets[0] ?? null)
      } catch (err) {
        toast.show(err instanceof ApiError ? err.message : "Could not load the linked ticket.", { tone: "danger" })
      } finally {
        setLoading(false)
      }
    },
    [incident.id, toast],
  )

  useEffect(() => {
    load()
  }, [load])

  const computedPriority = computeTicketPriorityPreview(incident.severity, assetCriticality, incident.confidence)
  const effectivePriority = priorityOverride || computedPriority

  async function handleCreate() {
    if (!title.trim()) return
    setCreating(true)
    try {
      const created = await apiCreateTicket({
        title: title.trim(),
        description: description.trim() || undefined,
        category: category.trim() || undefined,
        severity: incident.severity,
        priority: priorityOverride || undefined, // omitted -> backend computes
        incident_id: incident.id,
        organization_id: incident.organization_id,
      })
      toast.show(`Ticket ${created.ticket_number} created (${created.priority}).`, { tone: "success" })
      setShowCreate(false)
      setTitle("")
      setDescription("")
      setCategory("")
      setPriorityOverride("")
      setTicket(created)
      onChanged()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not create the ticket.", { tone: "danger" })
    } finally {
      setCreating(false)
    }
  }

  async function handleAutoAssign() {
    if (!ticket) return
    setActing(true)
    try {
      const updated = await apiAutoAssignTicket(ticket.id)
      setTicket(updated)
      toast.show(`Assigned via the organization's rules.`, { tone: "success" })
      onChanged()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Auto-assign failed -- no rule matched.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function confirmVerify() {
    if (!ticket || !verifyTarget) return
    const target = verifyTarget
    setVerifyTarget(null)
    setActing(true)
    try {
      const updated = await apiVerifyTicket(ticket.id, { result: target.result })
      setTicket(updated)
      toast.show(`Ticket ${updated.ticket_number}: ${target.label.toLowerCase()}.`, { tone: "success" })
      onChanged()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Verification failed.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function confirmReopen() {
    if (!ticket) return
    setReopenOpen(false)
    setActing(true)
    try {
      const updated = await apiTransitionTicket(ticket.id, { status: "OPEN", note: "Reopened from the incident panel" })
      setTicket(updated)
      toast.show(`Ticket ${updated.ticket_number} reopened.`, { tone: "info" })
      onChanged()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not reopen the ticket.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-fg-muted" role="status">Loading ticket…</p>
  }

  if (!ticket) {
    return (
      <div className="space-y-3">
        {!canWrite ? (
          <p className="text-sm text-fg-muted">No remediation ticket exists yet for this incident.</p>
        ) : showCreate ? (
          <form
            className="space-y-3 rounded-card border border-line bg-surface p-4"
            onSubmit={(e) => {
              e.preventDefault()
              void handleCreate()
            }}
          >
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-fg-muted">Title (required)</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-fg-muted">What IT should do</span>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              />
            </label>
            <div className="flex flex-wrap gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-fg-muted">Category</span>
                <input
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g. patching, credential reset"
                  className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-fg-muted">Priority (SOC override)</span>
                <select
                  value={priorityOverride}
                  onChange={(e) => setPriorityOverride(e.target.value as typeof priorityOverride)}
                  className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                >
                  <option value="">Computed: {computedPriority}</option>
                  {(["P1", "P2", "P3", "P4"] as const).map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="text-xs text-fg-muted">
              Priority preview <strong className="text-fg-primary">{effectivePriority}</strong> from the documented formula:
              severity {incident.severity}
              {assetCriticality ? `, asset criticality ${assetCriticality}` : ", no linked asset"}
              {incident.confidence !== null ? `, confidence ${Math.round(incident.confidence * 100)}%` : ""}. The backend
              computes the final value; an override is audited as <code>ticket.priority_override</code>.
            </p>
            <div className="flex gap-2">
              <Button type="submit" variant="primary" loading={creating} disabled={!title.trim()}>
                Create ticket
              </Button>
              <Button type="button" variant="ghost" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="rounded-card border border-dashed border-line bg-surface p-6 text-center">
            <p className="text-sm text-fg-muted">No remediation ticket yet for this incident.</p>
            {canWrite && (
              <Button variant="primary" className="mt-3" onClick={() => setShowCreate(true)}>
                Create ticket for IT
              </Button>
            )}
          </div>
        )}
      </div>
    )
  }

  const slaState = ticket.sla?.state ?? "none"
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-surface p-4">
        <div>
          <p className="flex items-center gap-2 text-sm font-medium text-fg-primary">
            <span className="font-mono">{ticket.ticket_number}</span>
            <Badge tone="neutral">{ticket.status}</Badge>
            <Badge tone={ticket.priority === "P1" ? "danger" : "brand"}>{ticket.priority}</Badge>
            <Badge tone={SLA_TONE[slaState] ?? "neutral"}>SLA {slaState.replace("_", " ")}</Badge>
          </p>
          <p className="mt-1 text-sm text-fg-secondary">{ticket.title}</p>
          {ticket.assigned_user_id && (
            <p className="mt-1 text-xs text-fg-muted">Assigned to an IT developer of the organization.</p>
          )}
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            {ticket.status === "VERIFICATION" && (
              <>
                <Button variant="primary" icon={<UserPlus size={14} />} loading={acting} onClick={() => setVerifyTarget({ result: "verified", label: "Verified" })}>
                  Verify fix
                </Button>
                <Button variant="secondary" loading={acting} onClick={() => setVerifyTarget({ result: "failed", label: "Failed" })}>
                  Verification failed
                </Button>
              </>
            )}
            {(ticket.status === "RESOLVED" || ticket.status === "CLOSED") && (
              <Button variant="secondary" loading={acting} onClick={() => setReopenOpen(true)}>
                Reopen ticket
              </Button>
            )}
            {!ticket.assigned_user_id && ticket.status !== "RESOLVED" && ticket.status !== "CLOSED" && (
              <Button variant="secondary" loading={acting} onClick={() => void handleAutoAssign()}>
                Suggest assignee
              </Button>
            )}
          </div>
        )}
      </div>

      {ticket.description && <p className="text-sm text-fg-secondary">{ticket.description}</p>}

      <p className="text-xs text-fg-muted">
        IT developers work this ticket from their own pages; the SOC verifies and closes here. A P1 ticket's close needs
        the organization's approval (P19 brings the approvals UI).
      </p>

      <ConfirmDialog
        open={verifyTarget !== null}
        onClose={() => setVerifyTarget(null)}
        onConfirm={() => void confirmVerify()}
        title={verifyTarget?.result === "verified" ? "Verify the fix" : "Fail verification"}
        impact={
          verifyTarget?.result === "verified"
            ? `Marks ${ticket.ticket_number} RESOLVED -- the SOC confirms the remediation worked.`
            : `Moves ${ticket.ticket_number} back to INVESTIGATING for IT.`
        }
        confirmLabel={verifyTarget?.result === "verified" ? "Verify" : "Send back"}
        danger={verifyTarget?.result === "failed"}
      />

      <ConfirmDialog
        open={reopenOpen}
        onClose={() => setReopenOpen(false)}
        onConfirm={() => void confirmReopen()}
        title="Reopen ticket"
        impact={`Moves ${ticket.ticket_number} back to OPEN -- the resolve clock restarts for IT.`}
        confirmLabel="Reopen"
      />
    </div>
  )
}

export default IncidentTicketPanel
