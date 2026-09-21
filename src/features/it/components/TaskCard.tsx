import type { KeyboardEvent } from "react"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import CountdownChip from "../../../components/ui/CountdownChip"
import ProgressBar from "../../../components/ui/ProgressBar"
import SeverityBadge from "../../../components/SeverityBadge"
import Tooltip from "../../../components/ui/Tooltip"
import type { Asset, Ticket } from "../../../types"

type TaskCardProps = {
  ticket: Ticket
  asset: Asset | undefined
  onOpenDetail: (ticket: Ticket) => void
  onAcknowledge: (ticket: Ticket) => void
  onStartWork: (ticket: Ticket) => void
  onSubmitForVerification: (ticket: Ticket) => void
}

function canSubmitForVerification(ticket: Ticket): boolean {
  const checklistComplete = ticket.checklist.length > 0 && ticket.checklist.every((item) => item.done)
  return checklistComplete && ticket.evidence.length > 0
}

function submitBlockedReason(ticket: Ticket): string {
  const missing: string[] = []
  if (ticket.checklist.length === 0 || !ticket.checklist.every((item) => item.done)) missing.push("the checklist")
  if (ticket.evidence.length === 0) missing.push("evidence")
  return `Complete ${missing.join(" and ")} before submitting for SOC verification.`
}

/** One remediation ticket in the "My work" board. The whole card opens the
 * detail drawer; action buttons stop propagation so they don't also open it. */
function TaskCard({ ticket, asset, onOpenDetail, onAcknowledge, onStartWork, onSubmitForVerification }: TaskCardProps) {
  const doneCount = ticket.checklist.filter((item) => item.done).length
  const isAssigned = ticket.status === "OPEN" || ticket.status === "TRIAGED" || ticket.status === "ASSIGNED"
  const isAcknowledged = ticket.status === "ACKNOWLEDGED"
  const isInProgress = ticket.status === "INVESTIGATING" || ticket.status === "REMEDIATION"
  const isAwaitingVerification = ticket.status === "VERIFICATION"
  const isDone = ticket.status === "RESOLVED" || ticket.status === "CLOSED"
  const submittable = canSubmitForVerification(ticket)

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onOpenDetail(ticket)
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpenDetail(ticket)}
      onKeyDown={handleKeyDown}
      className="cursor-pointer rounded-card border border-line bg-surface p-3 text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-fg-faint">{ticket.ticketNumber}</span>
        <SeverityBadge severity={ticket.severity} showIcon />
      </div>

      <p className="mt-2 font-medium text-fg-primary">{ticket.title}</p>
      <p className="mt-1 line-clamp-1 text-fg-muted">{ticket.description}</p>

      <p className="mt-2 text-fg-muted">
        {asset?.hostname ?? "No asset on file"}
        {ticket.environment && <> &middot; {ticket.environment}</>}
      </p>

      {ticket.reopenReason && (
        <Badge tone="danger" className="mt-2">
          Returned by SOC
        </Badge>
      )}

      <div className="mt-3 flex items-center justify-between gap-2">
        <CountdownChip dueAt={ticket.resolveDueAt} done={isDone} />
      </div>

      <div className="mt-2">
        <ProgressBar value={doneCount} max={ticket.checklist.length} label="Checklist" />
      </div>

      <div className="mt-3">
        {isAssigned && (
          <Button
            variant="secondary"
            className="w-full"
            onClick={(e) => {
              e.stopPropagation()
              onAcknowledge(ticket)
            }}
          >
            Acknowledge
          </Button>
        )}
        {isAcknowledged && (
          <Button
            variant="secondary"
            className="w-full"
            onClick={(e) => {
              e.stopPropagation()
              onStartWork(ticket)
            }}
          >
            Start work
          </Button>
        )}
        {isInProgress && (
          <Tooltip label={submittable ? "Ready to submit" : submitBlockedReason(ticket)}>
            <Button
              variant="primary"
              className="w-full"
              disabled={!submittable}
              onClick={(e) => {
                e.stopPropagation()
                onSubmitForVerification(ticket)
              }}
            >
              Submit for verification
            </Button>
          </Tooltip>
        )}
        {isAwaitingVerification && (
          <p className="rounded-control border border-line bg-surface-sunken px-2 py-1.5 text-center text-fg-muted">
            Waiting for SOC verification
          </p>
        )}
        {isDone && (
          <p className="rounded-control border border-success/20 bg-success/10 px-2 py-1.5 text-center text-success-fg">
            {ticket.status === "CLOSED" ? "Closed" : "Resolved"}
          </p>
        )}
      </div>
    </div>
  )
}

export default TaskCard
