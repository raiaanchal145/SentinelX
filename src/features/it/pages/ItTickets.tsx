import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { RefreshCw } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import IconButton from "../../../components/ui/IconButton"
import SegmentedControl from "../../../components/ui/SegmentedControl"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiListTickets,
  type TicketRow,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import { slaBadgeTone, slaStateLabel, TICKET_STATUSES, TICKET_STATUS_LABELS, ticketInScope, type TicketScope } from "../itShared"

const PAGE_SIZE = 50

const selectClass =
  "rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-secondary focus:border-brand-500 focus:outline-none"

type ScopeOption = { value: TicketScope; label: string }

/** The IT developer's ticket queue (module `it_tickets` read). Data comes
 * from GET /tickets -- the backend scopes it to the caller's organization;
 * mine/team/all is a client-side view over those rows. */
function ItTickets() {
  const { me } = useMe()
  const toast = useToast()
  const navigate = useNavigate()

  const [scope, setScope] = useState<TicketScope>("mine")
  const [status, setStatus] = useState("")
  const [priority, setPriority] = useState("")
  const [tickets, setTickets] = useState<TicketRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const teamId = me?.organization?.id ?? null // teams are org-scoped; the API has no per-user team on /auth/me

  const load = useCallback(
    async function load() {
      setLoading(true)
      setError("")
      try {
        const res = await apiListTickets({
          status: status || undefined,
          priority: priority || undefined,
          limit: PAGE_SIZE,
        })
        setTickets(res.tickets)
        setTotal(res.total)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load tickets.")
      } finally {
        setLoading(false)
      }
    },
    [status, priority],
  )

  useEffect(() => {
    load()
  }, [load])

  const scoped = useMemo(
    () => tickets.filter((t) => ticketInScope(t, scope, me?.id ?? "", teamId)),
    [tickets, scope, me?.id, teamId],
  )

  const columns = useMemo<DataTableColumn<TicketRow>[]>(
    () => [
      {
        key: "number",
        header: "Ticket",
        width: "130px",
        render: (t) => <span className="font-mono text-xs">{t.ticket_number}</span>,
      },
      {
        key: "title",
        header: "Title",
        render: (t) => (
          <div className="min-w-0">
            <p className="truncate font-medium text-fg-primary" title={t.title}>
              {t.title}
            </p>
            {t.category && <p className="truncate text-xs text-fg-muted">{t.category}</p>}
          </div>
        ),
      },
      {
        key: "severity",
        header: "Severity",
        width: "110px",
        render: (t) => <SeverityBadge severity={t.severity} />,
      },
      {
        key: "priority",
        header: "Priority",
        width: "90px",
        render: (t) => (t.priority ? <Badge tone={t.priority === "P1" ? "danger" : "brand"}>{t.priority}</Badge> : "--"),
      },
      {
        key: "status",
        header: "Status",
        width: "150px",
        render: (t) => <Badge tone="neutral">{TICKET_STATUS_LABELS[t.status] ?? t.status}</Badge>,
      },
      {
        key: "sla",
        header: "SLA",
        width: "130px",
        render: (t) => <Badge tone={slaBadgeTone(t.sla?.state ?? "none")}>{slaStateLabel(t.sla?.state ?? "none")}</Badge>,
      },
      {
        key: "assignee",
        header: "Assignee",
        width: "110px",
        render: (t) =>
          t.assigned_user_id ? (
            t.assigned_user_id === me?.id ? (
              "Me"
            ) : (
              <span title={t.assigned_user_id}>Teammate</span>
            )
          ) : t.assigned_team_id ? (
            "A team"
          ) : (
            <span className="text-fg-faint">Unassigned</span>
          ),
      },
      {
        key: "created",
        header: "Opened",
        width: "110px",
        render: (t) => (t.created_at ? new Date(t.created_at).toLocaleDateString() : "--"),
      },
    ],
    [me?.id],
  )

  const scopeOptions: ScopeOption[] = [
    { value: "mine", label: "Mine" },
    { value: "team", label: "Team" },
    { value: "all", label: "All in scope" },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">Tickets</h1>
          <p className="mt-0.5 text-xs text-fg-muted">
            Remediation work handed off from the SOC.{total > tickets.length ? ` ${total} total.` : ""}
          </p>
        </div>
        <IconButton icon={RefreshCw} label="Refresh tickets" onClick={load} />
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-3">
        <SegmentedControl
          options={scopeOptions}
          value={scope}
          onChange={(next) => setScope(next as TicketScope)}
          ariaLabel="Ticket scope"
        />
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className={selectClass}>
          <option value="">All statuses</option>
          {TICKET_STATUSES.map((s) => (
            <option key={s} value={s}>
              {TICKET_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select aria-label="Filter by priority" value={priority} onChange={(e) => setPriority(e.target.value)} className={selectClass}>
          <option value="">All priorities</option>
          {["P1", "P2", "P3", "P4"].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        {(status || priority || scope !== "mine") && (
          <button
            type="button"
            onClick={() => {
              setStatus("")
              setPriority("")
              setScope("mine")
            }}
            className="text-xs text-brand-400 hover:text-brand-300"
          >
            Clear filters
          </button>
        )}
      </div>

      {error ? (
        <div className="rounded-card border border-danger-fg/30 bg-surface p-6 text-center">
          <p className="text-sm text-danger-fg">{error}</p>
          <button
            type="button"
            onClick={load}
            className="mt-3 rounded-control border border-line px-3 py-1.5 text-xs text-fg-secondary hover:border-line-strong"
          >
            Try again
          </button>
        </div>
      ) : loading ? (
        <div className="space-y-2" role="status" aria-label="Loading tickets">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-control bg-surface-hover" style={{ animationDuration: "1.6s" }} />
          ))}
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={scoped}
          getRowId={(t) => t.id}
          ariaLabel="IT tickets"
          onRowActivate={(t) => navigate(`/it/tickets/${t.id}`)}
          emptyState={
            <EmptyState
              title="No tickets here"
              description={
                scope === "mine"
                  ? "Nothing is assigned to you right now. Check the Team or All views."
                  : "No tickets match these filters."
              }
            />
          }
        />
      )}

      {!loading && !error && tickets.length < total && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={async () => {
              try {
                const res = await apiListTickets({
                  status: status || undefined,
                  priority: priority || undefined,
                  limit: PAGE_SIZE,
                })
                setTickets((prev) => [...prev, ...res.tickets.filter((t) => !prev.some((p) => p.id === t.id))])
                setTotal(res.total)
              } catch (err) {
                toast.show(err instanceof ApiError ? err.message : "Could not load more tickets.", { tone: "danger" })
              }
            }}
            className="rounded-control border border-line bg-surface px-4 py-2 text-xs text-fg-secondary hover:border-line-strong hover:text-fg-primary"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  )
}

export default ItTickets
