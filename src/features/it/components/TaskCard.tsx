import Badge from "../../../components/ui/Badge"
import CountdownChip from "../../../components/ui/CountdownChip"
import SeverityBadge from "../../../components/SeverityBadge"
import type { TicketRow } from "../../../lib/api"

import { isDoneStatus } from "../itShared"

type TaskCardProps = {
  ticket: TicketRow
  onOpen: (ticket: TicketRow) => void
}

/** One remediation ticket on the "My work" board, wired to the API's
 * TicketRow. The whole card is keyboard operable and opens the detail
 * page; the checklist/evidence work happens there. */
function TaskCard({ ticket, onOpen }: TaskCardProps) {
  const isDone = isDoneStatus(ticket.status)
  const isVerification = ticket.status === "VERIFICATION"
  const breached = ticket.sla?.state === "breached"

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(ticket)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onOpen(ticket)
        }
      }}
      className="cursor-pointer rounded-card border border-line bg-surface p-3 text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-fg-faint">{ticket.ticket_number}</span>
        <SeverityBadge severity={ticket.severity} showIcon />
      </div>

      <p className="mt-2 line-clamp-2 font-medium text-fg-primary">{ticket.title}</p>
      {ticket.category && <p className="mt-1 line-clamp-1 text-fg-muted">{ticket.category}</p>}

      <div className="mt-2 flex items-center justify-between gap-2">
        <Badge tone={ticket.priority === "P1" ? "danger" : "brand"}>{ticket.priority ?? "--"}</Badge>
        <CountdownChip dueAt={ticket.sla?.resolve_due_at ?? null} done={isDone} />
      </div>

      <div className="mt-3">
        {isVerification ? (
          <p className="rounded-control border border-line bg-surface-sunken px-2 py-1.5 text-center text-fg-muted">
            Waiting for SOC verification
          </p>
        ) : isDone ? (
          <p className="rounded-control border border-success/20 bg-success/10 px-2 py-1.5 text-center text-success-fg">
            {ticket.status === "CLOSED" ? "Closed" : "Resolved"}
          </p>
        ) : breached ? (
          <p className="rounded-control border border-critical/20 bg-critical/10 px-2 py-1.5 text-center text-critical-fg">
            SLA breached -- prioritize
          </p>
        ) : (
          <p className="rounded-control border border-line bg-surface-sunken px-2 py-1.5 text-center text-fg-muted">
            Open to work the checklist
          </p>
        )}
      </div>
    </div>
  )
}

export default TaskCard
