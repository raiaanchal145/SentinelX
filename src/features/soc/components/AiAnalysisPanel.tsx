import { useCallback, useEffect, useState } from "react"
import { Bot, Check, Pencil, RefreshCw, X } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  apiGetAiAnalysis,
  apiDecideAiAnalysis,
  ApiErrorLike as ApiError,
  type AiAnalysisView,
} from "../../../lib/aiAnalysisApi"

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

export default function AiAnalysisPanel({ targetType, targetId, canWrite, onOpenEvent }: AiAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<AiAnalysisView | null>(null)
  const [loading, setLoading] = useState(false)
  const [waited, setWaited] = useState(false) // the draft may still be generating
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")
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
    // The triage job runs right after the alert is created; give it a
    // few seconds before declaring "AI unavailable".
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

          {Array.isArray(analysis.recommended_actions?.actions) && (
            <div>
              <p className="text-fg-muted">Recommended actions</p>
              <ul className="mt-1 list-disc pl-4 text-fg-secondary">
                {analysis.recommended_actions.actions.map((a: string, i: number) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}

          {analysis.decision && (
            <p className="text-fg-muted">
              Decision:{" "}
              <span className="font-medium text-fg-secondary">{analysis.decision.decision}</span>
              {analysis.decision.reason ? ` — "${analysis.decision.reason}"` : ""}
            </p>
          )}

          {canWrite && !analysis.decision && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Button variant="primary" icon={<Check size={13} />} loading={busy} onClick={() => void decide("accepted")}>
                Accept
              </Button>
              <Button variant="secondary" icon={<Pencil size={13} />} loading={busy} onClick={() => toast.show("Edit the fields above and re-run 'Accept' to store edits.", { tone: "info" })}>
                Edit
              </Button>
              <Button variant="secondary" icon={<X size={13} />} loading={busy} onClick={() => setRejectOpen(true)}>
                Reject
              </Button>
              <Button variant="secondary" icon={<RefreshCw size={13} />} loading={busy} onClick={() => toast.show("Regeneration is subject to the organization's cost caps.", { tone: "info" })}>
                Regenerate
              </Button>
            </div>
          )}
        </div>
      )}

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
