import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { RefreshCw, ServerOff, Wifi } from "lucide-react"

import DemoDataChip from "../../../components/shared/DemoDataChip"
import EmptyState from "../../../components/EmptyState"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import CountdownChip from "../../../components/ui/CountdownChip"
import { useToast } from "../../../components/ui/Toast"

import {
  delay,
  getAssetById,
  getDueSoon,
  getItKpis,
  getMyAssets,
  getMyTickets,
  getMyWorkByStatus,
} from "../../../lib/data"
import { scopeFor } from "../../../lib/scope"
import { useMockStore } from "../../../mocks/store"
import type { Asset, Ticket } from "../../../types"

import TaskCard from "../components/TaskCard"
import TaskDetailDrawer from "../components/TaskDetailDrawer"

type Column = { key: string; label: string; statuses: Ticket["status"][] }

const COLUMNS: Column[] = [
  { key: "assigned", label: "Assigned", statuses: ["OPEN", "TRIAGED", "ASSIGNED"] },
  { key: "acknowledged", label: "Acknowledged", statuses: ["ACKNOWLEDGED"] },
  { key: "in-progress", label: "In progress", statuses: ["INVESTIGATING", "REMEDIATION"] },
  { key: "verification", label: "Ready for verification", statuses: ["VERIFICATION"] },
  { key: "done", label: "Done", statuses: ["RESOLVED", "CLOSED"] },
]

function sortByDue(tickets: Ticket[]): Ticket[] {
  return [...tickets].sort((a, b) => {
    const aTime = a.resolveDueAt ? new Date(a.resolveDueAt).getTime() - Date.now() : Infinity
    const bTime = b.resolveDueAt ? new Date(b.resolveDueAt).getTime() - Date.now() : Infinity
    return aTime - bTime
  })
}

function randomMockSize(): number {
  return Math.round(20_000 + Math.random() * 2_000_000)
}

