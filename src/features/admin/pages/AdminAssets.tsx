import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { RefreshCw, Search } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import EmptyState from "../../../components/EmptyState"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"

import {
  apiGetAdminAssets,
  ApiError,
  type AdminAssetRow,
  type AdminAssetsResponse,
} from "../../../lib/api"

const ASSET_TYPES = [
  { value: "", label: "All Types" },
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
]

const CRITICALITIES = [
  { value: "", label: "All Criticalities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
]

export default function AdminAssets() {
  const toast = useToast()

  const [data, setData] = useState<AdminAssetsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  // Filters
  const [q, setQ] = useState("")
  const [selectedOrgId, setSelectedOrgId] = useState("")
  const [selectedType, setSelectedType] = useState("")
  const [selectedCriticality, setSelectedCriticality] = useState("")
  const [selectedStatus, setSelectedStatus] = useState("")
  const [page, setPage] = useState(1)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGetAdminAssets({
        organization_id: selectedOrgId || undefined,
        q: q.trim() || undefined,
        asset_type: selectedType || undefined,
        criticality: selectedCriticality || undefined,
        status: selectedStatus || undefined,
        page,
        page_size: 25,
      })
      setData(res)
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to load assets.", {
        tone: "danger",
      })
    } finally {
      setLoading(false)
    }
  }, [selectedOrgId, q, selectedType, selectedCriticality, selectedStatus, page, toast])

  useEffect(() => {
    reload()
  }, [reload])

  const columns: DataTableColumn<AdminAssetRow>[] = [
    {
      key: "name",
      header: "Asset",
      render: (a) => (
        <div>
          <p className="font-medium text-fg-primary">{a.name}</p>
          {a.description ? (
            <p className="line-clamp-1 text-xs text-fg-muted">{a.description}</p>
          ) : (
            <p className="text-xs text-fg-faint">No description</p>
          )}
        </div>
      ),
    },
    {
      key: "organization",
      header: "Organization",
      render: (a) => (
        <Link
          to={`/admin/organizations/${a.organization_id}`}
          className="text-xs font-medium text-brand-300 hover:underline"
        >
          {a.organization_name}
        </Link>
      ),
    },
    {
      key: "type",
      header: "Type & Env",
      render: (a) => (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-fg-secondary capitalize">{a.asset_type.replace("_", " ")}</span>
          <span className="font-mono text-[10px] text-fg-muted">{a.environment}</span>
        </div>
      ),
    },
    {
      key: "network",
      header: "Host / IP",
      render: (a) => (
        <div className="font-mono text-xs">
          <p className="text-fg-primary">{a.hostname}</p>
          <p className="text-[11px] text-fg-muted">{a.ip_address}</p>
        </div>
      ),
    },
    {
      key: "criticality",
      header: "Criticality",
      width: "110px",
      render: (a) => {
        const toneMap: Record<string, "danger" | "brand" | "neutral"> = {
          critical: "danger",
          high: "danger",
          medium: "brand",
          low: "neutral",
        }
        return (
          <Badge tone={toneMap[a.criticality] || "neutral"} className="capitalize">
            {a.criticality}
          </Badge>
        )
      },
    },
    {
      key: "status",
      header: "Status",
      width: "90px",
      render: (a) => (
        <Badge tone={a.status === "active" ? "success" : "neutral"} className="capitalize">
          {a.status}
        </Badge>
      ),
    },
    {
      key: "created_at",
      header: "Added",
      width: "110px",
      render: (a) => (
        <span className="text-xs text-fg-muted">
          {a.created_at ? new Date(a.created_at).toLocaleDateString() : "N/A"}
        </span>
      ),
    },
  ]

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / (data?.page_size ?? 25)))

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">Assets Inventory</h1>
              <p className="mt-1 text-xs text-fg-muted">
                Complete infrastructure inventory across all registered SentinelX organizations.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <IconButton icon={RefreshCw} label="Refresh assets" onClick={reload} />
            </div>
          </div>

          {/* Key Metrics */}
          <section aria-label="Asset metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {loading && !data ? (
              Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)
            ) : (
              <>
                <KpiCard label="Total Assets" value={String(data?.kpis.total ?? 0)} tone="neutral" />
                <KpiCard label="Active" value={String(data?.kpis.active ?? 0)} tone="neutral" />
                <KpiCard
                  label="Critical Assets"
                  value={String(data?.kpis.critical ?? 0)}
                  tone={(data?.kpis.critical ?? 0) > 0 ? "critical" : "neutral"}
                />
                <KpiCard label="Retired" value={String(data?.kpis.retired ?? 0)} tone="neutral" />
              </>
            )}
          </section>

          {/* Filters Bar */}
          <section aria-label="Asset filters" className="rounded-card border border-line bg-surface p-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {/* Search */}
              <div className="relative">
                <Search size={14} className="absolute left-3 top-2.5 text-fg-muted" />
                <input
                  type="text"
                  placeholder="Search name, host, IP..."
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value)
                    setPage(1)
                  }}
                  className="w-full rounded-control border border-line bg-surface-sunken py-1.5 pl-8 pr-3 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                />
              </div>

              {/* Organization filter */}
              <select
                value={selectedOrgId}
                onChange={(e) => {
                  setSelectedOrgId(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by organization"
                className="rounded-control border border-line bg-surface-sunken px-3 py-1.5 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                <option value="">All Organizations</option>
                {data?.organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>

              {/* Asset Type */}
              <select
                value={selectedType}
                onChange={(e) => {
                  setSelectedType(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by asset type"
                className="rounded-control border border-line bg-surface-sunken px-3 py-1.5 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                {ASSET_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>

              {/* Criticality */}
              <select
                value={selectedCriticality}
                onChange={(e) => {
                  setSelectedCriticality(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by criticality"
                className="rounded-control border border-line bg-surface-sunken px-3 py-1.5 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                {CRITICALITIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>

              {/* Status */}
              <select
                value={selectedStatus}
                onChange={(e) => {
                  setSelectedStatus(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by status"
                className="rounded-control border border-line bg-surface-sunken px-3 py-1.5 text-xs text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                <option value="">All Statuses</option>
                <option value="active">Active</option>
                <option value="retired">Retired</option>
              </select>
            </div>
          </section>

          {/* Assets Data Table */}
          <section aria-label="Assets table">
            <DataTable
              columns={columns}
              rows={data?.assets ?? []}
              getRowId={(a) => a.id}
              ariaLabel="Platform assets"
              loading={loading && !data}
              emptyState={
                <EmptyState
                  title="No assets found"
                  description="No infrastructure assets match the active filters or search criteria."
                />
              }
            />

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-4 flex items-center justify-between text-xs text-fg-muted">
                <p>
                  Showing {data?.assets.length ?? 0} of {data?.total ?? 0} asset(s)
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    className="px-3 py-1 text-xs"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </Button>
                  <span>
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    variant="secondary"
                    className="px-3 py-1 text-xs"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}
