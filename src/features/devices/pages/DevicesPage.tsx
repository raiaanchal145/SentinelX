import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  KeyRound,
  Laptop,
  Monitor,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  apiGetDevicesSummary,
  apiListDevices,
  type DeviceRow,
  type DevicesSummary,
  type DeviceStatus,
} from "../../../lib/devicesApi"
import { useMe } from "../../../lib/me"
import AddDeviceDialog from "../components/AddDeviceDialog"

function statusTone(status: DeviceStatus): "success" | "brand" | "neutral" | "danger" {
  switch (status) {
    case "connected":
      return "success"
    case "pending_consent":
      return "brand"
    case "stale":
      return "brand"
    case "offline":
    case "expired":
      return "neutral"
    case "revoked":
      return "danger"
    default:
      return "neutral"
  }
}

function statusLabel(status: DeviceStatus): string {
  switch (status) {
    case "connected":
      return "Connected (< 2m)"
    case "stale":
      return "Stale (2-10m)"
    case "offline":
      return "Offline (> 10m)"
    case "pending_consent":
      return "Pending Consent"
    case "revoked":
      return "Revoked"
    case "expired":
      return "Token Expired"
    default:
      return status
  }
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "Never"
  const diffMs = Date.now() - new Date(iso).getTime()
  if (diffMs < 0) return "Just now"
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHours = Math.floor(diffMin / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

export default function DevicesPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { me } = useMe()

  // Module write access check (organization_admin, security_manager, or it_developer with write access)
  const canWrite =
    me?.role === "organization_admin" ||
    me?.effective_modules?.device_agents === "write" ||
    me?.effective_modules?.assets === "write"

  const [devices, setDevices] = useState<DeviceRow[]>([])
  const [summary, setSummary] = useState<DevicesSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [addModalOpen, setAddModalOpen] = useState(false)

  const loadData = useCallback(() => {
    setLoading(true)
    Promise.all([apiListDevices(), apiGetDevicesSummary()])
      .then(([devRes, sumRes]) => {
        setDevices(devRes.devices)
        setSummary(sumRes)
      })
      .catch((err) => {
        toast.show(err instanceof Error ? err.message : "Failed to load endpoint devices.", { tone: "danger" })
      })
      .finally(() => setLoading(false))
  }, [toast])

  useEffect(() => {
    loadData()
  }, [loadData])

  const filteredDevices = useMemo(() => {
    return devices.filter((d) => {
      if (statusFilter !== "all" && d.status !== statusFilter) return false
      if (!search.trim()) return true
      const term = search.toLowerCase()
      return (
        d.asset_name.toLowerCase().includes(term) ||
        (d.device_name && d.device_name.toLowerCase().includes(term)) ||
        (d.hostname && d.hostname.toLowerCase().includes(term)) ||
        (d.operating_system && d.operating_system.toLowerCase().includes(term)) ||
        (d.ip_address && d.ip_address.toLowerCase().includes(term))
      )
    })
  }, [devices, statusFilter, search])

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-fg-primary flex items-center gap-2">
            <Monitor className="text-brand-400" size={24} />
            Endpoint Devices &amp; Agents
          </h1>
          <p className="mt-1 text-xs text-fg-muted">
            Consent-based workstation and server monitoring with telemetry control.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <IconButton icon={RefreshCw} label="Refresh devices" onClick={loadData} />
          {canWrite && (
            <Button
              variant="primary"
              icon={<Plus size={16} />}
              onClick={() => setAddModalOpen(true)}
            >
              Add Device
            </Button>
          )}
        </div>
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="rounded-card border border-line bg-surface p-4">
          <div className="flex items-center justify-between text-xs text-fg-muted">
            <span>Total Endpoints</span>
            <Laptop size={16} className="text-fg-subtle" />
          </div>
          <div className="mt-2 text-2xl font-bold text-fg-primary">
            {summary ? summary.total : <Skeleton className="h-7 w-12" />}
          </div>
        </div>

        <div className="rounded-card border border-emerald-500/20 bg-emerald-500/5 p-4">
          <div className="flex items-center justify-between text-xs text-emerald-400">
            <span>Connected (&le; 2m)</span>
            <CheckCircle2 size={16} />
          </div>
          <div className="mt-2 text-2xl font-bold text-emerald-400">
            {summary ? summary.connected : <Skeleton className="h-7 w-12" />}
          </div>
        </div>

        <div className="rounded-card border border-amber-500/20 bg-amber-500/5 p-4">
          <div className="flex items-center justify-between text-xs text-amber-400">
            <span>Stale (2-10m)</span>
            <Clock size={16} />
          </div>
          <div className="mt-2 text-2xl font-bold text-amber-400">
            {summary ? summary.stale : <Skeleton className="h-7 w-12" />}
          </div>
        </div>

        <div className="rounded-card border border-line bg-surface p-4">
          <div className="flex items-center justify-between text-xs text-fg-muted">
            <span>Offline (&gt; 10m)</span>
            <AlertTriangle size={16} className="text-fg-faint" />
          </div>
          <div className="mt-2 text-2xl font-bold text-fg-muted">
            {summary ? summary.offline : <Skeleton className="h-7 w-12" />}
          </div>
        </div>

        <div className="rounded-card border border-brand/20 bg-brand/5 p-4">
          <div className="flex items-center justify-between text-xs text-brand">
            <span>Pending Consent</span>
            <KeyRound size={16} />
          </div>
          <div className="mt-2 text-2xl font-bold text-brand">
            {summary ? summary.pending_consent : <Skeleton className="h-7 w-12" />}
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by device, asset, OS..."
            className="w-full rounded-control border border-line bg-surface py-2 pl-9 pr-3 text-xs text-fg-primary placeholder-fg-faint outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {["all", "connected", "stale", "offline", "pending_consent", "revoked"].map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => setStatusFilter(st)}
              className={`rounded-control px-3 py-1.5 text-xs font-medium transition ${
                statusFilter === st
                  ? "bg-brand text-brand-fg"
                  : "bg-surface border border-line text-fg-muted hover:text-fg-primary"
              }`}
            >
              {st === "all" ? "All Endpoints" : statusLabel(st as DeviceStatus)}
            </button>
          ))}
        </div>
      </div>

      {/* Device List Table */}
      <div className="overflow-hidden rounded-card border border-line bg-surface">
        {loading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        ) : filteredDevices.length === 0 ? (
          <div className="p-8">
            <EmptyState
              title={devices.length === 0 ? "No endpoint devices enrolled" : "No devices match filter"}
              description={
                devices.length === 0
                  ? "Endpoints with SentinelX agents stream telemetry once authorized by device owners."
                  : "Try clearing search or changing the status filter."
              }
              action={
                canWrite && devices.length === 0
                  ? {
                      label: "Enroll First Device",
                      icon: <Plus size={16} />,
                      onClick: () => setAddModalOpen(true),
                    }
                  : undefined
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-line bg-surface-sunken text-fg-muted font-medium">
                <tr>
                  <th className="px-4 py-3">Device / Asset</th>
                  <th className="px-4 py-3">Platform</th>
                  <th className="px-4 py-3">Agent Status</th>
                  <th className="px-4 py-3">Consent Policy</th>
                  <th className="px-4 py-3">Last Heartbeat</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {filteredDevices.map((device) => {
                  const isRevoked = device.status === "revoked"
                  const isPending = device.status === "pending_consent"
                  const isConnected = device.status === "connected"

                  return (
                    <tr
                      key={device.id}
                      className="hover:bg-surface-muted/50 transition cursor-pointer"
                      onClick={() => navigate(`/devices/${device.id}`)}
                    >
                      <td className="px-4 py-3.5">
                        <div className="font-medium text-fg-primary">
                          {device.device_name || device.asset_name}
                        </div>
                        <div className="text-[11px] text-fg-muted">
                          Asset: {device.asset_name} ({device.asset_type})
                          {device.hostname ? ` • ${device.hostname}` : ""}
                        </div>
                      </td>

                      <td className="px-4 py-3.5">
                        <div className="text-fg-secondary">
                          {device.operating_system || "Unknown OS"}
                        </div>
                        <div className="text-[11px] text-fg-muted">
                          Agent v{device.agent_version || "1.0.0"}
                        </div>
                      </td>

                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5">
                          {isConnected && (
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                            </span>
                          )}
                          <Badge tone={statusTone(device.status)}>
                            {statusLabel(device.status)}
                          </Badge>
                        </div>
                      </td>

                      <td className="px-4 py-3.5">
                        {isRevoked ? (
                          <span className="text-danger flex items-center gap-1">
                            <XCircle size={14} /> Ingestion blocked
                          </span>
                        ) : isPending ? (
                          <span className="text-brand flex items-center gap-1">
                            <Clock size={14} /> Consent required
                          </span>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <ShieldCheck size={14} className="text-emerald-400" />
                            <span className="font-medium text-fg-primary">
                              {device.categories_granted.length} categories
                            </span>
                            <span className="text-[11px] text-fg-muted">
                              ({device.categories_granted.slice(0, 2).join(", ")}
                              {device.categories_granted.length > 2 ? "..." : ""})
                            </span>
                          </div>
                        )}
                      </td>

                      <td className="px-4 py-3.5 text-fg-muted">
                        <div>{formatRelativeTime(device.last_heartbeat_at || device.last_seen_at)}</div>
                        {device.last_heartbeat_at && (
                          <div className="text-[10px] text-fg-faint">
                            {new Date(device.last_heartbeat_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })}
                          </div>
                        )}
                      </td>

                      <td className="px-4 py-3.5 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            icon={<Eye size={14} />}
                            onClick={() => navigate(`/devices/${device.id}`)}
                          >
                            Details
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <AddDeviceDialog
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        onCreated={loadData}
      />
    </div>
  )
}
