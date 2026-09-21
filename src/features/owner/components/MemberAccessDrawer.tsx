import { useEffect, useState } from "react"
import { Check, X } from "lucide-react"

import Button from "../../../components/ui/Button"
import Drawer from "../../../components/ui/Drawer"
import Skeleton from "../../../components/ui/Skeleton"
import Tooltip from "../../../components/ui/Tooltip"
import { useToast } from "../../../components/ui/Toast"
import { MODULE_INFO, MODULE_KEYS } from "../../../lib/modules"
import {
  apiGetMemberAccess,
  apiUpdateMemberAccess,
  ApiError,
  type MemberAccessResponse,
  type OwnerMember,
} from "../../../lib/api"

type MemberAccessDrawerProps = {
  member: OwnerMember | null
  onClose: () => void
  onSaved: () => void
}

/** Per-member access drawer (Prompt B section B4) -- lets the owner
 * turn individual modules off for one person, on top of their role's
 * access. Shows the live effective result (a module already locked by
 * the platform, the organization, or SOC-mode gating can't be turned
 * back on here -- only a module the role would otherwise have can be
 * denied). */
function MemberAccessDrawer({ member, onClose, onSaved }: MemberAccessDrawerProps) {
  const toast = useToast()
  const [access, setAccess] = useState<MemberAccessResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [denied, setDenied] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!member) return
    setLoading(true)
    apiGetMemberAccess(member.id)
      .then((res) => {
        setAccess(res)
        setDenied(new Set(Object.entries(res.modules).filter(([, cell]) => cell.denied).map(([key]) => key)))
      })
      .catch(() => setAccess(null))
      .finally(() => setLoading(false))
  }, [member])

  function toggleDenied(key: string) {
    setDenied((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function handleSave() {
    if (!member) return
    setSaving(true)
    try {
      await apiUpdateMemberAccess(member.id, Array.from(denied))
      toast.show(`Access updated for ${member.name}.`, { tone: "success" })
      onSaved()
      onClose()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update this member's access.", { tone: "danger" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={member !== null} onClose={onClose} side="right" title={member ? `${member.name}'s access` : "Member access"}>
      {loading || !access ? (
        <Skeleton count={6} className="h-10 w-full" />
      ) : (
        <div className="space-y-4">
          <ul className="space-y-1.5">
            {MODULE_KEYS.map((key) => {
              const cell = access.modules[key]
              const info = MODULE_INFO[key]

              if (!cell.role_has_default) {
                return (
                  <li key={key} className="flex items-center justify-between rounded-control p-2 text-sm text-fg-faint">
                    <span>{info.label}</span>
                    <span>N/A for this role</span>
                  </li>
                )
              }

              if (!cell.platform_enabled || cell.soc_gated) {
                return (
                  <li key={key} className="flex items-center justify-between rounded-control bg-surface-sunken p-2 text-sm">
                    <span className="text-fg-muted">{info.label}</span>
                    <Tooltip label={!cell.platform_enabled ? "Disabled by platform" : "Requires in-house SOC"}>
                      <span className="text-xs text-fg-faint">Locked</span>
                    </Tooltip>
                  </li>
                )
              }

              if (!cell.owner_enabled) {
                return (
                  <li key={key} className="flex items-center justify-between rounded-control bg-surface-sunken p-2 text-sm">
                    <span className="text-fg-muted">{info.label}</span>
                    <Tooltip label="Turned off for this role in your Access page">
                      <span className="text-xs text-fg-faint">Locked</span>
                    </Tooltip>
                  </li>
                )
              }

              const isDenied = denied.has(key)
              return (
                <li key={key} className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-sm">
                  <div>
                    <p className="font-medium text-fg-primary">{info.label}</p>
                    <p className="text-xs text-fg-muted">{info.description}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleDenied(key)}
                    aria-pressed={!isDenied}
                    className={`inline-flex h-7 w-7 items-center justify-center rounded-control border ${
                      isDenied ? "border-danger/30 bg-danger/10 text-danger-fg" : "border-success/30 bg-success/10 text-success-fg"
                    }`}
                    title={isDenied ? "Blocked -- click to allow" : "Allowed -- click to block"}
                  >
                    {isDenied ? <X size={14} /> : <Check size={14} />}
                  </button>
                </li>
              )
            })}
          </ul>

          <Button variant="primary" className="w-full" disabled={saving} onClick={() => void handleSave()}>
            {saving ? "Saving..." : "Save access"}
          </Button>
        </div>
      )}
    </Drawer>
  )
}

export default MemberAccessDrawer
