import { useCallback, useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import {
  ArrowLeft,
  CheckCircle2,
  History,
  Info,
  Laptop,
  RefreshCw,
  Shield,
  ShieldCheck,
  Slash,
  Trash2,
} from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import Dialog from "../../../components/ui/Dialog"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  apiGetConsentCategories,
  apiGetDeviceDetail,
  apiRevokeDevice,
  apiUpdateDeviceConsent,
  ApiError,
  type ConsentCategory,
  type DeviceDetail,
  type DeviceStatus,
} from "../../../lib/devicesApi"
import { useMe } from "../../../lib/me"

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

export default function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const { me } = useMe()

  const canWrite =
    me?.role === "organization_admin" ||
    me?.effective_modules?.device_agents === "write" ||
    me?.effective_modules?.assets === "write"

  const [device, setDevice] = useState<DeviceDetail | null>(null)
  const [categoriesDef, setCategoriesDef] = useState<ConsentCategory[]>([])
  const [loading, setLoading] = useState(true)
  const [revokeOpen, setRevokeOpen] = useState(false)

  // Update consent modal state
  const [editConsentOpen, setEditConsentOpen] = useState(false)
  const [selectedCats, setSelectedCats] = useState<string[]>([])
  const [updatingConsent, setUpdatingConsent] = useState(false)

  const loadData = useCallback(() => {
    if (!id) return
    setLoading(true)
    Promise.all([apiGetDeviceDetail(id), apiGetConsentCategories()])
      .then(([dev, catRes]) => {
        setDevice(dev)
        setCategoriesDef(catRes.categories)
        if (dev.active_consent) {
          setSelectedCats(dev.active_consent.categories)
        }
      })
      .catch((err) => {
        toast.show(err instanceof ApiError ? err.message : "Failed to load device details.", { tone: "danger" })
      })
      .finally(() => setLoading(false))
  }, [id, toast])

  useEffect(() => {
    loadData()
  }, [loadData])

  async function handleRevoke(reason?: string) {
    if (!id || !reason?.trim()) {
      toast.show("A revocation reason is required for audit verification.", { tone: "danger" })
      return
    }
    try {
      await apiRevokeDevice(id, reason.trim())
      toast.show("Device agent revoked. Ingestion stopped immediately.", { tone: "success" })
      setRevokeOpen(false)
      loadData()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to revoke device.", { tone: "danger" })
    }
  }

  async function handleUpdateConsent() {
    if (!id) return
    if (selectedCats.length === 0) {
      toast.show("At least one monitoring category must be selected.", { tone: "danger" })
      return
    }
    setUpdatingConsent(true)
    try {
      await apiUpdateDeviceConsent(id, selectedCats)
      toast.show("Consent record updated. New immutable ledger entry created.", { tone: "success" })
      setEditConsentOpen(false)
      loadData()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to update consent.", { tone: "danger" })
    } finally {
      setUpdatingConsent(false)
    }
  }

  function toggleCat(key: string) {
    setSelectedCats((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }

  if (loading && !device) {
    return (
      <div className="space-y-6 p-6 lg:p-8">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!device) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-fg-muted">Device not found or access denied.</p>
        <Button variant="ghost" className="mt-4" onClick={() => navigate("/devices")}>
          Back to Devices
        </Button>
      </div>
    )
  }

  const isRevoked = device.status === "revoked"
  const isPending = device.status === "pending_consent"
  const activeCategories = device.active_consent?.categories ?? []

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Back button & Title bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            icon={<ArrowLeft size={16} />}
            onClick={() => navigate("/devices")}
          >
            All Devices
          </Button>
          <div className="h-4 w-px bg-line" />
          <div>
            <h1 className="text-xl font-semibold text-fg-primary flex items-center gap-2">
              <Laptop className="text-brand-400" size={22} />
              {device.device_name || device.asset.name}
            </h1>
            <p className="text-xs text-fg-muted">
              Endpoint Device ID: <code className="font-mono text-fg-secondary">{device.id}</code>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <IconButton icon={RefreshCw} label="Refresh" onClick={loadData} />
          {canWrite && !isRevoked && (
            <Button
              variant="danger"
              icon={<Trash2 size={14} />}
              onClick={() => setRevokeOpen(true)}
            >
              Revoke Device
            </Button>
          )}
        </div>
      </div>

      {/* Main Status & Asset Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Device Status Card */}
        <div className="rounded-card border border-line bg-surface p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-fg-muted">
              Agent Liveness
            </span>
            <Badge tone={statusTone(device.status)}>{statusLabel(device.status)}</Badge>
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between py-1 border-b border-line/40">
              <span className="text-fg-muted">Operating System</span>
              <span className="text-fg-primary font-medium">{device.operating_system || "Unknown"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-line/40">
              <span className="text-fg-muted">Agent Version</span>
              <span className="font-mono text-fg-primary">v{device.agent_version || "1.0.0"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-line/40">
              <span className="text-fg-muted">Last Heartbeat</span>
              <span className="text-fg-primary">
                {device.last_heartbeat_at
                  ? new Date(device.last_heartbeat_at).toLocaleString()
                  : "Never received"}
              </span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-fg-muted">Enrolled At</span>
              <span className="text-fg-primary">
                {device.enrolled_at ? new Date(device.enrolled_at).toLocaleString() : "Pending"}
              </span>
            </div>
          </div>
        </div>

        {/* Bound Asset Card */}
        <div className="rounded-card border border-line bg-surface p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-fg-muted">
              Target Asset
            </span>
            <Badge tone="neutral">{device.asset.asset_type}</Badge>
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between py-1 border-b border-line/40">
              <span className="text-fg-muted">Asset Name</span>
              <span className="text-fg-primary font-medium">{device.asset.name}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-line/40">
              <span className="text-fg-muted">Hostname</span>
              <span className="font-mono text-fg-primary">{device.asset.hostname || "None"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-line/40">
              <span className="text-fg-muted">IP Address</span>
              <span className="font-mono text-fg-primary">{device.asset.ip_address || "None"}</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-fg-muted">Criticality</span>
              <span className="capitalize text-fg-primary">{device.asset.criticality}</span>
            </div>
          </div>
        </div>

        {/* Consent Protection Status */}
        <div className="rounded-card border border-line bg-surface p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-fg-muted">
              Consent Enforcement
            </span>
            {isRevoked ? (
              <Badge tone="danger">Revoked</Badge>
            ) : isPending ? (
              <Badge tone="brand">Awaiting Consent</Badge>
            ) : (
              <Badge tone="success">Active v{device.active_consent?.version}</Badge>
            )}
          </div>
          <div className="text-xs text-fg-muted space-y-2">
            {isRevoked ? (
              <p className="text-danger">
                Ingestion is halted. Any events sent from this device token are rejected with{" "}
                <code className="font-mono">device_revoked</code>.
              </p>
            ) : isPending ? (
              <p>
                Consent has not been granted yet. Events from this device cannot be ingested until
                the user completes the consent flow.
              </p>
            ) : (
              <>
                <p>
                  Server-side filter strictly verifies incoming telemetry. Non-consented categories
                  are rejected and discarded without being stored.
                </p>
                <div className="text-[11px] text-emerald-400 flex items-center gap-1 font-medium">
                  <ShieldCheck size={14} />
                  {activeCategories.length} / {categoriesDef.length || 6} categories authorized
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Active Consent Categories Panel */}
      <div className="rounded-card border border-line bg-surface p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/60 pb-4">
          <div>
            <h2 className="text-sm font-semibold text-fg-primary flex items-center gap-2">
              <Shield className="text-brand-400" size={18} />
              Active Monitoring Policy &amp; Category Disclosures
            </h2>
            <p className="text-xs text-fg-muted mt-0.5">
              Only explicitly consented telemetry is ingested. Prohibited data categories are never monitored.
            </p>
          </div>
          {canWrite && !isRevoked && (
            <Button
              variant="secondary"
              onClick={() => {
                setSelectedCats(device.active_consent?.categories ?? [])
                setEditConsentOpen(true)
              }}
            >
              Update Consent Policy
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {categoriesDef.map((cat) => {
            const isGranted = activeCategories.includes(cat.key)

            return (
              <div
                key={cat.key}
                className={`rounded-control border p-3.5 space-y-2 transition ${
                  isGranted
                    ? "border-emerald-500/30 bg-emerald-500/5"
                    : "border-line bg-surface-sunken opacity-70"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-xs text-fg-primary">{cat.label}</span>
                  {isGranted ? (
                    <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-400">
                      <CheckCircle2 size={13} /> Consented
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[11px] font-medium text-fg-muted">
                      <Slash size={13} /> Prohibited
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-fg-muted leading-relaxed">{cat.description}</p>
                <div className="rounded bg-black/20 p-2 text-[10px] text-fg-faint space-y-0.5">
                  <div className="font-semibold text-fg-muted">Prohibited:</div>
                  <div>{cat.prohibited}</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Consent History Ledger (Immutable Audit Trail) */}
      <div className="rounded-card border border-line bg-surface p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-line/60 pb-3">
          <div>
            <h2 className="text-sm font-semibold text-fg-primary flex items-center gap-2">
              <History className="text-brand-400" size={18} />
              Consent Audit Ledger
            </h2>
            <p className="text-xs text-fg-muted mt-0.5">
              Append-only consent log. Updates create new version records; past entries are never mutated.
            </p>
          </div>
          <Badge tone="neutral">{device.consent_history.length} records</Badge>
        </div>

        {device.consent_history.length === 0 ? (
          <div className="py-6 text-center text-xs text-fg-muted">
            No consent records logged for this device yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-line bg-surface-sunken text-fg-muted font-medium">
                <tr>
                  <th className="px-3 py-2.5">Version &amp; Status</th>
                  <th className="px-3 py-2.5">Consented At</th>
                  <th className="px-3 py-2.5">Signatory Account</th>
                  <th className="px-3 py-2.5">Authorized Categories</th>
                  <th className="px-3 py-2.5">Revocation</th>
                  <th className="px-3 py-2.5">Client IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {device.consent_history.map((record) => {
                  const recordRevoked = !!record.revoked_at
                  const isActive = !recordRevoked && device.active_consent?.id === record.id

                  return (
                    <tr key={record.id} className="hover:bg-surface-muted/40">
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-medium text-fg-primary">
                            {record.version}
                          </span>
                          {isActive ? (
                            <Badge tone="success">Active</Badge>
                          ) : recordRevoked ? (
                            <Badge tone="danger">Revoked</Badge>
                          ) : (
                            <Badge tone="neutral">Superseded</Badge>
                          )}
                        </div>
                      </td>

                      <td className="px-3 py-2.5 text-fg-muted">
                        {new Date(record.consented_at).toLocaleString()}
                      </td>

                      <td className="px-3 py-2.5">
                        <span className="font-mono text-fg-secondary text-[11px]">
                          {record.account_type}: {record.account_id.slice(0, 8)}...
                        </span>
                      </td>

                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {record.categories.map((c) => (
                            <span
                              key={c}
                              className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-fg-muted border border-line"
                            >
                              {c}
                            </span>
                          ))}
                        </div>
                      </td>

                      <td className="px-3 py-2.5">
                        {recordRevoked ? (
                          <div className="text-danger text-[11px]">
                            <div>{new Date(record.revoked_at!).toLocaleDateString()}</div>
                            <div className="text-fg-muted italic">"{record.revocation_reason}"</div>
                          </div>
                        ) : (
                          <span className="text-fg-faint">--</span>
                        )}
                      </td>

                      <td className="px-3 py-2.5 font-mono text-fg-muted text-[11px]">
                        {record.ip || "127.0.0.1"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Revoke Confirmation Dialog */}
      <ConfirmDialog
        open={revokeOpen}
        onClose={() => setRevokeOpen(false)}
        onConfirm={(reason) => void handleRevoke(reason)}
        title="Revoke Device &amp; Monitoring Consent"
        impact="This will immediately revoke device authorization, delete active consent, and reject all subsequent event ingestion."
        requireReason
        confirmLabel="Revoke Device"
        danger
      />

      {/* Update Consent Dialog */}
      <Dialog
        open={editConsentOpen}
        onClose={() => setEditConsentOpen(false)}
        title="Update Device Consent Policy"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => setEditConsentOpen(false)} disabled={updatingConsent}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => void handleUpdateConsent()}
              loading={updatingConsent}
              disabled={selectedCats.length === 0}
            >
              Sign &amp; Save Policy
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="rounded-control bg-brand/5 border border-brand/20 p-3 text-xs text-fg-primary space-y-1">
            <div className="font-semibold text-brand flex items-center gap-1.5">
              <Info size={14} /> Immutable History Policy
            </div>
            <p className="text-fg-muted">
              Saving updates creates a new consent version (v1.0). Previous records remain unaltered in the audit ledger.
            </p>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-medium text-fg-secondary">Select Authorized Categories:</div>
            {categoriesDef.map((cat) => {
              const isChecked = selectedCats.includes(cat.key)
              return (
                <label
                  key={cat.key}
                  className={`flex items-start gap-3 p-2.5 rounded-control border cursor-pointer transition ${
                    isChecked
                      ? "border-brand/40 bg-brand/5"
                      : "border-line bg-surface hover:bg-surface-sunken"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleCat(cat.key)}
                    className="mt-0.5 accent-brand"
                  />
                  <div className="space-y-0.5 text-xs">
                    <div className="font-medium text-fg-primary">{cat.label}</div>
                    <div className="text-fg-muted text-[11px]">{cat.description}</div>
                  </div>
                </label>
              )
            })}
          </div>
        </div>
      </Dialog>
    </div>
  )
}
