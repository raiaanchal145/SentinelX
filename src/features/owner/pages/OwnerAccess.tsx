import { useCallback, useEffect, useMemo, useState } from "react"
import { Check, Lock, X } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import EmptyState from "../../../components/EmptyState"
import Skeleton from "../../../components/ui/Skeleton"
import Tooltip from "../../../components/ui/Tooltip"
import { useToast } from "../../../components/ui/Toast"
import { roleLabel } from "../../../lib/auth"
import { MODULE_INFO, MODULE_KEYS } from "../../../lib/modules"
import MemberAccessDrawer from "../components/MemberAccessDrawer"

import {
  apiGetAccessMatrix,
  apiGetOwnerMembers,
  apiUpdateAccessMatrix,
  ApiError,
  type AccessMatrixResponse,
  type OwnerMember,
} from "../../../lib/api"

const ROLES = ["soc_analyst", "security_manager", "it_developer", "auditor"] as const

/** Organization owner: role x module access matrix + per-member drawer
 * (Prompt B section B4). */
function OwnerAccess() {
  const toast = useToast()
  const [data, setData] = useState<AccessMatrixResponse | null>(null)
  const [members, setMembers] = useState<OwnerMember[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [pending, setPending] = useState<Record<string, Record<string, boolean>>>({})
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [memberDrawerTarget, setMemberDrawerTarget] = useState<OwnerMember | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError("")
    Promise.all([apiGetAccessMatrix(), apiGetOwnerMembers()])
      .then(([matrixRes, membersRes]) => {
        setData(matrixRes)
        setMembers(membersRes.members)
        const initialPending: Record<string, Record<string, boolean>> = {}
        for (const role of ROLES) {
          initialPending[role] = {}
          for (const key of MODULE_KEYS) {
            initialPending[role][key] = matrixRes.matrix[role]?.[key]?.owner_enabled ?? true
          }
        }
        setPending(initialPending)
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load the access matrix."))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const changes = useMemo(() => {
    if (!data) return []
    const result: { role: string; module_key: string; enabled: boolean }[] = []
    for (const role of ROLES) {
      for (const key of MODULE_KEYS) {
        const cell = data.matrix[role]?.[key]
        if (!cell || !cell.role_has_default) continue
        const current = pending[role]?.[key]
        if (current !== undefined && current !== cell.owner_enabled) {
          result.push({ role, module_key: key, enabled: current })
        }
      }
    }
    return result
  }, [data, pending])

  function toggle(role: string, key: string) {
    setPending((prev) => ({
      ...prev,
      [role]: { ...prev[role], [key]: !prev[role]?.[key] },
    }))
  }

  async function handleSave() {
    setSaving(true)
    try {
      await apiUpdateAccessMatrix(changes)
      toast.show("Access updated.", { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update access.", { tone: "danger" })
    } finally {
      setSaving(false)
      setConfirmOpen(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div>
            <h1 className="text-2xl font-semibold text-fg-primary">Access</h1>
            <p className="mt-1 text-xs text-fg-muted">
              Control which modules each role can use. A module the platform has disabled, or that requires
              in-house SOC, appears locked and can't be turned on here.
            </p>
          </div>

          {loading ? (
            <Skeleton count={6} className="h-10 w-full" />
          ) : loadError ? (
            <EmptyState title="Couldn't load access" description={loadError} action={{ label: "Retry", onClick: load }} />
          ) : (
            data && (
              <>
                <div className="overflow-auto rounded-card border border-line">
                  <table className="w-full min-w-[720px] border-collapse text-sm">
                    <thead className="bg-surface-sunken">
                      <tr>
                        <th className="border-b border-line px-3 py-2.5 text-left text-xs font-semibold text-fg-muted">
                          Module
                        </th>
                        {ROLES.map((role) => (
                          <th key={role} className="border-b border-line px-3 py-2.5 text-left text-xs font-semibold text-fg-muted">
                            {roleLabel(role)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {MODULE_KEYS.map((key, index) => (
                        <tr key={key} className={index > 0 ? "border-t border-line/60" : ""}>
                          <td className="px-3 py-2.5 align-top">
                            <p className="font-medium text-fg-primary">{MODULE_INFO[key].label}</p>
                            <p className="text-xs text-fg-muted">{MODULE_INFO[key].description}</p>
                          </td>
                          {ROLES.map((role) => {
                            const cell = data.matrix[role]?.[key]
                            if (!cell || !cell.role_has_default) {
                              return (
                                <td key={role} className="px-3 py-2.5 text-fg-faint">
                                  --
                                </td>
                              )
                            }
                            if (!cell.platform_enabled || cell.soc_gated) {
                              return (
                                <td key={role} className="px-3 py-2.5">
                                  <Tooltip label={!cell.platform_enabled ? "Disabled by platform" : "Requires in-house SOC"}>
                                    <Lock size={14} className="text-fg-faint" aria-hidden="true" />
                                  </Tooltip>
                                </td>
                              )
                            }
                            const value = pending[role]?.[key] ?? cell.owner_enabled
                            return (
                              <td key={role} className="px-3 py-2.5">
                                <button
                                  type="button"
                                  onClick={() => toggle(role, key)}
                                  aria-pressed={value}
                                  aria-label={`${MODULE_INFO[key].label} for ${roleLabel(role)}`}
                                  className={`inline-flex h-7 w-7 items-center justify-center rounded-control border ${
                                    value
                                      ? "border-success/30 bg-success/10 text-success-fg"
                                      : "border-danger/30 bg-danger/10 text-danger-fg"
                                  }`}
                                >
                                  {value ? <Check size={14} /> : <X size={14} />}
                                </button>
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="flex items-center justify-end gap-3">
                  {changes.length > 0 && (
                    <p className="text-xs text-fg-muted">
                      {changes.length} change{changes.length === 1 ? "" : "s"} pending
                    </p>
                  )}
                  <Button variant="primary" disabled={changes.length === 0} onClick={() => setConfirmOpen(true)}>
                    Save changes
                  </Button>
                </div>

                <section aria-label="Per-member overrides" className="rounded-card border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold text-fg-primary">Per-member overrides</h2>
                  <p className="mt-1 text-xs text-fg-muted">
                    Turn off individual modules for one person, on top of what their role allows.
                  </p>
                  {members.length === 0 ? (
                    <p className="mt-3 text-xs text-fg-muted">Invite members to your organization first.</p>
                  ) : (
                    <ul className="mt-3 space-y-1.5">
                      {members.map((member) => (
                        <li key={member.id} className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-sm">
                          <span>
                            <span className="font-medium text-fg-primary">{member.name}</span>{" "}
                            <span className="text-xs text-fg-muted">{roleLabel(member.role)}</span>
                          </span>
                          <Button variant="ghost" onClick={() => setMemberDrawerTarget(member)}>
                            Edit access
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </>
            )
          )}
        </div>
      </main>

      <MemberAccessDrawer member={memberDrawerTarget} onClose={() => setMemberDrawerTarget(null)} onSaved={load} />

      <ConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void handleSave()}
        title="Save access changes?"
        impact={
          changes.length === 0
            ? "No changes to save."
            : `This will change: ${changes
                .map((c) => `${roleLabel(c.role)} / ${MODULE_INFO[c.module_key as keyof typeof MODULE_INFO]?.label ?? c.module_key} -> ${c.enabled ? "Enabled" : "Disabled"}`)
                .join(", ")}.`
        }
        confirmLabel={saving ? "Saving..." : "Save changes"}
        danger={changes.some((c) => !c.enabled)}
      />
    </div>
  )
}

export default OwnerAccess
