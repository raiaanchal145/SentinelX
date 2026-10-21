import { useEffect, useState } from "react"
import { Check, Copy, ExternalLink, KeyRound, ShieldCheck } from "lucide-react"

import Button from "../../../components/ui/Button"
import Dialog from "../../../components/ui/Dialog"
import { useToast } from "../../../components/ui/Toast"
import { apiListAssets, type AssetRow } from "../../../lib/api"
import { apiCreateEnrollmentToken, ApiError } from "../../../lib/devicesApi"

interface AddDeviceDialogProps {
  open: boolean
  onClose: () => void
  onCreated?: () => void
}

export default function AddDeviceDialog({ open, onClose, onCreated }: AddDeviceDialogProps) {
  const toast = useToast()
  const [assets, setAssets] = useState<AssetRow[]>([])
  const [loadingAssets, setLoadingAssets] = useState(false)
  const [selectedAssetId, setSelectedAssetId] = useState("")
  const [deviceName, setDeviceName] = useState("")
  const [operatingSystem, setOperatingSystem] = useState("Windows 11 Pro")
  const [submitting, setSubmitting] = useState(false)

  // Success state with generated token
  const [tokenResult, setTokenResult] = useState<{
    token: string
    token_prefix: string
    expires_at: string
    enrollment_url: string
    asset_name: string
  } | null>(null)
  const [copiedToken, setCopiedToken] = useState(false)
  const [copiedUrl, setCopiedUrl] = useState(false)

  useEffect(() => {
    if (open) {
      setLoadingAssets(true)
      apiListAssets({ page_size: 100 })
        .then((res) => {
          setAssets(res.assets.filter((a) => a.status === "active"))
          if (res.assets.length > 0) {
            setSelectedAssetId(res.assets[0].id)
            setDeviceName(res.assets[0].name)
            if (res.assets[0].operating_system) {
              setOperatingSystem(res.assets[0].operating_system)
            }
          }
        })
        .catch(() => {
          // ignore error
        })
        .finally(() => setLoadingAssets(false))
      setTokenResult(null)
      setCopiedToken(false)
      setCopiedUrl(false)
    }
  }, [open])

  async function handleCreateToken() {
    if (!selectedAssetId) {
      toast.show("Please select an asset.", { tone: "danger" })
      return
    }
    setSubmitting(true)
    try {
      const res = await apiCreateEnrollmentToken({
        asset_id: selectedAssetId,
        device_name: deviceName || undefined,
        operating_system: operatingSystem || undefined,
      })
      setTokenResult({
        token: res.token,
        token_prefix: res.token_prefix,
        expires_at: res.expires_at,
        enrollment_url: `${window.location.origin}${res.enrollment_url}`,
        asset_name: res.asset_name,
      })
      toast.show("Enrollment token generated.", { tone: "success" })
      onCreated?.()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to generate token.", { tone: "danger" })
    } finally {
      setSubmitting(false)
    }
  }

  function copyToClipboard(text: string, isToken: boolean) {
    navigator.clipboard.writeText(text)
    if (isToken) {
      setCopiedToken(true)
      setTimeout(() => setCopiedToken(false), 2000)
    } else {
      setCopiedUrl(true)
      setTimeout(() => setCopiedUrl(false), 2000)
    }
    toast.show("Copied to clipboard.", { tone: "success" })
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={tokenResult ? "Device Enrollment Token Ready" : "Enroll New Endpoint Device"}
      footer={
        tokenResult ? (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        ) : (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => void handleCreateToken()}
              loading={submitting}
              disabled={!selectedAssetId || loadingAssets}
            >
              Generate Enrollment Token
            </Button>
          </div>
        )
      }
    >
      {tokenResult ? (
        <div className="space-y-4">
          <div className="rounded-control border border-brand/30 bg-brand/5 p-4 text-xs text-fg-primary space-y-2">
            <div className="flex items-center gap-2 font-semibold text-brand">
              <ShieldCheck size={16} />
              Consent-Gated Enrollment
            </div>
            <p className="text-fg-muted">
              Before the endpoint agent can send events, the user of <strong>{tokenResult.asset_name}</strong> must open
              the Consent Screen to review and authorize the monitoring categories.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-fg-muted mb-1">One-Time Token (Valid 30 minutes)</label>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={tokenResult.token}
                className="w-full font-mono text-xs rounded-control border border-line bg-surface-sunken px-3 py-2 text-fg-primary select-all outline-none"
              />
              <Button
                variant="secondary"
                icon={copiedToken ? <Check size={14} className="text-success" /> : <Copy size={14} />}
                onClick={() => copyToClipboard(tokenResult.token, true)}
              >
                {copiedToken ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-fg-muted mb-1">User Consent Link</label>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={tokenResult.enrollment_url}
                className="w-full text-xs rounded-control border border-line bg-surface-sunken px-3 py-2 text-fg-primary select-all outline-none"
              />
              <Button
                variant="secondary"
                icon={copiedUrl ? <Check size={14} className="text-success" /> : <Copy size={14} />}
                onClick={() => copyToClipboard(tokenResult.enrollment_url, false)}
              >
                {copiedUrl ? "Copied" : "Copy"}
              </Button>
              <a
                href={tokenResult.enrollment_url}
                target="_blank"
                rel="noreferrer"
                className="p-2 rounded-control border border-line hover:bg-surface-muted text-fg-muted"
                title="Open consent screen"
              >
                <ExternalLink size={14} />
              </a>
            </div>
          </div>

          <div className="rounded-control bg-surface-sunken p-3 text-xs text-fg-muted space-y-1">
            <div className="font-medium text-fg-secondary">Agent Setup Command:</div>
            <code className="block font-mono bg-black/30 p-2 rounded text-fg-primary select-all">
              sentinelx-agent --enroll-token {tokenResult.token}
            </code>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-fg-muted">
            Generate a single-use token to bind a workstation or server to an endpoint monitoring agent.
          </p>

          <label className="block">
            <span className="block text-xs font-medium text-fg-muted mb-1">Select Target Asset *</span>
            {loadingAssets ? (
              <div className="text-xs text-fg-faint py-2">Loading asset inventory...</div>
            ) : assets.length === 0 ? (
              <div className="text-xs text-danger py-2">No active assets found. Create an asset in the Assets module first.</div>
            ) : (
              <select
                value={selectedAssetId}
                onChange={(e) => {
                  setSelectedAssetId(e.target.value)
                  const found = assets.find((a) => a.id === e.target.value)
                  if (found) {
                    setDeviceName(found.name)
                    if (found.operating_system) setOperatingSystem(found.operating_system)
                  }
                }}
                className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              >
                {assets.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.asset_type}) {a.hostname ? `- ${a.hostname}` : ""}
                  </option>
                ))}
              </select>
            )}
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-medium text-fg-muted mb-1">Device / Host Name</span>
              <input
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                placeholder="e.g. Workstation-Alice"
                className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-fg-muted mb-1">Operating System</span>
              <input
                value={operatingSystem}
                onChange={(e) => setOperatingSystem(e.target.value)}
                placeholder="e.g. Windows 11, macOS, Ubuntu"
                className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              />
            </label>
          </div>

          <div className="rounded-control border border-dashed border-line bg-surface-sunken p-3 text-xs text-fg-muted space-y-1">
            <div className="flex items-center gap-1.5 font-medium text-fg-secondary">
              <KeyRound size={14} />
              Consent Protection
            </div>
            <p>
              Generating this token does not activate event collection. The device owner will choose granted categories
              on the consent screen before any data can be ingested.
            </p>
          </div>
        </div>
      )}
    </Dialog>
  )
}
