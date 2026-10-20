import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertTriangle, Bot, Check, Clock, Eye, RefreshCw, Shield, User, X } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Dialog from "../../../components/ui/Dialog"
import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import Tabs from "../../../components/ui/Tabs"
import { useToast } from "../../../components/ui/Toast"
import {
  apiApproveApproval,
  apiListApprovals,
  apiRejectApproval,
  type ApprovalRiskLevel,
  type ApprovalStatus,
  type ApprovalView,
} from "../../../lib/approvalsApi"

function riskTone(risk: ApprovalRiskLevel): "brand" | "neutral" | "danger" | "success" {
  switch (risk) {
    case "high":
      return "danger"
    case "low":
      return "neutral"
    case "read_only":
      return "brand"
    default:
      return "neutral"
  }
}

function statusTone(status: ApprovalStatus): "brand" | "neutral" | "danger" | "success" {
  switch (status) {
    case "approved":
      return "success"
    case "rejected":
      return "danger"
    case "expired":
      return "neutral"
    case "pending":
    default:
      return "brand"
  }
}

function riskExplanation(risk: ApprovalRiskLevel): string {
  switch (risk) {
    case "high":
      return "High Risk: Containment or state-altering action. Gated by policy to require human approval before executing."
    case "low":
      return "Low Risk: Reversible data update. Requires review because automated low-risk actions are turned off."
    case "read_only":
      return "Read Only: Informational inquiry."
    default:
      return "Requires authorization by policy."
  }
}

