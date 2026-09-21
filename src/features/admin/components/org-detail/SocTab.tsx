import { useEffect, useMemo, useState } from "react"

import Badge from "../../../../components/ui/Badge"
import Button from "../../../../components/ui/Button"
import ConfirmDialog from "../../../../components/ui/ConfirmDialog"
import EmptyState from "../../../../components/EmptyState"
import SegmentedControl from "../../../../components/ui/SegmentedControl"
import Skeleton from "../../../../components/ui/Skeleton"
import { useToast } from "../../../../components/ui/Toast"
import {
  apiGetOrganizationMembers,
  apiListSocAnalysts,
  apiUpdateOrganizationSocMode,
  apiUpdateSocAnalystOrganizations,
  ApiError,
  type OrganizationDetail,
  type SocAnalyst,
} from "../../../../lib/api"

type SocTabProps = {
  detail: OrganizationDetail
  onSaved: () => void
}

/** SOC mode + (in managed mode) assigned platform SOC analysts for one
 * organization (Prompt B section A3, "SOC"). Assignment is edited from
 * the analyst side of the backend (PUT /admin/soc-analysts/{id}/
 * organizations replaces that analyst's FULL org list), so saving here
 * computes each changed analyst's new full list rather than posting a
 * per-organization assignment list directly. */
