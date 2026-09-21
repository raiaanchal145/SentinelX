import { useEffect, useState } from "react"

import Button from "../../../components/ui/Button"
import Drawer from "../../../components/ui/Drawer"
import EmptyState from "../../../components/EmptyState"
import { useToast } from "../../../components/ui/Toast"
import { roleLabel } from "../../../lib/auth"
import { apiSetTeamMembers, ApiError, type OwnerMember, type Team } from "../../../lib/api"

type TeamMembersDrawerProps = {
  team: Team | null
  members: OwnerMember[]
  onClose: () => void
  onSaved: () => void
}

/** Manage-members drawer for one team (Prompt B section B3). A member
 * can only be on one team at a time -- checking them here for this
 * team unchecks them from whichever team they were on before (backend
 * enforces this via users.team_id, see docs/DECISIONS.md). */
function TeamMembersDrawer({ team, members, onClose, onSaved }: TeamMembersDrawerProps) {
  const toast = useToast()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!team) return
    setSelected(new Set(members.filter((m) => m.team_id === team.id).map((m) => m.id)))
  }, [team, members])

  async function handleSave() {
    if (!team) return
    setSaving(true)
    try {
      await apiSetTeamMembers(team.id, Array.from(selected))
      toast.show(`${team.name}'s members updated.`, { tone: "success" })
      onSaved()
      onClose()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update this team's members.", { tone: "danger" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={team !== null} onClose={onClose} side="right" title={team ? `${team.name} members` : "Team members"}>
      {members.length === 0 ? (
        <EmptyState title="No members yet" description="Invite members to your organization first." />
      ) : (
        <div className="space-y-4">
          <ul className="space-y-2">
            {members.map((member) => {
              const onOtherTeam = member.team_id !== null && member.team_id !== team?.id
              return (
                <li
                  key={member.id}
                  className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-sm"
                >
                  <label className="flex items-center gap-2.5">
                    <input
                      type="checkbox"
                      checked={selected.has(member.id)}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(member.id)
                          else next.delete(member.id)
                          return next
                        })
                      }
                      className="h-4 w-4 rounded border-line accent-brand-500"
                    />
                    <span>
                      <span className="font-medium text-fg-primary">{member.name}</span>{" "}
                      <span className="text-xs text-fg-muted">{roleLabel(member.role)}</span>
                    </span>
                  </label>
                  {onOtherTeam && <span className="text-xs text-fg-faint">Moves from another team</span>}
                </li>
              )
            })}
          </ul>

          <Button variant="primary" className="w-full" disabled={saving} onClick={() => void handleSave()}>
            {saving ? "Saving..." : "Save members"}
          </Button>
        </div>
      )}
    </Drawer>
  )
}

export default TeamMembersDrawer
