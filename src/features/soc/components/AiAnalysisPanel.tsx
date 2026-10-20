import { useCallback, useEffect, useState } from "react"
import { Bot, Check, FileText, Pencil, RefreshCw, Ticket, X } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  apiGetAiAnalysis,
  apiDecideAiAnalysis,
  apiRegenerateAiAnalysis,
  ApiErrorLike as ApiError,
  type AiAnalysisView,
} from "../../../lib/aiAnalysisApi"
import { apiCreateTicket } from "../../../lib/api"

/**
 * Shared AI-analysis panel, rendered by BOTH SOC placements:
 * - the alert drawer (target_type="alert")
 * - the incident detail page (target_type="incident")
 *
 * Contract the backend already enforces (docs/DECISIONS.md):
 * - the panel is labeling-only: "AI-generated — verify before acting";
 * - every decision the panel offers maps to a real endpoint;
 * - citations link to events the model was actually shown (the
 *   grounding check ran before anything was stored);
 * - read-only viewers (managed org's owner/security_manager) get the
 *   summary but no decision buttons -- mirroring the drawer's canWrite
 *   rule, not a second opinion.
 */

type AiAnalysisPanelProps = {
  /** Where the analysis hangs: alert or incident. */
  targetType: "alert" | "incident"
  /** The alert's or incident's id (not the analysis id). */
  targetId: string | null
  /** False for read-only oversight viewers: no decision buttons. */
  canWrite: boolean
  /** Event drawer opener for citations (alerts only). */
  onOpenEvent?: (eventId: string) => void
}

type TicketDraft = {
  description: string
  remediation_steps?: string[]
  suggested_priority: string
  assignee_team?: string | null
}

type TimelineDraft = {
  entry_type: string
  description: string
  timestamp?: string | null
  evidence_ids?: string[]
}