export default function ManagerApprovals() {
  const [activeTab, setActiveTab] = useState<"pending" | "mine" | "history">("pending")
  const [approvals, setApprovals] = useState<ApprovalView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  // Detail inspection drawer/dialog
  const [selectedApproval, setSelectedApproval] = useState<ApprovalView | null>(null)

  // Decision dialog states
  const [decideMode, setDecideMode] = useState<"approve" | "reject" | null>(null)
  const [decideTarget, setDecideTarget] = useState<ApprovalView | null>(null)
  const [reasonInput, setReasonInput] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const toast = useToast()

  const load = useCallback(() => {
    setLoading(true)
    setError("")
    apiListApprovals(activeTab)
      .then((res) => {
        setApprovals(res.approvals)
        setError("")
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not load approvals.")
      })
      .finally(() => setLoading(false))
  }, [activeTab])

  useEffect(() => {
    load()
  }, [load])

  function openDecide(approval: ApprovalView, mode: "approve" | "reject") {
    setDecideTarget(approval)
    setDecideMode(mode)
    setReasonInput("")
  }

  function closeDecide() {
    setDecideMode(null)
    setDecideTarget(null)
    setReasonInput("")
  }

  async function handleDecideSubmit() {
    if (!decideTarget || !decideMode) return
    if (decideMode === "reject" && !reasonInput.trim()) {
      toast.show("A reason is required to reject an approval request.", { tone: "danger" })
      return
    }

    setSubmitting(true)
    try {
      if (decideMode === "approve") {
        await apiApproveApproval(decideTarget.id, reasonInput.trim() || undefined)
        toast.show("Approval granted. Action sent to worker execution.", { tone: "success" })
      } else {
        await apiRejectApproval(decideTarget.id, reasonInput.trim())
        toast.show("Approval rejected.", { tone: "info" })
      }
      closeDecide()
      setSelectedApproval(null)
      load()
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("sentinelx_approvals_change"))
      }
    } catch (err: unknown) {
      toast.show(err instanceof Error ? err.message : "Decision failed.", { tone: "danger" })
    } finally {
      setSubmitting(false)
    }
  }

  const pendingCount = useMemo(() => {
    return activeTab === "pending" ? approvals.length : undefined
  }, [activeTab, approvals.length])

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-fg-primary">Authorizations &amp; Approvals</h1>
          <p className="text-xs text-fg-muted">
            Review and govern containment actions, critical ticket closures, and automated agent proposals.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <IconButton icon={RefreshCw} label="Refresh approvals" onClick={load} />
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        ariaLabel="Approval queues"
        value={activeTab}
        onChange={(id) => setActiveTab(id as "pending" | "mine" | "history")}
        tabs={[
          {
            id: "pending",
            label: "Pending Queue",
            badge: pendingCount !== undefined && pendingCount > 0 ? (
              <span className="ml-1 rounded-full bg-danger px-1.5 py-0.2 text-[10px] font-bold text-white">
                {pendingCount}
              </span>
            ) : undefined,
            content: null,
          },
          {
            id: "mine",
            label: "My Requests",
            content: null,
          },
          {
            id: "history",
            label: "History",
            content: null,
          },
        ]}
      />

      {/* Content */}
      {error ? (
        <div className="rounded-card border border-danger/30 bg-danger/5 p-4 text-xs text-danger-fg">
          <p className="font-semibold">Failed to load approvals</p>
          <p className="mt-1">{error}</p>
          <Button variant="secondary" className="mt-3 text-xs" onClick={load}>
            Try again
          </Button>
        </div>
      ) : loading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : approvals.length === 0 ? (
        <EmptyState
          title={
            activeTab === "pending"
              ? "No Pending Approvals"
              : activeTab === "mine"
              ? "No Requests Created"
              : "No Approval History"
          }
          description={
            activeTab === "pending"
              ? "All actions requiring authorization have been reviewed. Clean queue!"
              : "Requests you initiate or that are decided will appear here."
          }
        />
      ) : (
        <div className="space-y-3">
          {approvals.map((item) => {
            const toolName = item.tool || item.action_type.replace("tool:", "")
            const isAi = item.requested_by_type === "ai_agent"
            const isPending = item.status === "pending"

            return (
              <div
                key={item.id}
                className="flex flex-col justify-between gap-3 rounded-card border border-line bg-surface p-4 transition hover:border-line-strong sm:flex-row sm:items-center"
              >
                <div className="space-y-1.5 min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-fg-primary">{toolName}</span>
                    <Badge tone={riskTone(item.risk_level)}>{item.risk_level} risk</Badge>
                    <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                    {isAi ? (
                      <span className="inline-flex items-center gap-1 rounded bg-brand/10 px-1.5 py-0.5 text-[11px] font-medium text-brand-300">
                        <Bot size={12} aria-hidden="true" />
                        AI Agent
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] text-fg-muted">
                        <User size={12} aria-hidden="true" />
                        {item.requested_by_type}
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-fg-secondary truncate">
                    {item.requested_reason || "No explicit reason supplied."}
                  </p>

                  <div className="flex flex-wrap items-center gap-4 text-[11px] text-fg-faint">
                    {item.created_at && (
                      <span className="flex items-center gap-1">
                        <Clock size={11} /> Requested {new Date(item.created_at).toLocaleString()}
                      </span>
                    )}
                    {item.expires_at && isPending && (
                      <span className="text-warning-fg">Expires: {new Date(item.expires_at).toLocaleString()}</span>
                    )}
                    {item.incident_id && (
                      <span className="font-mono">Incident #{item.incident_id.slice(0, 8)}</span>
                    )}
                  </div>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="ghost"
                    className="text-xs flex items-center gap-1.5"
                    onClick={() => setSelectedApproval(item)}
                  >
                    <Eye size={13} /> Details
                  </Button>

                  {isPending && (
                    <>
                      <Button
                        variant="secondary"
                        className="text-xs text-danger-fg hover:bg-danger/10 flex items-center gap-1"
                        onClick={() => openDecide(item, "reject")}
                      >
                        <X size={13} /> Reject
                      </Button>
                      <Button
                        variant="primary"
                        className="text-xs flex items-center gap-1"
                        onClick={() => openDecide(item, "approve")}
                      >
                        <Check size={13} /> Approve
                      </Button>
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Detail Dialog */}
      {selectedApproval && (
        <Dialog
          open
          title={`Approval Details: ${selectedApproval.tool || selectedApproval.action_type}`}
          onClose={() => setSelectedApproval(null)}
          footer={
            <div className="flex w-full items-center justify-between">
              <Button variant="ghost" onClick={() => setSelectedApproval(null)}>
                Close
              </Button>
              {selectedApproval.status === "pending" && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="danger"
                    onClick={() => {
                      openDecide(selectedApproval, "reject")
                    }}
                  >
                    Reject
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => {
                      openDecide(selectedApproval, "approve")
                    }}
                  >
                    Approve
                  </Button>
                </div>
              )}
            </div>
          }
        >
          <div className="space-y-4 text-xs">
            {/* Risk Explanation Banner */}
            <div
              className={`rounded-control border p-3 ${
                selectedApproval.risk_level === "high"
                  ? "border-danger/30 bg-danger/5 text-danger-fg"
                  : "border-line bg-surface-sunken text-fg-muted"
              }`}
            >
              <div className="flex items-center gap-2 font-semibold">
                <Shield size={14} />
                <span>{selectedApproval.risk_level.toUpperCase()} Risk Tier</span>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed">{riskExplanation(selectedApproval.risk_level)}</p>
            </div>

            <div className="grid grid-cols-2 gap-3 rounded-control border border-line bg-surface p-3">
              <div>
                <span className="text-[10px] uppercase text-fg-muted">Action Type</span>
                <p className="font-mono text-sm font-semibold text-fg-primary">
                  {selectedApproval.tool || selectedApproval.action_type}
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase text-fg-muted">Status</span>
                <div className="mt-0.5">
                  <Badge tone={statusTone(selectedApproval.status)}>{selectedApproval.status}</Badge>
                </div>
              </div>

              <div>
                <span className="text-[10px] uppercase text-fg-muted">Requested By</span>
                <p className="font-medium text-fg-primary flex items-center gap-1">
                  {selectedApproval.requested_by_type === "ai_agent" ? (
                    <>
                      <Bot size={12} className="text-brand-300" /> AI Agent
                    </>
                  ) : (
                    <>
                      <User size={12} /> {selectedApproval.requested_by_type}
                    </>
                  )}
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase text-fg-muted">Requested At</span>
                <p className="text-fg-secondary">
                  {selectedApproval.created_at ? new Date(selectedApproval.created_at).toLocaleString() : "--"}
                </p>
              </div>

              {selectedApproval.incident_id && (
                <div className="col-span-2">
                  <span className="text-[10px] uppercase text-fg-muted">Target Incident</span>
                  <p className="font-mono text-fg-primary">{selectedApproval.incident_id}</p>
                </div>
              )}
            </div>

            {/* Requested Reason */}
            <div>
              <span className="font-semibold text-fg-primary">Requested Reason:</span>
              <p className="mt-1 rounded-control border border-line bg-surface-sunken p-2.5 text-fg-secondary">
                {selectedApproval.requested_reason || "(No reason provided)"}
              </p>
            </div>

            {/* Arguments Payload */}
            {selectedApproval.arguments && Object.keys(selectedApproval.arguments).length > 0 && (
              <div>
                <span className="font-semibold text-fg-primary">Action Payload:</span>
                <pre className="mt-1 overflow-x-auto rounded-control border border-line bg-surface-sunken p-2.5 font-mono text-[11px] text-fg-muted">
                  {JSON.stringify(selectedApproval.arguments, null, 2)}
                </pre>
              </div>
            )}

            {/* Decided Info */}
            {selectedApproval.status !== "pending" && (
              <div className="rounded-control border border-line bg-surface p-3 space-y-1">
                <span className="font-semibold text-fg-primary">Decision Record</span>
                <p className="text-fg-muted">
                  Decision: <span className="font-semibold">{selectedApproval.status}</span>
                </p>
                {selectedApproval.decision_reason && (
                  <p className="text-fg-muted">Reason: {selectedApproval.decision_reason}</p>
                )}
                {selectedApproval.reviewed_at && (
                  <p className="text-[11px] text-fg-faint">
                    Reviewed: {new Date(selectedApproval.reviewed_at).toLocaleString()}
                  </p>
                )}
                {selectedApproval.executed_at && (
                  <p className="text-[11px] text-success-fg">
                    Executed: {new Date(selectedApproval.executed_at).toLocaleString()}
                  </p>
                )}
              </div>
            )}
          </div>
        </Dialog>
      )}

      {/* Approve/Reject Confirmation Dialog */}
      {decideMode && decideTarget && (
        <Dialog
          open
          title={decideMode === "approve" ? "Authorize Action" : "Reject Action"}
          onClose={closeDecide}
          footer={
            <div className="flex w-full justify-end gap-2">
              <Button variant="ghost" onClick={closeDecide} disabled={submitting}>
                Cancel
              </Button>
              <Button
                variant={decideMode === "approve" ? "primary" : "danger"}
                onClick={handleDecideSubmit}
                disabled={submitting || (decideMode === "reject" && !reasonInput.trim())}
              >
                {submitting
                  ? "Submitting..."
                  : decideMode === "approve"
                  ? "Confirm & Authorize"
                  : "Confirm Rejection"}
              </Button>
            </div>
          }
        >
          <div className="space-y-3 text-xs">
            <div className="flex items-start gap-2 rounded-control border border-line bg-surface-sunken p-3">
              <AlertTriangle
                size={16}
                className={decideMode === "approve" ? "text-warning-fg" : "text-danger-fg"}
              />
              <div>
                <p className="font-semibold text-fg-primary">
                  {decideMode === "approve"
                    ? `You are about to authorize ${decideTarget.tool || decideTarget.action_type}.`
                    : `You are rejecting ${decideTarget.tool || decideTarget.action_type}.`}
                </p>
                <p className="mt-1 text-fg-muted">
                  {decideMode === "approve"
                    ? "Once approved, the action will be dispatched to the execution worker immediately."
                    : "Rejections cannot be undone. An audit record will preserve this decision."}
                </p>
              </div>
            </div>

            <div>
              <label htmlFor="reason" className="block font-medium text-fg-primary mb-1">
                {decideMode === "reject" ? "Rejection Reason (Required)" : "Authorization Note (Optional)"}
              </label>
              <textarea
                id="reason"
                rows={3}
                value={reasonInput}
                onChange={(e) => setReasonInput(e.target.value)}
                placeholder={
                  decideMode === "reject"
                    ? "Explain why this request is rejected..."
                    : "Add any context or instructions..."
                }
                className="w-full rounded-control border border-line bg-surface p-2 text-fg-primary placeholder:text-fg-faint focus:border-brand-400 focus:outline-none"
              />
            </div>
          </div>
        </Dialog>
      )}
    </div>
  )
}
