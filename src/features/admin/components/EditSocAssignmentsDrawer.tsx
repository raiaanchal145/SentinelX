import { useEffect, useMemo, useState } from "react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Drawer from "../../../components/ui/Drawer"
import EmptyState from "../../../components/EmptyState"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import {
  apiListOrganizations,
  apiUpdateSocAnalystOrganizations,
  ApiError,
  type OrganizationRow,
  type SocAnalyst,
} from "../../../lib/api"

type EditSocAssignmentsDrawerProps = {
  analyst: SocAnalyst | null
  onClose: () => void
  onSaved: () => void
}

/** Only managed, non-archived organizations can be assigned to a
 * platform SOC analyst (docs/API_CONTRACT.md's invalid_organization_
 * assignment) -- fetched fresh each time the drawer opens so a recently
 * archived or mode-switched organization can't be picked. */
function EditSocAssignmentsDrawer({ analyst, onClose, onSaved }: EditSocAssignmentsDrawerProps) {
  const toast = useToast()
  const [eligibleOrgs, setEligibleOrgs] = useState<OrganizationRow[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!analyst) return
    setLoading(true)
    setSelected(new Set(analyst.assigned_organizations.map((o) => o.id)))
    apiListOrganizations({ soc_mode: "managed", page_size: 100 })
      .then((res) => setEligibleOrgs(res.organizations.filter((o) => o.status !== "archived")))
      .catch(() => setEligibleOrgs(null))
      .finally(() => setLoading(false))
  }, [analyst])

  const dirty = useMemo(() => {
    if (!analyst) return false
    const original = new Set(analyst.assigned_organizations.map((o) => o.id))
    if (original.size !== selected.size) return true
    for (const id of original) if (!selected.has(id)) return true
    return false
  }, [analyst, selected])

  async function handleSave() {
    if (!analyst) return
    setSaving(true)
    try {
      await apiUpdateSocAnalystOrganizations(analyst.id, Array.from(selected))
      toast.show(`Assignments updated for ${analyst.name}.`, { tone: "success" })
      onSaved()
      onClose()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update assignments.", { tone: "danger" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={analyst !== null} onClose={onClose} side="right" title={analyst ? `Assign organizations to ${analyst.name}` : "Assign organizations"}>
      {loading ? (
        <Skeleton count={4} className="h-9 w-full" />
      ) : !eligibleOrgs || eligibleOrgs.length === 0 ? (
        <EmptyState
          title="No eligible organizations"
          description="Only managed, non-archived organizations can be assigned to a platform SOC analyst."
        />
      ) : (
        <div className="space-y-4">
          <ul className="space-y-2">
            {eligibleOrgs.map((org) => (
              <li
                key={org.id}
                className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-sm"
              >
                <label className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={selected.has(org.id)}
                    onChange={(e) =>
                      setSelected((prev) => {
                        const next = new Set(prev)
                        if (e.target.checked) next.add(org.id)
                        else next.delete(org.id)
                        return next
                      })
                    }
                    className="h-4 w-4 rounded border-line accent-brand-500"
                  />
                  <span className="font-medium text-fg-primary">{org.name}</span>
                </label>
                <Badge tone={org.status === "active" ? "success" : "brand"}>{org.status}</Badge>
              </li>
            ))}
          </ul>

          <Button variant="primary" className="w-full" disabled={!dirty || saving} onClick={() => void handleSave()}>
            {saving ? "Saving..." : "Save assignments"}
          </Button>
        </div>
      )}
    </Drawer>
  )
}

export default EditSocAssignmentsDrawer
