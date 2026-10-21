import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Copy,
  Info,
  Laptop,
  Lock,
  ShieldCheck,
  Slash,
  Terminal,
} from "lucide-react"

import Button from "../components/ui/Button"
import Skeleton from "../components/ui/Skeleton"
import { useToast } from "../components/ui/Toast"
import {
  apiPreviewEnrollmentToken,
  apiSubmitTokenConsent,
  ApiError,
  type TokenPreview,
} from "../lib/devicesApi"

export default function DeviceConsentPage() {
  const [searchParams] = useSearchParams()
  const toast = useToast()

  const [tokenInput, setTokenInput] = useState(searchParams.get("token") || "")
  const [token, setToken] = useState(searchParams.get("token") || "")
  const [preview, setPreview] = useState<TokenPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  // Selected categories (defaults to all categories from preview)
  const [selectedCats, setSelectedCats] = useState<string[]>([])
  const [acknowledged, setAcknowledged] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Success state
  const [success, setSuccess] = useState<{
    consent_id: string
    categories: string[]
    message: string
  } | null>(null)
  const [copiedCmd, setCopiedCmd] = useState(false)

  useEffect(() => {
    if (!token) return
    setLoading(true)
    setError("")
    apiPreviewEnrollmentToken(token)
      .then((res) => {
        setPreview(res)
        setSelectedCats(res.categories.map((c) => c.key))
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Invalid or expired enrollment token.")
      })
      .finally(() => setLoading(false))
  }, [token])

  function handleTokenSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!tokenInput.trim()) return
    setToken(tokenInput.trim())
  }

  function toggleCat(key: string) {
    setSelectedCats((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }

  async function handleGrantConsent() {
    if (!token) return
    if (selectedCats.length === 0) {
      toast.show("Please select at least one monitoring category.", { tone: "danger" })
      return
    }
    if (!acknowledged) {
      toast.show("Please check the confirmation box to proceed.", { tone: "danger" })
      return
    }

    setSubmitting(true)
    try {
      const res = await apiSubmitTokenConsent(token, selectedCats, preview?.consent_version || "v1.0")
      setSuccess({
        consent_id: res.consent_id,
        categories: res.categories_granted,
        message: res.message,
      })
      toast.show("Consent recorded successfully.", { tone: "success" })
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Failed to authorize consent.", { tone: "danger" })
    } finally {
      setSubmitting(false)
    }
  }

  function copyCommand(cmd: string) {
    navigator.clipboard.writeText(cmd)
    setCopiedCmd(true)
    setTimeout(() => setCopiedCmd(false), 2000)
    toast.show("Command copied to clipboard.", { tone: "success" })
  }

  return (
    <div className="min-h-screen bg-canvas text-fg-primary flex flex-col justify-between">
      {/* Top Header */}
      <header className="border-b border-line bg-surface/80 backdrop-blur px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="rounded-lg bg-brand-500/10 p-2">
              <ShieldCheck size={22} className="text-brand-400" />
            </div>
            <div>
              <span className="font-bold text-base text-white tracking-tight">
                Sentinel<span className="text-brand-400">X</span>
              </span>
              <span className="ml-2 text-xs text-fg-muted font-normal">
                Consent-Based Telemetry Portal
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            <Lock size={13} className="text-emerald-400" />
            End-to-End Consent Protected
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-3xl mx-auto w-full p-6 my-auto space-y-6">
        {/* Token Input Screen if no token given */}
        {!token && (
          <div className="rounded-card border border-line bg-surface p-8 max-w-lg mx-auto space-y-5 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-brand/10 text-brand">
              <Laptop size={24} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-fg-primary">Endpoint Device Enrollment</h2>
              <p className="mt-1 text-xs text-fg-muted">
                Enter your 30-minute enrollment token to review monitoring policies and authorize endpoint telemetry.
              </p>
            </div>
            <form onSubmit={handleTokenSubmit} className="space-y-4">
              <input
                type="text"
                placeholder="sxe_..."
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                className="w-full text-center font-mono text-sm rounded-control border border-line bg-surface-sunken px-3 py-2.5 text-fg-primary placeholder-fg-faint outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
              />
              <Button variant="primary" type="submit" className="w-full" disabled={!tokenInput.trim()}>
                Review Consent Policies
              </Button>
            </form>
          </div>
        )}

        {/* Loading State */}
        {token && loading && (
          <div className="rounded-card border border-line bg-surface p-8 space-y-4">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}

        {/* Error State */}
        {token && error && (
          <div className="rounded-card border border-danger/30 bg-danger/5 p-6 text-center space-y-4">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-danger/10 text-danger">
              <AlertTriangle size={24} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-danger">Enrollment Token Unavailable</h3>
              <p className="mt-1 text-xs text-fg-muted">{error}</p>
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                setToken("")
                setTokenInput("")
                setError("")
              }}
            >
              Try Another Token
            </Button>
          </div>
        )}

        {/* Success Screen */}
        {success && (
          <div className="rounded-card border border-emerald-500/30 bg-emerald-500/5 p-8 space-y-6 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-400">
              <CheckCircle2 size={32} />
            </div>
            <div>
              <h2 className="text-xl font-bold text-fg-primary">Monitoring Consent Authorized</h2>
              <p className="mt-1 text-xs text-fg-muted">
                Consent record ID <code className="font-mono text-fg-secondary">{success.consent_id}</code> is
                permanently recorded and stamped with version {preview?.consent_version || "v1.0"}.
              </p>
            </div>

            <div className="rounded-control bg-surface border border-line p-4 text-left space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-fg-primary">
                <Terminal size={15} className="text-brand-400" />
                Next Step: Connect Your Endpoint Agent
              </div>
              <p className="text-xs text-fg-muted">
                Execute the following setup command on <strong>{preview?.asset.name}</strong> to exchange this
                token for an encrypted device API key:
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 font-mono text-xs bg-black/40 p-2.5 rounded border border-line text-emerald-400 select-all overflow-x-auto">
                  python -m agent.main enroll --token {token}
                </code>
                <Button
                  variant="secondary"
                  icon={copiedCmd ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                  onClick={() => copyCommand(`python -m agent.main enroll --token ${token}`)}
                >
                  {copiedCmd ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>

            <div className="rounded-control bg-surface-sunken p-3 text-xs text-fg-muted text-left flex items-start gap-2.5">
              <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <strong>Strict Privacy Guarantee:</strong> The SentinelX server will only accept telemetry from
                the {success.categories.length} categories you authorized. You or your security manager may revoke
                this authorization at any time.
              </div>
            </div>
          </div>
        )}

        {/* Consent Form Preview */}
        {preview && !success && (
          <div className="space-y-6">
            {/* Header info */}
            <div className="rounded-card border border-line bg-surface p-6 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/60 pb-3">
                <div>
                  <h2 className="text-lg font-bold text-fg-primary">
                    Endpoint Telemetry Authorization
                  </h2>
                  <p className="text-xs text-fg-muted">
                    Organization: <strong className="text-fg-secondary">{preview.organization_name}</strong>
                  </p>
                </div>
                <div className="rounded bg-brand/10 text-brand px-2.5 py-1 text-xs font-mono">
                  Agreement {preview.consent_version}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs">
                <div className="rounded-control bg-surface-sunken p-3 border border-line">
                  <div className="text-fg-muted">Target Device / Asset:</div>
                  <div className="font-semibold text-fg-primary mt-0.5">{preview.asset.name}</div>
                  <div className="text-fg-muted text-[11px] capitalize">{preview.asset.asset_type}</div>
                </div>
                <div className="rounded-control bg-surface-sunken p-3 border border-line">
                  <div className="text-fg-muted">Operating Platform:</div>
                  <div className="font-semibold text-fg-primary mt-0.5">
                    {preview.asset.operating_system || "Endpoint OS"}
                  </div>
                  <div className="text-fg-muted text-[11px]">Valid until {new Date(preview.expires_at).toLocaleTimeString()}</div>
                </div>
              </div>

              <div className="rounded-control bg-brand/5 border border-brand/20 p-3 text-xs text-fg-muted space-y-1">
                <div className="font-semibold text-brand flex items-center gap-1.5">
                  <Info size={14} /> Explicit Consent Protection
                </div>
                <p>
                  SentinelX enforces strict consent-gated telemetry. Select the monitoring categories you agree to
                  stream to the security team. Categories you leave unchecked are strictly prohibited and discarded
                  by the ingestion pipeline.
                </p>
              </div>
            </div>

            {/* Category selection list */}
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-semibold uppercase tracking-wider text-fg-muted">
                  Monitoring Categories ({selectedCats.length} of {preview.categories.length} selected)
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setSelectedCats(
                      selectedCats.length === preview.categories.length
                        ? []
                        : preview.categories.map((c) => c.key),
                    )
                  }
                  className="text-xs text-brand hover:underline"
                >
                  {selectedCats.length === preview.categories.length ? "Deselect All" : "Select All"}
                </button>
              </div>

              <div className="space-y-3">
                {preview.categories.map((cat) => {
                  const isChecked = selectedCats.includes(cat.key)

                  return (
                    <div
                      key={cat.key}
                      onClick={() => toggleCat(cat.key)}
                      className={`rounded-card border p-4 cursor-pointer transition select-none ${
                        isChecked
                          ? "border-brand/40 bg-brand/5 shadow-sm"
                          : "border-line bg-surface hover:bg-surface-sunken opacity-75"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {}} // handled by div click
                          className="mt-1 h-4 w-4 accent-brand cursor-pointer"
                        />
                        <div className="flex-1 space-y-1.5 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-fg-primary text-sm">{cat.label}</span>
                            {isChecked ? (
                              <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                                <CheckCircle2 size={13} /> Included
                              </span>
                            ) : (
                              <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                                <Slash size={13} /> Excluded
                              </span>
                            )}
                          </div>
                          <p className="text-fg-muted leading-relaxed">{cat.description}</p>
                          <div className="rounded bg-black/25 p-2 text-[11px] space-y-0.5">
                            <div className="text-fg-secondary font-medium">Prohibited Boundary:</div>
                            <div className="text-fg-faint">{cat.prohibited}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Acknowledgment & Submit */}
            <div className="rounded-card border border-line bg-surface p-6 space-y-4">
              <label className="flex items-start gap-3 cursor-pointer text-xs">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-brand cursor-pointer"
                />
                <span className="text-fg-secondary leading-relaxed">
                  I understand and authorize the collection of endpoint security telemetry for the selected categories
                  under SentinelX terms (version {preview.consent_version}). I acknowledge that telemetry will be retained
                  for security monitoring and that consent can be revoked at any time.
                </span>
              </label>

              <Button
                variant="primary"
                className="w-full"
                onClick={() => void handleGrantConsent()}
                loading={submitting}
                disabled={!acknowledged || selectedCats.length === 0}
                icon={<ArrowRight size={16} />}
              >
                Authorize &amp; Register Endpoint
              </Button>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-line bg-surface/40 px-6 py-4 text-center text-xs text-fg-muted">
        SentinelX Security Platform &bull; Privacy-First Endpoint Monitoring
      </footer>
    </div>
  )
}
