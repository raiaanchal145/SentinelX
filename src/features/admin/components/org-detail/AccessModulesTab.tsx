import { useMemo, useState } from "react"

import ConfirmDialog from "../../../../components/ui/ConfirmDialog"
import SegmentedControl from "../../../../components/ui/SegmentedControl"
import Button from "../../../../components/ui/Button"
import { useToast } from "../../../../components/ui/Toast"
import { MODULE_INFO, MODULE_KEYS } from "../../../../lib/modules"
import { apiUpdateOrganizationModules, ApiError, type OrganizationDetail } from "../../../../lib/api"

type AccessModulesTabProps = {
  detail: OrganizationDetail
  onSaved: () => void
}

/** Platform-level per-module on/off switches for one organization
 * (Prompt B section A3, "Access and modules"). A module the platform
 * disables here is what the owner's own Access page (section B4) shows
 * as locked -- see docs/API_CONTRACT.md's module_disabled_by_platform. */
function AccessModulesTab({ detail, onSaved }: AccessModulesTabProps) {
  const toast = useToast()
  const [pending, setPending] = useState<Record<string, boolean>>(() => {
    const base: Record<string, boolean> = {}
    for (const key of MODULE_KEYS) base[key] = detail.modules[key] ?? true
    return base
  })
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const changes = useMemo(
    () => MODULE_KEYS.filter((key) => pending[key] !== (detail.modules[key] ?? true)),
    [pending, detail.modules],
  )

  async function handleSave() {
    setSaving(true)
    try {
      await apiUpdateOrganizationModules(detail.id, pending)
      toast.show("Module access updated.", { tone: "success" })
      onSaved()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update module access.", { tone: "danger" })
    } finally {
      setSaving(false)
      setConfirmOpen(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-card border border-line bg-surface">
        {MODULE_KEYS.map((key, index) => (
          <div
            key={key}
            className={`flex items-center justify-between gap-4 p-4 ${index > 0 ? "border-t border-line" : ""}`}
          >
            <div>
              <p className="text-sm font-medium text-fg-primary">{MODULE_INFO[key].label}</p>
              <p className="mt-0.5 text-xs text-fg-muted">{MODULE_INFO[key].description}</p>
            </div>
            <SegmentedControl
              ariaLabel={`${MODULE_INFO[key].label} access`}
              value={pending[key] ? "on" : "off"}
              onChange={(value) => setPending((prev) => ({ ...prev, [key]: value === "on" }))}
              options={[
                { value: "on", label: "Enabled" },
                { value: "off", label: "Disabled" },
              ]}
            />
          </div>
        ))}
      </div>

      <div className="flex items-center justify-end gap-3">
        {changes.length > 0 && (
          <p className="text-xs text-fg-muted">
            {changes.length} module{changes.length === 1 ? "" : "s"} changed
          </p>
        )}
        <Button variant="primary" disabled={changes.length === 0} onClick={() => setConfirmOpen(true)}>
          Save changes
        </Button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void handleSave()}
        title="Save module access changes?"
        impact={
          changes.length === 0
            ? "No changes to save."
            : `This will change: ${changes
                .map((key) => `${MODULE_INFO[key].label} -> ${pending[key] ? "Enabled" : "Disabled"}`)
                .join(", ")}.`
        }
        confirmLabel={saving ? "Saving..." : "Save changes"}
        danger={changes.some((key) => !pending[key])}
      />
    </div>
  )
}

export default AccessModulesTab