function SocTab({ detail, onSaved }: SocTabProps) {
  const toast = useToast()
  const [socAnalystCount, setSocAnalystCount] = useState<number | null>(null)
  const [analysts, setAnalysts] = useState<SocAnalyst[] | null>(null)
  const [loadingAnalysts, setLoadingAnalysts] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [pendingMode, setPendingMode] = useState<"managed" | "in_house" | null>(null)
  const [savingMode, setSavingMode] = useState(false)
  const [savingAssignments, setSavingAssignments] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiGetOrganizationMembers(detail.id)
      .then((res) => {
        if (cancelled) return
        setSocAnalystCount(res.members.filter((m) => m.role === "soc_analyst" && m.is_active).length)
      })
      .catch(() => {
        if (!cancelled) setSocAnalystCount(null)
      })
    return () => {
      cancelled = true
    }
  }, [detail.id])

  useEffect(() => {
    if (detail.soc_mode !== "managed") return
    let cancelled = false
    setLoadingAnalysts(true)
    apiListSocAnalysts()
      .then((res) => {
        if (cancelled) return
        setAnalysts(res.soc_analysts)
        setSelected(
          new Set(
            res.soc_analysts
              .filter((a) => a.assigned_organizations.some((o) => o.id === detail.id))
              .map((a) => a.id),
          ),
        )
      })
      .catch(() => {
        if (!cancelled) setAnalysts(null)
      })
      .finally(() => {
        if (!cancelled) setLoadingAnalysts(false)
      })
    return () => {
      cancelled = true
    }
  }, [detail.id, detail.soc_mode])

  const assignmentsDirty = useMemo(() => {
    if (!analysts) return false
    return analysts.some((a) => {
      const wasAssigned = a.assigned_organizations.some((o) => o.id === detail.id)
      return selected.has(a.id) !== wasAssigned
    })
  }, [analysts, selected, detail.id])

  async function handleModeConfirm() {
    if (!pendingMode) return
    setSavingMode(true)
    try {
      const res = await apiUpdateOrganizationSocMode(detail.id, pendingMode)
      toast.show(res.message ?? res.warning ?? "SOC mode updated.", {
        tone: res.message ? "info" : "success",
      })
      onSaved()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update SOC mode.", { tone: "danger" })
    } finally {
      setSavingMode(false)
      setPendingMode(null)
    }
  }

  async function handleSaveAssignments() {
    if (!analysts) return
    setSavingAssignments(true)
    try {
      const changed = analysts.filter((a) => {
        const wasAssigned = a.assigned_organizations.some((o) => o.id === detail.id)
        return selected.has(a.id) !== wasAssigned
      })
      for (const analyst of changed) {
        const wasAssigned = analyst.assigned_organizations.some((o) => o.id === detail.id)
        const currentIds = analyst.assigned_organizations.map((o) => o.id)
        const nextIds = wasAssigned
          ? currentIds.filter((id) => id !== detail.id)
          : [...currentIds, detail.id]
        await apiUpdateSocAnalystOrganizations(analyst.id, nextIds)
      }
      toast.show("SOC analyst assignments updated.", { tone: "success" })
      onSaved()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update assignments.", { tone: "danger" })
    } finally {
      setSavingAssignments(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-card border border-line bg-surface p-4">
        <p className="text-sm font-medium text-fg-primary">SOC mode</p>
        <p className="mt-1 text-xs text-fg-muted">
          {socAnalystCount === null
            ? "Checking affected members..."
            : `${socAnalystCount} active soc_analyst member${socAnalystCount === 1 ? "" : "s"} in this organization.`}
        </p>

        <div className="mt-3">
          <SegmentedControl
            ariaLabel="SOC mode"
            value={detail.soc_mode}
            onChange={(value) => setPendingMode(value)}
            options={[
              { value: "managed", label: "Managed" },
              { value: "in_house", label: "In-house" },
            ]}
          />
        </div>

        <p className="mt-3 text-xs leading-5 text-fg-muted">
          <strong className="text-fg-secondary">Managed</strong> -- SentinelX's platform SOC team monitors this
          organization; its own soc_analyst members (if any) lose the SOC/incidents modules until switched back.
          <br />
          <strong className="text-fg-secondary">In-house</strong> -- this organization staffs its own SOC; the
          owner can invite soc_analyst members once in this mode.
        </p>
      </div>

      {detail.soc_mode === "managed" && (
        <div className="rounded-card border border-line bg-surface p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-fg-primary">Assigned platform SOC analysts</p>
            <Button variant="primary" disabled={!assignmentsDirty || savingAssignments} onClick={() => void handleSaveAssignments()}>
              {savingAssignments ? "Saving..." : "Save assignments"}
            </Button>
          </div>

          {loadingAnalysts ? (
            <Skeleton count={3} className="mt-3 h-9 w-full" />
          ) : !analysts || analysts.length === 0 ? (
            <div className="mt-3">
              <EmptyState
                title="No platform SOC analysts yet"
                description="Invite platform SOC analysts from the SOC Team page, then assign them here."
              />
            </div>
          ) : (
            <ul className="mt-3 space-y-2">
              {analysts.map((analyst) => (
                <li
                  key={analyst.id}
                  className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-sm"
                >
                  <label className="flex items-center gap-2.5">
                    <input
                      type="checkbox"
                      checked={selected.has(analyst.id)}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(analyst.id)
                          else next.delete(analyst.id)
                          return next
                        })
                      }
                      className="h-4 w-4 rounded border-line accent-brand-500"
                    />
                    <span>
                      <span className="font-medium text-fg-primary">{analyst.name}</span>{" "}
                      <span className="text-xs text-fg-muted">{analyst.email}</span>
                    </span>
                  </label>
                  {!analyst.is_active && <Badge tone="neutral">Inactive</Badge>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <ConfirmDialog
        open={pendingMode !== null}
        onClose={() => setPendingMode(null)}
        onConfirm={() => void handleModeConfirm()}
        title={`Switch to ${pendingMode === "managed" ? "managed" : "in-house"} SOC mode?`}
        impact={
          pendingMode === "managed"
            ? `${socAnalystCount ?? 0} soc_analyst member(s) keep their accounts but lose the SOC/incidents modules until switched back.`
            : "The organization can now assign its own soc_analyst members. This doesn't remove any platform SOC analyst assignments by itself."
        }
        confirmLabel={savingMode ? "Saving..." : "Switch mode"}
        danger={pendingMode === "managed"}
      />
    </div>
  )
}

export default SocTab
