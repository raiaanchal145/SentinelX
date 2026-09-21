import { useCallback, useEffect, useMemo, useState } from "react"
import { MoreVertical, Plus, RotateCw, Search, XCircle } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import DropdownMenu, { type DropdownMenuItem } from "../../../components/ui/DropdownMenu"
import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import Tabs from "../../../components/ui/Tabs"
import { useToast } from "../../../components/ui/Toast"
import { useMe } from "../../../lib/me"
import { roleLabel } from "../../../lib/auth"
import InviteMemberDialog from "../components/InviteMemberDialog"

import {
  apiGetOwnerMembers,
  apiListOwnerInvitations,
  apiListTeams,
  apiPatchOwnerMember,
  apiRemoveOwnerMember,
  apiResendInvitation,
  apiRevokeInvitation,
  ApiError,
  type OwnerInvitation,
  type OwnerMember,
  type Team,
} from "../../../lib/api"

type RemoveTarget = { member: OwnerMember }

/** Organization owner: members + pending invitations (Prompt B section
 * B2). Both tabs share one load() so an invite/accept/remove on either
 * side keeps the other's counts in sync. */
function OwnerMembers() {
  const toast = useToast()
  const { me } = useMe()
  const socModeInHouse = me?.organization?.soc_mode === "in_house"

  const [members, setMembers] = useState<OwnerMember[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [invitations, setInvitations] = useState<OwnerInvitation[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [search, setSearch] = useState("")
  const [roleFilter, setRoleFilter] = useState("")
  const [inviteOpen, setInviteOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<RemoveTarget | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError("")
    Promise.all([apiGetOwnerMembers(), apiListTeams(), apiListOwnerInvitations()])
      .then(([membersRes, teamsRes, invitationsRes]) => {
        setMembers(membersRes.members)
        setTeams(teamsRes.teams)
        setInvitations(invitationsRes.invitations.filter((i) => i.kind === "member"))
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load members."))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const teamName = useMemo(() => {
    const byId = new Map(teams.map((t) => [t.id, t.name]))
    return (teamId: string | null) => (teamId ? byId.get(teamId) ?? "Unknown team" : "--")
  }, [teams])

  const filteredMembers = members.filter((m) => {
    const matchesSearch =
      !search.trim() ||
      m.name.toLowerCase().includes(search.trim().toLowerCase()) ||
      m.email.toLowerCase().includes(search.trim().toLowerCase())
    const matchesRole = !roleFilter || m.role === roleFilter
    return matchesSearch && matchesRole
  })

  async function handleToggleActive(member: OwnerMember) {
    setBusyId(member.id)
    try {
      await apiPatchOwnerMember(member.id, { is_active: !member.is_active })
      toast.show(`${member.name} ${member.is_active ? "deactivated" : "activated"}.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update this member.", { tone: "danger" })
    } finally {
      setBusyId(null)
    }
  }

  async function handleChangeRole(member: OwnerMember, role: string) {
    setBusyId(member.id)
    try {
      await apiPatchOwnerMember(member.id, { role })
      toast.show(`${member.name}'s role updated.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update this member's role.", { tone: "danger" })
    } finally {
      setBusyId(null)
    }
  }

  async function handleRemove() {
    if (!removeTarget) return
    const { member } = removeTarget
    setBusyId(member.id)
    try {
      const res = await apiRemoveOwnerMember(member.id)
      toast.show(res.deleted ? `${member.name} removed.` : `${member.name} deactivated (still referenced in history).`, {
        tone: "success",
      })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not remove this member.", { tone: "danger" })
    } finally {
      setBusyId(null)
      setRemoveTarget(null)
    }
  }

  async function handleResendInvitation(invitation: OwnerInvitation) {
    setBusyId(invitation.id)
    try {
      await apiResendInvitation(invitation.id)
      toast.show(`Invitation resent to ${invitation.email}.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not resend this invitation.", { tone: "danger" })
    } finally {
      setBusyId(null)
    }
  }

  async function handleRevokeInvitation(invitation: OwnerInvitation) {
    setBusyId(invitation.id)
    try {
      await apiRevokeInvitation(invitation.id)
      toast.show(`Invitation to ${invitation.email} revoked.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not revoke this invitation.", { tone: "danger" })
    } finally {
      setBusyId(null)
    }
  }

  const assignableRoles = [...(socModeInHouse ? ["soc_analyst"] : []), "security_manager", "it_developer", "auditor"]

  function memberRowActions(member: OwnerMember): DropdownMenuItem[] {
    const items: DropdownMenuItem[] = assignableRoles
      .filter((r) => r !== member.role)
      .map((r) => ({
        key: `role-${r}`,
        label: `Change role to ${roleLabel(r)}`,
        onSelect: () => void handleChangeRole(member, r),
      }))

    items.push({
      key: "toggle-active",
      label: member.is_active ? "Deactivate" : "Activate",
      onSelect: () => void handleToggleActive(member),
    })
    items.push({
      key: "remove",
      label: "Remove",
      danger: true,
      onSelect: () => setRemoveTarget({ member }),
    })
    return items
  }

  const memberColumns: DataTableColumn<OwnerMember>[] = [
    { key: "name", header: "Name", sortValue: (m) => m.name.toLowerCase(), render: (m) => <span className="font-medium text-fg-primary">{m.name}</span> },
    { key: "email", header: "Email", sortValue: (m) => m.email.toLowerCase(), render: (m) => m.email },
    { key: "role", header: "Role", sortValue: (m) => m.role, render: (m) => roleLabel(m.role) },
    { key: "team", header: "Team", render: (m) => teamName(m.team_id) },
    {
      key: "status",
      header: "Status",
      width: "100px",
      sortValue: (m) => (m.is_active ? 0 : 1),
      render: (m) => <Badge tone={m.is_active ? "success" : "neutral"}>{m.is_active ? "Active" : "Inactive"}</Badge>,
    },
    {
      key: "last_login",
      header: "Last login",
      width: "160px",
      sortValue: (m) => m.last_login_at ?? "",
      render: (m) => (m.last_login_at ? new Date(m.last_login_at).toLocaleString() : "Never"),
    },
    {
      key: "actions",
      header: "",
      width: "48px",
      render: (m) => (
        <DropdownMenu
          label={`Actions for ${m.name}`}
          trigger={<IconButton icon={MoreVertical} label={`Actions for ${m.name}`} disabled={busyId === m.id} />}
          items={memberRowActions(m)}
        />
      ),
    },
  ]

  const invitationColumns: DataTableColumn<OwnerInvitation>[] = [
    { key: "email", header: "Email", sortValue: (i) => i.email.toLowerCase(), render: (i) => i.email },
    { key: "role", header: "Role", render: (i) => (i.role ? roleLabel(i.role) : "--") },
    { key: "status", header: "Status", width: "110px", render: (i) => <Badge tone={i.status === "pending" ? "brand" : "neutral"}>{i.status}</Badge> },
    {
      key: "expires_at",
      header: "Expires",
      width: "180px",
      render: (i) => (i.expires_at ? new Date(i.expires_at).toLocaleString() : "--"),
    },
    {
      key: "actions",
      header: "",
      width: "90px",
      render: (i) =>
        i.status === "pending" ? (
          <div className="flex items-center gap-1.5">
            <IconButton icon={RotateCw} label={`Resend invitation to ${i.email}`} disabled={busyId === i.id} onClick={() => void handleResendInvitation(i)} />
            <IconButton icon={XCircle} label={`Revoke invitation to ${i.email}`} disabled={busyId === i.id} onClick={() => void handleRevokeInvitation(i)} />
          </div>
        ) : null,
    },
  ]

  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <div className="space-y-6 p-6 lg:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold text-fg-primary">Members</h1>
              <p className="mt-1 text-xs text-fg-muted">Invite, manage roles, and control access for your team.</p>
            </div>
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setInviteOpen(true)}>
              Invite member
            </Button>
          </div>

          {loadError && !loading ? (
            <EmptyState title="Couldn't load members" description={loadError} action={{ label: "Retry", onClick: load }} />
          ) : (
            <Tabs
              ariaLabel="Members"
              tabs={[
                {
                  id: "members",
                  label: "Members",
                  content: (
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="relative min-w-[220px] flex-1">
                          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" />
                          <input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search by name or email..."
                            aria-label="Search members"
                            className="w-full rounded-control border border-line bg-surface py-2 pl-9 pr-3 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                          />
                        </div>
                        <select
                          value={roleFilter}
                          onChange={(e) => setRoleFilter(e.target.value)}
                          aria-label="Filter by role"
                          className="rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                        >
                          <option value="">All roles</option>
                          {["soc_analyst", "security_manager", "it_developer", "auditor"].map((r) => (
                            <option key={r} value={r}>
                              {roleLabel(r)}
                            </option>
                          ))}
                        </select>
                      </div>

                      <DataTable
                        columns={memberColumns}
                        rows={filteredMembers}
                        getRowId={(m) => m.id}
                        ariaLabel="Members"
                        loading={loading}
                        emptyState={<EmptyState title="No members yet" description="Invite your first team member to get started." />}
                      />
                    </div>
                  ),
                },
                {
                  id: "invitations",
                  label: "Pending invitations",
                  badge: invitations.filter((i) => i.status === "pending").length > 0 && (
                    <Badge tone="brand">{invitations.filter((i) => i.status === "pending").length}</Badge>
                  ),
                  content: (
                    <DataTable
                      columns={invitationColumns}
                      rows={invitations}
                      getRowId={(i) => i.id}
                      ariaLabel="Pending invitations"
                      loading={loading}
                      emptyState={<EmptyState title="No invitations" description="Invitations you send will show up here." />}
                    />
                  ),
                },
              ]}
            />
          )}
        </div>
      </main>

      <InviteMemberDialog
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onInvited={() => {
          toast.show("Invitation sent.", { tone: "success" })
          load()
        }}
        teams={teams}
        socModeInHouse={socModeInHouse}
      />

      <ConfirmDialog
        open={removeTarget !== null}
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => void handleRemove()}
        title={`Remove ${removeTarget?.member.name}?`}
        impact="If they have history in this organization (tickets, audit entries), they'll be deactivated instead of fully removed."
        confirmLabel="Remove"
        danger
      />
    </div>
  )
}

export default OwnerMembers
