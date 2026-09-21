import { useCallback, useEffect, useState } from "react"
import { Pencil, Plus, Trash2, UsersRound } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { useToast } from "../../../components/ui/Toast"
import TeamDialog from "../components/TeamDialog"
import TeamMembersDrawer from "../components/TeamMembersDrawer"

import { apiDeleteTeam, apiGetOwnerMembers, apiListTeams, ApiError, type OwnerMember, type Team } from "../../../lib/api"

/** Organization owner: teams (Prompt B section B3). */
function OwnerTeams() {
  const toast = useToast()
  const [teams, setTeams] = useState<Team[]>([])
  const [members, setMembers] = useState<OwnerMember[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [dialogState, setDialogState] = useState<{ open: boolean; team: Team | null }>({ open: false, team: null })
  const [membersTeam, setMembersTeam] = useState<Team | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Team | null>(null)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError("")
    Promise.all([apiListTeams(), apiGetOwnerMembers()])
      .then(([teamsRes, membersRes]) => {
        setTeams(teamsRes.teams)
        setMembers(membersRes.members)
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load teams."))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await apiDeleteTeam(deleteTarget.id)
      toast.show(`${deleteTarget.name} deleted.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not delete this team.", { tone: "danger" })
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold text-fg-primary">Teams</h1>
              <p className="mt-1 text-xs text-fg-muted">Group your members into teams.</p>
            </div>
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setDialogState({ open: true, team: null })}>
              Create team
            </Button>
          </div>

          {loading ? (
            <Skeleton count={3} className="h-20 w-full" />
          ) : loadError ? (
            <EmptyState title="Couldn't load teams" description={loadError} action={{ label: "Retry", onClick: load }} />
          ) : teams.length === 0 ? (
            <EmptyState title="No teams yet" description="Create a team to start grouping your members." />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {teams.map((team) => (
                <div key={team.id} className="rounded-card border border-line bg-surface p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-medium text-fg-primary">{team.name}</p>
                      {team.description && <p className="mt-1 text-xs text-fg-muted">{team.description}</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <IconButton icon={Pencil} label={`Rename ${team.name}`} onClick={() => setDialogState({ open: true, team })} />
                      <IconButton icon={Trash2} label={`Delete ${team.name}`} onClick={() => setDeleteTarget(team)} />
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setMembersTeam(team)}
                    className="mt-3 flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300"
                  >
                    <UsersRound size={13} aria-hidden="true" />
                    {team.member_count} member{team.member_count === 1 ? "" : "s"} &middot; manage
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      <TeamDialog
        open={dialogState.open}
        team={dialogState.team}
        onClose={() => setDialogState({ open: false, team: null })}
        onSaved={load}
      />

      <TeamMembersDrawer team={membersTeam} members={members} onClose={() => setMembersTeam(null)} onSaved={load} />

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void handleDelete()}
        title={`Delete ${deleteTarget?.name}?`}
        impact="Members on this team aren't removed -- they're just unassigned from it."
        confirmLabel={deleting ? "Deleting..." : "Delete"}
        danger
      />
    </div>
  )
}

export default OwnerTeams
