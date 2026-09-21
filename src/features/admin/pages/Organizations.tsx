import { useCallback, useEffect, useState } from "react"
import { ChevronLeft, ChevronRight, MoreVertical, Plus, Search } from "lucide-react"
import { useNavigate } from "react-router-dom"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import DropdownMenu, { type DropdownMenuItem } from "../../../components/ui/DropdownMenu"
import IconButton from "../../../components/ui/IconButton"
import { useToast } from "../../../components/ui/Toast"
import CreateOrganizationDialog from "../components/CreateOrganizationDialog"

import {
  apiArchiveOrganization,
  apiListOrganizations,
  apiReactivateOrganization,
  apiSuspendOrganization,
  ApiError,
  type OrganizationRow,
} from "../../../lib/api"

const STATUS_TONE: Record<OrganizationRow["status"], "brand" | "success" | "danger" | "neutral"> = {
  active: "success",
  suspended: "danger",
  archived: "neutral",
}

const PAGE_SIZE = 25

function relativeTime(iso: string | null): string {
  if (!iso) return "Never"
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return "Just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

type PendingAction =
  | { type: "suspend"; org: OrganizationRow }
  | { type: "archive"; org: OrganizationRow }

/**
 * Platform admin: organizations list (Prompt B section A1). Search and
 * the status/soc_mode filters hit the backend; column-header sorting
 * (DataTable's built-in sortValue) re-orders the current page locally.
 * See docs/API_CONTRACT.md ("GET /admin/organizations").
 */
function Organizations() {
  const navigate = useNavigate()
  const toast = useToast()

  const [searchInput, setSearchInput] = useState("")
  const [q, setQ] = useState("")
  const [status, setStatus] = useState("")
  const [socMode, setSocMode] = useState("")
  const [page, setPage] = useState(1)

  const [rows, setRows] = useState<OrganizationRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [createOpen, setCreateOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [actionBusyId, setActionBusyId] = useState<string | null>(null)

  // Debounce the search box -- refetch 300ms after the user stops typing.
  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1)
      setQ(searchInput.trim())
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  const load = useCallback(() => {
    setLoading(true)
    setLoadError("")
    apiListOrganizations({
      q: q || undefined,
      status: status || undefined,
      soc_mode: socMode || undefined,
      page,
      page_size: PAGE_SIZE,
    })
      .then((res) => {
        setRows(res.organizations)
        setTotal(res.total)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "Could not load organizations.")
      })
      .finally(() => setLoading(false))
  }, [q, status, socMode, page])

  useEffect(() => {
    load()
  }, [load])

  async function handleReactivate(org: OrganizationRow) {
    setActionBusyId(org.id)
    try {
      await apiReactivateOrganization(org.id)
      toast.show(`${org.name} reactivated.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not reactivate this organization.", {
        tone: "danger",
      })
    } finally {
      setActionBusyId(null)
    }
  }

  async function handleConfirmAction(reason?: string) {
    if (!pendingAction) return
    const { type, org } = pendingAction
    setActionBusyId(org.id)
    try {
      if (type === "suspend") {
        await apiSuspendOrganization(org.id, reason ?? "")
        toast.show(`${org.name} suspended.`, { tone: "success" })
      } else {
        await apiArchiveOrganization(org.id)
        toast.show(`${org.name} archived.`, { tone: "success" })
      }
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not complete this action.", {
        tone: "danger",
      })
    } finally {
      setActionBusyId(null)
    }
  }

  function rowActions(org: OrganizationRow): DropdownMenuItem[] {
    const items: DropdownMenuItem[] = [
      {
        key: "view",
        label: "View details",
        onSelect: () => navigate(`/admin/organizations/${org.id}`),
      },
    ]

    if (org.status === "active") {
      items.push(
        {
          key: "suspend",
          label: "Suspend",
          danger: true,
          onSelect: () => setPendingAction({ type: "suspend", org }),
        },
        {
          key: "archive",
          label: "Archive",
          danger: true,
          onSelect: () => setPendingAction({ type: "archive", org }),
        },
      )
    } else if (org.status === "suspended") {
      items.push(
        { key: "reactivate", label: "Reactivate", onSelect: () => void handleReactivate(org) },
        {
          key: "archive",
          label: "Archive",
          danger: true,
          onSelect: () => setPendingAction({ type: "archive", org }),
        },
      )
    }

    return items
  }

  const columns: DataTableColumn<OrganizationRow>[] = [
    {
      key: "name",
      header: "Name",
      sortValue: (r) => r.name.toLowerCase(),
      render: (r) => (
        <button
          type="button"
          onClick={() => navigate(`/admin/organizations/${r.id}`)}
          className="font-medium text-fg-primary hover:text-brand-400"
        >
          {r.name}
        </button>
      ),
    },
    {
      key: "owner",
      header: "Owner",
      sortValue: (r) => r.owner?.email.toLowerCase() ?? "",
      render: (r) =>
        r.owner ? (
          <div>
            <p className="text-fg-secondary">{r.owner.name}</p>
            <p className="text-xs text-fg-muted">{r.owner.email}</p>
          </div>
        ) : (
          <span className="text-fg-faint">Awaiting invite acceptance</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      width: "110px",
      sortValue: (r) => r.status,
      render: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>,
    },
    {
      key: "soc_mode",
      header: "SOC mode",
      width: "110px",
      sortValue: (r) => r.soc_mode,
      render: (r) => <Badge tone="neutral">{r.soc_mode === "managed" ? "Managed" : "In-house"}</Badge>,
    },
    {
      key: "members",
      header: "Members",
      width: "90px",
      sortValue: (r) => r.members,
      render: (r) => r.members,
    },
    {
      key: "pending_invitations",
      header: "Pending invites",
      width: "110px",
      sortValue: (r) => r.pending_invitations,
      render: (r) => r.pending_invitations,
    },
    {
      key: "assets",
      header: "Assets",
      width: "80px",
      sortValue: (r) => r.assets,
      render: (r) => r.assets,
    },
    {
      key: "open_incidents",
      header: "Open incidents",
      width: "110px",
      sortValue: (r) => r.open_incidents,
      render: (r) => r.open_incidents,
    },
    {
      key: "open_tickets",
      header: "Open tickets",
      width: "100px",
      sortValue: (r) => r.open_tickets,
      render: (r) => r.open_tickets,
    },
    {
      key: "last_activity",
      header: "Last activity",
      width: "120px",
      sortValue: (r) => r.last_activity_at ?? "",
      render: (r) => <span title={r.last_activity_at ?? undefined}>{relativeTime(r.last_activity_at)}</span>,
    },
    {
      key: "actions",
      header: "",
      width: "48px",
      render: (r) => {
        const items = rowActions(r)
        if (items.length === 0) return null
        return (
          <DropdownMenu
            label={`Actions for ${r.name}`}
            align="right"
            trigger={
              <IconButton
                icon={MoreVertical}
                label={`Actions for ${r.name}`}
                disabled={actionBusyId === r.id}
              />
            }
            items={items}
          />
        )
      },
    },
  ]

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">Organizations</h1>
              <p className="mt-1 text-xs text-fg-muted">
                Every organization on the platform -- manage owner invitations, status and SOC mode.
              </p>
            </div>
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>
              Create organization
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[240px] flex-1">
              <Search
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted"
                aria-hidden="true"
              />
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search by name or owner email..."
                aria-label="Search organizations"
                className="w-full rounded-control border border-line bg-surface py-2 pl-9 pr-3 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              />
            </div>

            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value)
                setPage(1)
              }}
              aria-label="Filter by status"
              className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
              <option value="archived">Archived</option>
            </select>

            <select
              value={socMode}
              onChange={(e) => {
                setSocMode(e.target.value)
                setPage(1)
              }}
              aria-label="Filter by SOC mode"
              className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              <option value="">All SOC modes</option>
              <option value="managed">Managed</option>
              <option value="in_house">In-house</option>
            </select>
          </div>

          {loadError && !loading ? (
            <EmptyState
              title="Couldn't load organizations"
              description={loadError}
              action={{ label: "Retry", onClick: load }}
            />
          ) : (
            <DataTable
              columns={columns}
              rows={rows}
              getRowId={(r) => r.id}
              ariaLabel="Organizations"
              loading={loading}
              emptyState={
                <EmptyState
                  title="No organizations found"
                  description="Try adjusting your search or filters, or create a new organization."
                />
              }
            />
          )}

          {!loading && !loadError && total > 0 && (
            <div className="flex items-center justify-between text-xs text-fg-muted">
              <span>
                Page {page} of {totalPages} &middot; {total} organization{total === 1 ? "" : "s"}
              </span>
              <div className="flex items-center gap-2">
                <IconButton
                  icon={ChevronLeft}
                  label="Previous page"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                />
                <IconButton
                  icon={ChevronRight}
                  label="Next page"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                />
              </div>
            </div>
          )}
        </div>
      </main>

      <CreateOrganizationDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          toast.show("Organization created. The owner will get an invitation email.", { tone: "success" })
          setPage(1)
          load()
        }}
      />

      <ConfirmDialog
        open={pendingAction !== null}
        onClose={() => setPendingAction(null)}
        onConfirm={(reason) => void handleConfirmAction(reason)}
        title={
          pendingAction?.type === "suspend"
            ? `Suspend ${pendingAction.org.name}?`
            : `Archive ${pendingAction?.org.name}?`
        }
        impact={
          pendingAction?.type === "suspend"
            ? "Members of this organization will not be able to sign in until it's reactivated."
            : "This organization will be archived. Archiving is terminal and cannot be undone."
        }
        requireReason={pendingAction?.type === "suspend"}
        confirmLabel={pendingAction?.type === "suspend" ? "Suspend" : "Archive"}
        danger
      />
    </div>
  )
}

export default Organizations