export default function AiAnalysisPanel({ targetType, targetId, canWrite, onOpenEvent }: AiAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<AiAnalysisView | null>(null)
  const [loading, setLoading] = useState(false)
  const [waited, setWaited] = useState(false)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [creatingTicket, setCreatingTicket] = useState(false)
  const [ticketCreated, setTicketCreated] = useState(false)

  // Rejection modal state
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")

  // Edit modal state
  const [editOpen, setEditOpen] = useState(false)
  const [editSummary, setEditSummary] = useState("")
  const [editTicketDesc, setEditTicketDesc] = useState("")
  const [editPriority, setEditPriority] = useState("P2")
  const [editReason, setEditReason] = useState("")

  const toast = useToast()

  const load = useCallback(() => {
    if (!targetId) return
    setLoading(true)
    setError("")
    apiGetAiAnalysis(targetType, targetId)
      .then((res) => {
        setAnalysis(res.analysis)
        setWaited(false)
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Could not load the AI analysis."),
      )
      .finally(() => setLoading(false))
  }, [targetType, targetId])

  useEffect(() => {
    if (!targetId) {
      setAnalysis(null)
      return
    }
    load()
    const t = setTimeout(() => setWaited(true), 4000)
    return () => clearTimeout(t)
  }, [targetId, load])

  async function decide(decision: "accepted" | "rejected", reason?: string) {
    if (!analysis) return
    setBusy(true)
    try {
      const fresh = await apiDecideAiAnalysis(analysis.id, { decision, reason })
      setAnalysis(fresh.analysis)
      toast.show(
        decision === "accepted" ? "AI analysis accepted." : "AI analysis rejected.",
        { tone: "success" },
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The decision failed. Try again.")
    } finally {
      setBusy(false)
      setRejectOpen(false)
      setRejectReason("")
    }
  }

  async function handleRegenerate() {
    if (!targetId) return
    setBusy(true)
    setError("")
    try {
      const fresh = await apiRegenerateAiAnalysis(targetType, targetId)
      setAnalysis(fresh.analysis)
      toast.show("AI analysis regenerated.", { tone: "success" })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Regeneration failed.")
    } finally {
      setBusy(false)
    }
  }

  const actionsPayload = (analysis?.recommended_actions ?? {}) as Record<string, unknown>
  const ticketDraft = actionsPayload.ticket_draft as TicketDraft | undefined
  const timelineEntries = actionsPayload.timeline_entries as TimelineDraft[] | undefined

  function startEdit() {
    setEditSummary(analysis?.summary ?? "")
    setEditTicketDesc(ticketDraft?.description ?? "")
    setEditPriority(ticketDraft?.suggested_priority ?? "P2")
    setEditReason("")
    setEditOpen(true)
  }

  async function saveEdits() {
    if (!analysis) return
    setBusy(true)
    try {
      const editsPayload: Record<string, unknown> = {
        summary: editSummary.trim(),
      }
      if (ticketDraft) {
        editsPayload.ticket_draft = {
          ...ticketDraft,
          description: editTicketDesc.trim(),
          suggested_priority: editPriority,
        }
      }
      const fresh = await apiDecideAiAnalysis(analysis.id, {
        decision: "edited",
        reason: editReason.trim() || "Analyst adjusted draft parameters",
        edits: editsPayload,
      })
      setAnalysis(fresh.analysis)
      toast.show("AI analysis updated with your edits.", { tone: "success" })
      setEditOpen(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save edits.")
    } finally {
      setBusy(false)
    }
  }

  async function handleCreateTicket() {
    if (!targetId || !ticketDraft) return
    setCreatingTicket(true)
    setError("")
    try {
      const title = (actionsPayload.title as string) || analysis?.summary || "Remediation Ticket"
      const steps = Array.isArray(ticketDraft.remediation_steps) ? ticketDraft.remediation_steps : []
      const desc = steps.length
        ? `${ticketDraft.description}\n\nRemediation Steps:\n- ${steps.join("\n- ")}`
        : ticketDraft.description
      await apiCreateTicket({
        title,
        description: desc,
        priority: ticketDraft.suggested_priority || "P2",
        incident_id: targetId,
      })
      setTicketCreated(true)
      toast.show("Ticket created from AI draft.", { tone: "success" })
      if (!analysis?.decision) {
        await decide("accepted")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create ticket from draft.")
    } finally {
      setCreatingTicket(false)
    }
  }

  if (!targetId) return null

  if (loading && !analysis) {
    return (
      <section className="rounded-panel border border-line bg-surface-sunken p-3">
        <Skeleton count={2} className="h-4 w-full" />
      </section>
    )
  }

  const isUntracked = !analysis && waited

  return (
    <section className="rounded-panel border border-brand-500/20 bg-brand-500/5 p-3">
      <header className="flex items-center gap-2">
        <Bot size={14} className="text-brand-300" aria-hidden="true" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-300">AI analysis</h3>
        <Badge tone="brand">AI-generated — verify before acting</Badge>
      </header>

      {error && <p className="mt-2 text-xs text-danger-fg">{error}</p>}

      {isUntracked && (
        <p className="mt-2 text-xs text-fg-muted">
          AI unavailable — showing the deterministic summary only. (AI is disabled for this
          organization, the provider could not be reached, or the analysis has not finished yet.)
        </p>
      )}

      {analysis && (
        <div className="mt-2 space-y-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-fg-muted">Confidence</span>
            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface">
              <div
                className="h-full rounded-full bg-brand-400"
                style={{ width: `${Math.round((analysis.confidence ?? 0) * 100)}%` }}
              />
            </div>
            <span className="text-fg-secondary">{Math.round((analysis.confidence ?? 0) * 100)}%</span>
            {analysis.source === "rules" ? (
              <Badge tone="neutral">deterministic fallback</Badge>
            ) : (
              <span className="text-fg-faint">
                FP-likelihood {Math.round((analysis.false_positive_likelihood ?? 0) * 100)}%
              </span>
            )}
          </div>

          {typeof actionsPayload.title === "string" && actionsPayload.title ? (
            <div>
              <p className="text-fg-muted">Drafted title</p>
              <p className="font-medium text-fg-primary">{actionsPayload.title}</p>
            </div>
          ) : null}

          <p className="text-fg-secondary">{analysis.summary}</p>
          {analysis.reasoning && <p className="text-fg-muted">{analysis.reasoning}</p>}

          {analysis.evidence_ids.length > 0 && (
            <div>
              <p className="text-fg-muted">Citations</p>
              <ul className="mt-1 flex flex-wrap gap-1">
                {analysis.evidence_ids.map((id) => (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => onOpenEvent?.(id)}
                      className="rounded-control border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-fg-secondary transition hover:border-brand-400"
                      title="Open the cited event"
                    >
                      {id.slice(0, 8)}…
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Alert triage actions */}
          {Array.isArray(actionsPayload.actions) && (
            <div>
              <p className="text-fg-muted">Recommended actions</p>
              <ul className="mt-1 list-disc pl-4 text-fg-secondary">
                {actionsPayload.actions.map((a: string, i: number) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Incident timeline entries draft */}
          {timelineEntries && timelineEntries.length > 0 && (
            <div className="rounded-control border border-line bg-surface-sunken p-2.5">
              <p className="font-medium text-fg-secondary">Drafted timeline ({timelineEntries.length})</p>
              <ul className="mt-1.5 space-y-1.5">
                {timelineEntries.map((entry, idx) => (
                  <li key={idx} className="border-l-2 border-brand-400 pl-2">
                    <span className="font-mono text-[11px] text-fg-muted uppercase">{entry.entry_type}</span>:{" "}
                    <span className="text-fg-secondary">{entry.description}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Incident ticket draft */}
          {ticketDraft && (
            <div className="rounded-control border border-brand-500/20 bg-surface p-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-medium text-fg-primary">
                  <Ticket size={13} className="text-brand-300" />
                  <span>Ticket Draft</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge tone="brand">{ticketDraft.suggested_priority || "P2"}</Badge>
                  {ticketDraft.assignee_team && (
                    <Badge tone="neutral">{ticketDraft.assignee_team}</Badge>
                  )}
                </div>
              </div>
              <p className="mt-1.5 text-fg-secondary">{ticketDraft.description}</p>
              {ticketDraft.remediation_steps && ticketDraft.remediation_steps.length > 0 && (
                <div className="mt-2">
                  <p className="text-fg-muted">Remediation steps:</p>
                  <ul className="mt-0.5 list-disc pl-4 text-fg-secondary">
                    {ticketDraft.remediation_steps.map((step, idx) => (
                      <li key={idx}>{step}</li>
                    ))}
                  </ul>
                </div>
              )}
              {canWrite && (
                <div className="mt-2.5">
                  <Button
                    variant="primary"
                    icon={<FileText size={12} />}
                    loading={creatingTicket}
                    disabled={ticketCreated}
                    onClick={() => void handleCreateTicket()}
                  >
                    {ticketCreated ? "Ticket Created" : "Create Ticket from Draft"}
                  </Button>
                </div>
              )}
            </div>
          )}

          {analysis.decision && (
            <p className="text-fg-muted">
              Decision:{" "}
              <span className="font-medium text-fg-secondary">{analysis.decision.decision}</span>
              {analysis.decision.reason ? ` — "${analysis.decision.reason}"` : ""}
            </p>
          )}

          {canWrite && !analysis.decision && !editOpen && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Button variant="primary" icon={<Check size={13} />} loading={busy} onClick={() => void decide("accepted")}>
                Accept
              </Button>
              <Button variant="secondary" icon={<Pencil size={13} />} loading={busy} onClick={startEdit}>
                Edit
              </Button>
              <Button variant="secondary" icon={<X size={13} />} loading={busy} onClick={() => setRejectOpen(true)}>
                Reject
              </Button>
              <Button variant="secondary" icon={<RefreshCw size={13} />} loading={busy} onClick={() => void handleRegenerate()}>
                Regenerate
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Edit Form */}
      {editOpen && (
        <div className="mt-2 rounded-control border border-line bg-surface p-2.5 space-y-2">
          <p className="font-medium text-fg-primary text-xs">Edit AI analysis</p>
          <div>
            <label className="text-fg-muted text-[11px]" htmlFor="ai-edit-summary">
              Summary
            </label>
            <textarea
              id="ai-edit-summary"
              value={editSummary}
              onChange={(e) => setEditSummary(e.target.value)}
              rows={2}
              className="mt-0.5 w-full rounded-control border border-line bg-surface-sunken p-1.5 text-xs text-fg-primary focus:border-brand-500 focus:outline-none"
            />
          </div>
          {ticketDraft && (
            <>
              <div>
                <label className="text-fg-muted text-[11px]" htmlFor="ai-edit-ticket">
                  Ticket description
                </label>
                <textarea
                  id="ai-edit-ticket"
                  value={editTicketDesc}
                  onChange={(e) => setEditTicketDesc(e.target.value)}
                  rows={2}
                  className="mt-0.5 w-full rounded-control border border-line bg-surface-sunken p-1.5 text-xs text-fg-primary focus:border-brand-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="text-fg-muted text-[11px]" htmlFor="ai-edit-prio">
                  Suggested priority
                </label>
                <select
                  id="ai-edit-prio"
                  value={editPriority}
                  onChange={(e) => setEditPriority(e.target.value)}
                  className="mt-0.5 w-full rounded-control border border-line bg-surface-sunken p-1.5 text-xs text-fg-primary focus:border-brand-500 focus:outline-none"
                >
                  <option value="P1">P1 (Critical)</option>
                  <option value="P2">P2 (High)</option>
                  <option value="P3">P3 (Medium)</option>
                  <option value="P4">P4 (Low)</option>
                </select>
              </div>
            </>
          )}
          <div>
            <label className="text-fg-muted text-[11px]" htmlFor="ai-edit-reason">
              Reason for edit (optional)
            </label>
            <input
              id="ai-edit-reason"
              type="text"
              value={editReason}
              onChange={(e) => setEditReason(e.target.value)}
              placeholder="e.g. Corrected severity and remediation scope"
              className="mt-0.5 w-full rounded-control border border-line bg-surface-sunken p-1.5 text-xs text-fg-primary focus:border-brand-500 focus:outline-none"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <Button variant="primary" loading={busy} onClick={() => void saveEdits()}>
              Save edits &amp; Accept
            </Button>
            <Button variant="secondary" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* Reject Form */}
      {rejectOpen && (
        <div className="mt-2 rounded-control border border-line bg-surface p-2">
          <label className="text-xs text-fg-secondary" htmlFor="ai-reject-reason">
            Why reject this analysis? (required)
          </label>
          <textarea
            id="ai-reject-reason"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-control border border-line bg-surface-sunken p-2 text-xs text-fg-primary focus:border-brand-500 focus:outline-none"
          />
          <div className="mt-2 flex gap-2">
            <Button
              variant="primary"
              loading={busy}
              disabled={!rejectReason.trim()}
              onClick={() => void decide("rejected", rejectReason.trim())}
            >
              Reject analysis
            </Button>
            <Button variant="secondary" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