function ItMyTasks() {
  const { state, dispatch } = useMockStore()
  const toast = useToast()
  const scope = useMemo(() => scopeFor(), [])

  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(() => new Date())
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)

  async function reload() {
    setLoading(true)
    await delay(null)
    setLoading(false)
    setLastUpdated(new Date())
  }

  useEffect(() => {
    let cancelled = false
    delay(null).then(() => {
      if (!cancelled) setLoading(false)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const kpis = useMemo(() => getItKpis(state, scope), [state, scope])
  const myTickets = useMemo(() => getMyTickets(state, scope), [state, scope])
  const byStatus = useMemo(() => getMyWorkByStatus(state, scope), [state, scope])
  const dueSoon = useMemo(() => getDueSoon(state, scope, 5), [state, scope])
  const myAssets = useMemo(() => getMyAssets(state, scope), [state, scope])

  const columns = useMemo(
    () =>
      COLUMNS.map((column) => ({
        ...column,
        tickets:
          column.key === "done"
            ? myTickets.filter((t) => t.status === "RESOLVED" || t.status === "CLOSED")
            : sortByDue(column.statuses.flatMap((status) => byStatus[status] ?? [])),
      })),
    [byStatus, myTickets],
  )

  const recentSocComments = useMemo(() => {
    return myTickets
      .flatMap((ticket) => ticket.comments.map((comment) => ({ ticket, comment })))
      .filter(({ comment }) => comment.authorName !== scope.displayName)
      .sort((a, b) => new Date(b.comment.createdAt).getTime() - new Date(a.comment.createdAt).getTime())
      .slice(0, 5)
  }, [myTickets, scope.displayName])

  const topTask = dueSoon[0]

  const selectedTicket = useMemo(
    () => state.tickets.find((t) => t.id === selectedTicketId) ?? null,
    [state.tickets, selectedTicketId],
  )
  const selectedAsset = selectedTicket ? getAssetById(state, selectedTicket.assetId) : undefined

  function handleAcknowledge(ticket: Ticket) {
    dispatch({ type: "IT_ACK_TICKET", ticketId: ticket.id, actorName: scope.displayName })
    toast.show(`Acknowledged ${ticket.ticketNumber}.`, { tone: "success" })
  }

  function handleStartWork(ticket: Ticket) {
    dispatch({ type: "IT_START_TICKET", ticketId: ticket.id, actorName: scope.displayName })
    toast.show(`Started work on ${ticket.ticketNumber}.`, { tone: "success" })
  }

  function handleSubmitForVerification(ticket: Ticket) {
    dispatch({ type: "IT_SUBMIT_FOR_VERIFICATION", ticketId: ticket.id, actorName: scope.displayName })
    toast.show(`${ticket.ticketNumber} submitted for SOC verification.`, { tone: "info" })
  }

  function handleToggleChecklistItem(ticket: Ticket, itemId: string) {
    dispatch({ type: "IT_TOGGLE_CHECKLIST_ITEM", ticketId: ticket.id, itemId, actorName: scope.displayName })
  }

  function handleAddEvidence(ticket: Ticket, fileName: string) {
    dispatch({
      type: "IT_ADD_EVIDENCE",
      ticketId: ticket.id,
      evidence: {
        id: `evidence-live-${Date.now()}`,
        fileName,
        sizeBytes: randomMockSize(),
        addedAt: new Date().toISOString(),
      },
      actorName: scope.displayName,
    })
  }

  function handleAddComment(ticket: Ticket, body: string) {
    dispatch({
      type: "IT_ADD_COMMENT",
      ticketId: ticket.id,
      comment: {
        id: `comment-live-${Date.now()}`,
        authorName: scope.displayName,
        authorType: "user",
        body,
        createdAt: new Date().toISOString(),
      },
    })
  }

  const assetColumns: DataTableColumn<Asset>[] = [
    { key: "hostname", header: "Asset", render: (a) => a.hostname },
    {
      key: "health",
      header: "Health",
      width: "110px",
      render: (a) =>
        a.agentStatus === "connected" ? (
          <span className="flex items-center gap-1.5 text-success-fg">
            <Wifi size={13} aria-hidden="true" /> Connected
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-critical-fg">
            <ServerOff size={13} aria-hidden="true" /> Offline
          </span>
        ),
    },
    {
      key: "openTickets",
      header: "Open tickets",
      width: "110px",
      render: (a) => myTickets.filter((t) => t.assetId === a.id && t.status !== "CLOSED" && t.status !== "RESOLVED").length,
    },
    {
      key: "lastSeen",
      header: "Last seen",
      render: (a) => (
        <span title={new Date(a.lastSeenAt).toString()}>{new Date(a.lastSeenAt).toLocaleString()}</span>
      ),
    },
  ]

  const hasWork = myTickets.length > 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">My Remediation Work</h1>
          <p className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
            Last updated{" "}
            <time dateTime={lastUpdated.toISOString()} title={lastUpdated.toString()}>
              {lastUpdated.toLocaleTimeString()}
            </time>
            <DemoDataChip />
          </p>
        </div>
        <IconButton icon={RefreshCw} label="Refresh dashboard" onClick={reload} />
      </div>

      <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {loading
          ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
          : kpis.map((kpi) => <KpiCard key={kpi.label} {...kpi} />)}
      </section>

      {!loading && !hasWork ? (
        <EmptyState
          title="No remediation tasks assigned"
          description="Tickets appear here once the SOC assigns remediation work to you or your team."
        />
      ) : (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          <section className="xl:col-span-2" aria-label="My work">
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
                          <TaskCard
                            key={ticket.id}
                            ticket={ticket}
                            asset={getAssetById(state, ticket.assetId)}
                            onOpenDetail={(t) => setSelectedTicketId(t.id)}
                            onAcknowledge={handleAcknowledge}
                            onStartWork={handleStartWork}
                            onSubmitForVerification={handleSubmitForVerification}
                          />
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
                  {dueSoon.map((ticket) => (
                    <li key={ticket.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedTicketId(ticket.id)}
                        className="flex w-full items-center justify-between gap-2 rounded-control border border-line bg-surface-sunken p-2 text-left text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                      >
                        <span className="truncate text-fg-secondary">{ticket.title}</span>
                        <CountdownChip dueAt={ticket.resolveDueAt} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-label="Recommended next step" className="rounded-card border border-line bg-surface p-4">
              <h2 className="text-sm font-semibold text-fg-primary">Recommended next step</h2>
              {loading ? (
                <Skeleton className="mt-3 h-14 w-full" />
              ) : !topTask || topTask.recommendedSteps.length === 0 ? (
                <p className="mt-2 text-xs text-fg-muted">No recommended steps right now.</p>
              ) : (
                <div className="mt-2 text-xs">
                  <p className="text-fg-muted">For {topTask.ticketNumber}</p>
                  <p className="mt-1 text-fg-secondary">{topTask.recommendedSteps[0]}</p>
                  {topTask.runbookId && (
                    <Link
                      to={`/it/runbooks?id=${topTask.runbookId}`}
                      className="mt-2 inline-block font-medium text-brand-400 hover:text-brand-300"
                    >
                      Open runbook
                    </Link>
                  )}
                </div>
              )}
            </section>

            <section aria-label="Comments from SOC" className="rounded-card border border-line bg-surface p-4">
              <h2 className="text-sm font-semibold text-fg-primary">Comments from SOC</h2>
              {loading ? (
                <Skeleton count={2} className="h-12 w-full" />
              ) : recentSocComments.length === 0 ? (
                <p className="mt-2 text-xs text-fg-muted">No comments on your tickets yet.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {recentSocComments.map(({ ticket, comment }) => (
                    <li key={comment.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedTicketId(ticket.id)}
                        className="w-full rounded-control border border-line bg-surface-sunken p-2 text-left text-xs transition hover:border-line-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                      >
                        <p className="flex items-center justify-between font-medium text-fg-primary">
                          {comment.authorName}
                          <span className="font-normal text-fg-faint">{ticket.ticketNumber}</span>
                        </p>
                        <p className="mt-1 line-clamp-2 text-fg-muted">{comment.body}</p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      )}

      <section aria-label="Assets I own">
        <h2 className="mb-2 text-sm font-semibold text-fg-primary">Assets I own</h2>
        <DataTable
          columns={assetColumns}
          rows={myAssets}
          getRowId={(a) => a.id}
          ariaLabel="Assets I own"
          loading={loading}
          emptyState={
            <p className="p-4 text-center text-xs text-fg-muted">No assets are linked to your open tickets.</p>
          }
        />
      </section>

      <TaskDetailDrawer
        open={selectedTicket !== null}
        onClose={() => setSelectedTicketId(null)}
        ticket={selectedTicket}
        asset={selectedAsset}
        onToggleChecklistItem={handleToggleChecklistItem}
        onAddEvidence={handleAddEvidence}
        onAddComment={handleAddComment}
      />
    </div>
  )
}

export default ItMyTasks
