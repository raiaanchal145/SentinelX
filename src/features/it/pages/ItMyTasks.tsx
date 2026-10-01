import { useCallback, useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { RefreshCw } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import CountdownChip from "../../../components/ui/CountdownChip"
import { ApiError, apiGetTicket, apiListTickets, type TicketRow } from "../../../lib/api"

import { BOARD_COLUMNS, isDoneStatus, slaStateLabel } from "../itShared"

const DUE_SOON_MS = 4 * 60 * 60 * 1000 // 4 hours ahead of the resolve deadline

/** The IT developer's dashboard on real data: my open tickets, the SLA
 * clock (due soon / at risk / breached), and the latest shared comments
 * from the SOC on my tickets. Everything comes from GET /tickets (+ the
 * opened ticket's detail for comments). */
function ItMyTasks() {
  const navigate = useNavigate()

  const [tickets, setTickets] = useState<TicketRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [socComments, setSocComments] = useState<{ ticketNumber: string; ticketId: string; body: string; at: string }[]>([])
  const [commentsLoading, setCommentsLoading] = useState(true)

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListTickets({ assignee: "me", limit: 100 })
        setTickets(res.tickets)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load your tickets.")
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    load()
  }, [load])

  // Recent SOC comments: the newest status-change note per ticket is in
  // the ticket list already; the detail round-trip is only worth it for
  // the three most recently updated tickets.
  useEffect(() => {
    let cancelled = false
    async function loadComments() {
      setCommentsLoading(true)
      const recent = tickets.slice(0, 3)
      const found: { ticketNumber: string; ticketId: string; body: string; at: string }[] = []
      for (const ticket of recent) {
        try {
          const detail = await apiGetTicket(ticket.id)
          const last = [...detail.comments]
            .filter((c) => c.author_type === "admin") // SOC side
            .pop()
          if (last) {
            found.push({ ticketNumber: ticket.ticket_number, ticketId: ticket.id, body: last.body, at: last.created_at ?? "" })
          }
        } catch {
          // a single detail failure shouldn't blank the panel
        }
      }
      if (!cancelled) {
        setSocComments(found)
        setCommentsLoading(false)
      }
    }
    void loadComments()
    return () => {
      cancelled = true
    }
  }, [tickets])

  const open = useMemo(() => tickets.filter((t) => !isDoneStatus(t.status)), [tickets])
  const breached = useMemo(() => tickets.filter((t) => t.sla?.state === "breached"), [tickets])
  const atRisk = useMemo(() => tickets.filter((t) => t.sla?.state === "at_risk"), [tickets])
  const dueSoon = useMemo(
    () =>
      tickets
        .filter(
          (t) =>
            !isDoneStatus(t.status) &&
            t.sla?.resolve_due_at &&
            new Date(t.sla.resolve_due_at).getTime() - Date.now() < DUE_SOON_MS &&
            t.sla.state !== "breached",
        )
        .sort((a, b) => new Date(a.sla.resolve_due_at ?? 0).getTime() - new Date(b.sla.resolve_due_at ?? 0).getTime()),
    [tickets],
  )
  const verification = useMemo(() => tickets.filter((t) => t.status === "VERIFICATION"), [tickets])

  const columns = useMemo(
    () =>
      BOARD_COLUMNS.map((column) => ({
        ...column,
        tickets:
          column.key === "done"
            ? tickets.filter((t) => isDoneStatus(t.status))
            : column.statuses.flatMap((status) => tickets.filter((t) => t.status === status)),
      })),
    [tickets],
  )

  const hasWork = tickets.length > 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">My Remediation Work</h1>
          <p className="mt-0.5 text-xs text-fg-muted">Tickets assigned to you, on the real SLA clock.</p>
        </div>
        <IconButton icon={RefreshCw} label="Refresh dashboard" onClick={load} />
      </div>

      {error ? (
        <EmptyState title="Could not load your work" description={error} action={{ label: "Try again", onClick: load }} />
      ) : (
        <>
          <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {loading
              ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
              : [
                  <KpiCard key="open" label="My open tickets" value={open.length} tone="neutral" link="/it/tickets" />,
                  <KpiCard
                    key="due-soon"
                    label="Due within 4h"
                    value={dueSoon.length}
                    tone={dueSoon.length > 0 ? "medium" : "info"}
                    link="/it/tickets"
                  />,
                  <KpiCard
                    key="at-risk"
                    label="SLA at risk"
                    value={atRisk.length}
                    tone={atRisk.length > 0 ? "high" : "info"}
                    link="/it/tickets"
                  />,
                  <KpiCard
                    key="breached"
                    label="SLA breached"
                    value={breached.length}
                    tone={breached.length > 0 ? "critical" : "info"}
                    link="/it/tickets"
                  />,
                  <KpiCard
                    key="verification"
                    label="Awaiting SOC verification"
                    value={verification.length}
                    tone="info"
                    link="/it/tickets"
                  />,
                ]}
          </section>

          {!loading && !hasWork ? (
            <EmptyState
              title="No remediation tasks assigned"
              description="Tickets appear here once the SOC assigns remediation work to you or your team."
            />
          ) : (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
              <section className="xl:col-span-2" aria-label="My work board">
                <h2 className="mb-2 text-sm font-semibold text-fg-primary">My work</h2>
                {loading ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {Array.from({ length: 6 }, (_, i) => (
                      <Skeleton key={i} className="h-40 w-full rounded-card" />
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {columns.map((column) => (
                      <div key={column.key}>
                        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
                          {column.label} <span className="text-fg-faint">({column.tickets.length})</span>
                        </h3>
                        <div className="space-y-2">
                          {column.tickets.length === 0 ? (
                            <p className="rounded-card border border-dashed border-line p-3 text-xs text-fg-faint">
                              Nothing here.
                            </p>
                          ) : (
                            column.tickets.map((ticket) => (
                              <TaskMiniCard key={ticket.id} ticket={ticket} onOpen={() => navigate(`/it/tickets/${ticket.id}`)} />
                            ))
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <div className="space-y-4">
                <section aria-label="Due soon" className="rounded-card border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold text-fg-primary">Due soon</h2>
                  {loading ? (
                    <Skeleton count={3} className="h-10 w-full" />
                  ) : dueSoon.length === 0 ? (
                    <p className="mt-2 text-xs text-fg-muted">Nothing on the clock right now.</p>
                  ) : (
                    <ul className="mt-3 space-y-2">
                      {dueSoon.slice(0, 5).map((ticket) => (
                        <li key={ticket.id}>
                          <button
                            type="button"
                            onClick={() => navigate(`/it/tickets/${ticket.id}`)}
                            className="flex w-full items-center justify-between gap-2 rounded-control border border-line bg-surface-sunken p-2 text-left text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-fg-secondary">{ticket.title}</span>
                              <span className="text-fg-faint">{slaStateLabel(ticket.sla?.state ?? "none")}</span>
                            </span>
                            <CountdownChip dueAt={ticket.sla?.resolve_due_at ?? null} done={isDoneStatus(ticket.status)} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-label="Comments from SOC" className="rounded-card border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold text-fg-primary">Comments from SOC</h2>
                  {commentsLoading ? (
                    <Skeleton count={2} className="h-12 w-full" />
                  ) : socComments.length === 0 ? (
                    <p className="mt-2 text-xs text-fg-muted">No comments on your tickets yet.</p>
                  ) : (
                    <ul className="mt-3 space-y-2">
                      {socComments.map((comment) => (
                        <li key={`${comment.ticketId}-${comment.at}`}>
                          <button
                            type="button"
                            onClick={() => navigate(`/it/tickets/${comment.ticketId}`)}
                            className="w-full rounded-control border border-line bg-surface-sunken p-2 text-left text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                          >
                            <p className="flex items-center justify-between font-medium text-fg-primary">
                              Platform SOC
                              <span className="font-normal text-fg-faint">{comment.ticketNumber}</span>
                            </p>
                            <p className="mt-1 line-clamp-2 text-fg-muted">{comment.body}</p>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-label="Runbooks" className="rounded-card border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold text-fg-primary">Runbooks</h2>
                  <p className="mt-1 text-xs text-fg-muted">Reference procedures for common remediations.</p>
                  <Link to="/it/runbooks" className="mt-2 inline-block text-xs text-brand-400 hover:text-brand-300">
                    Open the runbook library
                  </Link>
                </section>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** One ticket on the "My work" board -- a lighter TaskCard wired to the
 * API's TicketRow (the old mock shape had its own checklist/evidence
 * arrays; the real checklist lives on the detail page). */
function TaskMiniCard({ ticket, onOpen }: { ticket: TicketRow; onOpen: () => void }) {
  const isDone = isDoneStatus(ticket.status)
  const isVerification = ticket.status === "VERIFICATION"
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onOpen()
        }
      }}
      className="cursor-pointer rounded-card border border-line bg-surface p-3 text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-fg-faint">{ticket.ticket_number}</span>
        <SeverityBadge severity={ticket.severity} showIcon />
      </div>

      <p className="mt-2 line-clamp-2 font-medium text-fg-primary">{ticket.title}</p>

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
        ) : ticket.sla?.state === "breached" ? (
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

export default ItMyTasks
