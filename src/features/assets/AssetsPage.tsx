import { useCallback, useEffect, useMemo, useState } from "react"
import { Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react"

import Badge from "../../components/ui/Badge"
import Button from "../../components/ui/Button"
import ConfirmDialog from "../../components/ui/ConfirmDialog"
import DataTable, { type DataTableColumn } from "../../components/ui/DataTable"
import Dialog from "../../components/ui/Dialog"
import EmptyState from "../../components/EmptyState"
import IconButton from "../../components/ui/IconButton"
import SegmentedControl from "../../components/ui/SegmentedControl"
import Skeleton from "../../components/ui/Skeleton"
import { useToast } from "../../components/ui/Toast"

import {
  apiCreateAsset,
  apiGetAsset,
  apiGetAssetsLookup,
  apiListAssets,
  apiRetireAsset,
  apiSetAssetTags,
  apiUpdateAsset,
  ApiError,
  type AssetRow,
  type AssetsLookup,
} from "../../lib/api"

/**
 * The one Assets screen every organization-side role shares:
 *
 * - organization_admin (owner), security_manager: full write (backend
 *   computes per-row can_edit; both are always true here).
 * - it_developer: write on assets they own or that belong to their team
 *   only -- write controls render per-row from the backend's can_edit.
 * - soc_analyst, auditor: read-only (effective_modules.assets is "read",
 *   so write controls never render).
 *
 * The backend is the authority: a role with module-level read only never
 * sees a write control because effectiveWrite below is false, and even a
 * write-level role can't act on a specific retired/foreign row because
 * the backend's can_edit for that row is false. All this component does
 * is mirror what the server already decided.
 */

const ASSET_TYPES = [
  { value: "server", label: "Server" },
  { value: "workstation", label: "Workstation" },
  { value: "laptop", label: "Laptop" },
  { value: "network_device", label: "Network device" },
  { value: "firewall", label: "Firewall" },
  { value: "application", label: "Application" },
  { value: "api", label: "API" },
  { value: "database", label: "Database" },
  { value: "container", label: "Container" },
  { value: "cloud_resource", label: "Cloud resource" },
] as const

const CRITICALITIES = [
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
] as const

const ENVIRONMENTS = [
  { value: "production", label: "Production" },
  { value: "staging", label: "Staging" },
  { value: "development", label: "Development" },
] as const

const SORTS = [
  { value: "created_at_desc", label: "Newest" },
  { value: "created_at_asc", label: "Oldest" },
  { value: "name_asc", label: "Name A-Z" },
  { value: "name_desc", label: "Name Z-A" },
] as const

const CRITICALITY_TONE: Record<(typeof CRITICALITIES)[number]["value"], "danger" | "brand" | "neutral" | "success"> = {
  critical: "danger",
  high: "brand",
  medium: "neutral",
  low: "success",
}

const PAGE_SIZE = 25

export type AssetsPageProps = {
  /** "read" | "write" -- from useMe().effective_modules.assets. Governs
   * whether the create button, edit/retire/tag actions render at all. */
  access: "read" | "write"
  /** Optional fixed organization (platform SOC analyst viewing one of
   * their assigned managed organizations; the shared page is reused
   * read-only there with this set). */
  organizationId?: string
  /** Search placeholder naming the viewer, e.g. "your organization". */
  scopeLabel?: string
  title?: string
  description?: string
}

function labelFor(options: readonly { value: string; label: string }[], value: string | null | undefined): string {
  if (!value) return "--"
  return options.find((o) => o.value === value)?.label ?? value
}

type FormState = {
  name: string
  asset_type: string
  hostname: string
  ip_address: string
  operating_system: string
  environment: string
  criticality: string
  owner_user_id: string
  team_id: string
  description: string
  tags: string
}

const EMPTY_FORM: FormState = {
  name: "",
  asset_type: "server",
  hostname: "",
  ip_address: "",
  operating_system: "",
  environment: "",
  criticality: "medium",
  owner_user_id: "",
  team_id: "",
  description: "",
  tags: "",
}

function formFromAsset(asset: AssetRow): FormState {
  return {
    name: asset.name,
    asset_type: asset.asset_type,
    hostname: asset.hostname ?? "",
    ip_address: asset.ip_address ?? "",
    operating_system: asset.operating_system ?? "",
    environment: asset.environment ?? "",
    criticality: asset.criticality,
    owner_user_id: asset.owner_user_id ?? "",
    team_id: asset.team_id ?? "",
    description: asset.description ?? "",
    tags: asset.tags.join(", "),
  }
}

/** Create/edit dialog. Tags live in the same dialog as a comma-separated
 * editor; they're sent with the create payload and via PUT /tags on edit. */
function AssetDialog({
  open,
  asset,
  lookup,
  onClose,
  onSaved,
}: {
  open: boolean
  asset: AssetRow | null
  lookup: AssetsLookup | null
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  // Initialized once per mount: the parent keys this dialog on its open
  // state, so "create" and each "edit" session get a fresh form seeded
  // from the asset being edited -- no reset-effect needed.
  const [form, setForm] = useState<FormState>(() => (asset ? formFromAsset(asset) : EMPTY_FORM))
  const [saving, setSaving] = useState(false)

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  const parsedTags = form.tags.split(",").map((t) => t.trim()).filter(Boolean)

  async function save() {
    setSaving(true)
    try {
      const payload = {
        name: form.name,
        asset_type: form.asset_type,
        hostname: form.hostname || null,
        ip_address: form.ip_address || null,
        operating_system: form.operating_system || null,
        environment: form.environment || null,
        criticality: form.criticality,
        owner_user_id: form.owner_user_id || null,
        team_id: form.team_id || null,
        description: form.description || null,
        tags: parsedTags,
      }
      if (asset) {
        // Tags go through their own replace-all endpoint on edit; the
        // PATCH payload doesn't carry them.
        const { tags, ...patch } = payload
        await apiUpdateAsset(asset.id, patch)
        await apiSetAssetTags(asset.id, tags)
      } else {
        await apiCreateAsset(payload)
      }
      toast.show(asset ? "Asset updated." : "Asset created.", { tone: "success" })
      onSaved()
      onClose()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not save this asset.", { tone: "danger" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={asset ? `Edit ${asset.name}` : "Create asset"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void save()} disabled={!form.name.trim()} loading={saving}>
            {asset ? "Save changes" : "Create asset"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Name *</span>
          <input
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Type</span>
            <select
              value={form.asset_type}
              onChange={(e) => set("asset_type", e.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              {ASSET_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Criticality</span>
            <select
              value={form.criticality}
              onChange={(e) => set("criticality", e.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              {CRITICALITIES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Hostname</span>
            <input
              value={form.hostname}
              onChange={(e) => set("hostname", e.target.value)}
              placeholder="optional, unique per organization"
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">IP address</span>
            <input
              value={form.ip_address}
              onChange={(e) => set("ip_address", e.target.value)}
              placeholder="e.g. 10.0.0.5"
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Operating system</span>
            <input
              value={form.operating_system}
              onChange={(e) => set("operating_system", e.target.value)}
              placeholder="e.g. Ubuntu 22.04"
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Environment</span>
            <select
              value={form.environment}
              onChange={(e) => set("environment", e.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              <option value="">Not set</option>
              {ENVIRONMENTS.map((env) => (
                <option key={env.value} value={env.value}>{env.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Owner</span>
            <select
              value={form.owner_user_id}
              onChange={(e) => set("owner_user_id", e.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              <option value="">Unassigned</option>
              {(lookup?.users ?? []).map((u) => (
                <option key={u.id} value={u.id}>{u.name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">Team</span>
            <select
              value={form.team_id}
              onChange={(e) => set("team_id", e.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            >
              <option value="">No team</option>
              {(lookup?.teams ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
        </div>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Description</span>
          <textarea
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
            rows={2}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-fg-muted">Tags</span>
          <input
            value={form.tags}
            onChange={(e) => set("tags", e.target.value)}
            placeholder="comma-separated, e.g. prod, edge"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
          {parsedTags.length > 0 && (
            <span className="mt-1.5 flex flex-wrap gap-1">
              {parsedTags.map((tag, i) => (
                <Badge key={`${tag}-${i}`} tone="neutral">{tag}</Badge>
              ))}
            </span>
          )}
        </label>
      </div>
    </Dialog>
  )
}

/**
 * The shared assets screen. Every organization-side role renders this;
 * what differs is `access` (from their effective_modules) and the
 * per-row can_edit the backend stamps on each asset.
 */
function AssetsPage({
  access,
  organizationId,
  scopeLabel = "your organization",
  title = "Assets",
  description,
}: AssetsPageProps) {
  const { show: showToast } = useToast()
  const canWrite = access === "write"

  const [rows, setRows] = useState<AssetRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [assetType, setAssetType] = useState("")
  const [criticality, setCriticality] = useState("")
  const [status, setStatus] = useState("")
  const [tag, setTag] = useState("")
  const [sort, setSort] = useState<(typeof SORTS)[number]["value"]>("created_at_desc")
  const [page, setPage] = useState(1)

  const [lookup, setLookup] = useState<AssetsLookup | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<AssetRow | null>(null)
  const [retireTarget, setRetireTarget] = useState<AssetRow | null>(null)
  const [retiring, setRetiring] = useState(false)

  /** A viewer with module-level write but per-row read-only (an IT
   * developer looking at someone else's asset) can't act on that row, so
   * no edit affordance renders for it and this never fires for them.
   * The dialog still fetches by id rather than trusting the list row so
   * the form is always editing what's actually in the database now. */
  const openEdit = useCallback(
    function openEdit(row: AssetRow) {
      // Fetch before opening so the dialog mounts already seeded with the
      // asset, rather than flashing an empty create-style form.
      apiGetAsset(row.id, organizationId)
        .then((asset) => {
          setEditTarget(asset)
          setDialogOpen(true)
        })
        .catch(() => showToast("Could not load this asset for editing.", { tone: "danger" }))
    },
    [organizationId, showToast],
  )

  /** Filters narrow the result set -- a stale page can end up past the
   * new last page, so every filter change also goes back to page 1. */
  function filterChange(setter: (value: string) => void, value: string) {
    setter(value)
    setPage(1)
  }

  const load = useCallback(() => {
    setLoading(true)
    setLoadError("")
    apiListAssets({
      organization_id: organizationId,
      q: search || undefined,
      asset_type: assetType || undefined,
      criticality: criticality || undefined,
      status: status || undefined,
      tag: tag || undefined,
      sort,
      page,
      page_size: PAGE_SIZE,
    })
      .then((res) => {
        setRows(res.assets)
        setTotal(res.total)
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load assets."))
      .finally(() => setLoading(false))
  }, [organizationId, search, assetType, criticality, status, tag, sort, page])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!canWrite) return
    apiGetAssetsLookup(organizationId)
      .then(setLookup)
      .catch(() => setLookup(null)) // pickers just render empty; not fatal
  }, [canWrite, organizationId])

  const allTags = useMemo(() => {
    const set = new Set<string>()
    for (const row of rows) for (const t of row.tags) set.add(t)
    return [...set].sort()
  }, [rows])

  async function retire() {
    if (!retireTarget) return
    setRetiring(true)
    try {
      await apiRetireAsset(retireTarget.id)
      showToast(`${retireTarget.name} retired.`, { tone: "success" })
      load()
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Could not retire this asset.", { tone: "danger" })
    } finally {
      setRetiring(false)
      setRetireTarget(null)
    }
  }

  const columns = useMemo<DataTableColumn<AssetRow>[]>(() => {
    const base: DataTableColumn<AssetRow>[] = [
      {
        key: "name",
        header: "Name",
        sortValue: (row) => row.name,
        render: (row) => (
          <div>
            <p className="font-medium text-fg-primary">{row.name}</p>
            {row.hostname && <p className="text-xs text-fg-muted">{row.hostname}</p>}
          </div>
        ),
      },
      {
        key: "type",
        header: "Type",
        sortValue: (row) => row.asset_type,
        render: (row) => labelFor(ASSET_TYPES, row.asset_type),
      },
      {
        key: "criticality",
        header: "Criticality",
        sortValue: (row) => row.criticality,
        render: (row) => <Badge tone={CRITICALITY_TONE[row.criticality]}>{row.criticality}</Badge>,
      },
      { key: "environment", header: "Environment", render: (row) => labelFor(ENVIRONMENTS, row.environment) },
      { key: "owner", header: "Owner", render: (row) => row.owner_name ?? "--" },
      { key: "team", header: "Team", render: (row) => row.team_name ?? "--" },
      {
        key: "status",
        header: "Status",
        sortValue: (row) => row.status,
        render: (row) => (
          <Badge tone={row.status === "active" ? "success" : "neutral"}>{row.status}</Badge>
        ),
      },
      {
        key: "tags",
        header: "Tags",
        render: (row) =>
          row.tags.length === 0 ? (
            <span className="text-fg-faint">--</span>
          ) : (
            <span className="flex flex-wrap gap-1">
              {row.tags.map((t) => (
                <Badge key={t} tone="neutral">{t}</Badge>
              ))}
            </span>
          ),
      },
    ]
    if (canWrite) {
      base.push({
        key: "actions",
        header: "",
        render: (row) =>
          row.can_edit ? (
            <span className="flex items-center justify-end gap-1">
              <IconButton icon={Pencil} label={`Edit ${row.name}`} onClick={() => openEdit(row)} />
              <IconButton
                icon={Trash2}
                label={`Retire ${row.name}`}
                onClick={() => setRetireTarget(row)}
                disabled={row.status === "retired"}
              />
            </span>
          ) : null,
      })
    }
    return base
  }, [canWrite, openEdit])

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary">{title}</h1>
          {description && <p className="mt-1 text-xs text-fg-muted">{description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <IconButton icon={RefreshCw} label="Refresh assets" onClick={load} />
          {canWrite && (
            <Button
              variant="primary"
              icon={<Plus size={16} />}
              onClick={() => {
                setEditTarget(null)
                setDialogOpen(true)
              }}
            >
              Create asset
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint" aria-hidden="true" />
          <input
            value={searchInput}
            onChange={(e) => {
              setSearchInput(e.target.value)
              filterChange(setSearch, e.target.value.trim())
            }}
            placeholder={`Search ${scopeLabel}...`}
            aria-label="Search assets"
            className="w-56 rounded-control border border-line bg-surface py-2 pl-8 pr-3 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>

        <select
          value={assetType}
          onChange={(e) => filterChange(setAssetType, e.target.value)}
          aria-label="Filter by type"
          className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        >
          <option value="">All types</option>
          {ASSET_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>

        <select
          value={criticality}
          onChange={(e) => filterChange(setCriticality, e.target.value)}
          aria-label="Filter by criticality"
          className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        >
          <option value="">All criticalities</option>
          {CRITICALITIES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>

        <select
          value={status}
          onChange={(e) => filterChange(setStatus, e.target.value)}
          aria-label="Filter by status"
          className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="retired">Retired</option>
        </select>

        <select
          value={tag}
          onChange={(e) => filterChange(setTag, e.target.value)}
          aria-label="Filter by tag"
          className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        >
          <option value="">All tags</option>
          {allTags.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <SegmentedControl options={SORTS} value={sort} onChange={setSort} ariaLabel="Sort order" />
      </div>

      {loading ? (
        <Skeleton count={5} className="h-10 w-full" />
      ) : loadError ? (
        <EmptyState title="Couldn't load assets" description={loadError} action={{ label: "Retry", onClick: load }} />
      ) : (
        <>
          <DataTable
            ariaLabel="Assets"
            columns={columns}
            rows={rows}
            getRowId={(row) => row.id}
            emptyState={
              <EmptyState
                title="No assets yet"
                description={
                  canWrite
                    ? "Create your first asset -- everything else (events, alerts, incidents) points at one."
                    : "No assets match the current filters."
                }
              />
            }
          />
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between text-xs text-fg-muted">
              <span>
                {total} asset{total === 1 ? "" : "s"} &middot; page {page} of {pageCount}
              </span>
              <span className="flex gap-2">
                <Button variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </Button>
                <Button variant="ghost" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>
                  Next
                </Button>
              </span>
            </div>
          )}
        </>
      )}

      {canWrite && (
        <>
          <AssetDialog
            key={dialogOpen ? "asset-dialog-open" : "asset-dialog-closed"}
            open={dialogOpen}
            asset={editTarget}
            lookup={lookup}
            onClose={() => {
              setDialogOpen(false)
              setEditTarget(null)
            }}
            onSaved={load}
          />
          <ConfirmDialog
            open={retireTarget !== null}
            onClose={() => setRetireTarget(null)}
            onConfirm={() => void retire()}
            title={`Retire ${retireTarget?.name}?`}
            impact="The asset stays in the inventory but is marked retired -- history that references it is preserved."
            confirmLabel={retiring ? "Retiring..." : "Retire"}
            danger
          />
        </>
      )}
    </div>
  )
}

export default AssetsPage
