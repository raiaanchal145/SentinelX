import { useEffect, useState } from "react"
import { UserX } from "lucide-react"

import Badge from "../../../../components/ui/Badge"
import ConfirmDialog from "../../../../components/ui/ConfirmDialog"
import DataTable, { type DataTableColumn } from "../../../../components/ui/DataTable"
import EmptyState from "../../../../components/EmptyState"
import IconButton from "../../../../components/ui/IconButton"
import { useToast } from "../../../../components/ui/Toast"
import { roleLabel } from "../../../../lib/auth"
import {
  apiDeactivateOrganizationMember,
  apiGetOrganizationMembers,
  ApiError,
  type OrganizationMember,
} from "../../../../lib/api"

/** Platform admin's read-only member list for one organization (Prompt
 * B section A3) -- the only mutation available here is deactivation;
 * inviting/editing members is the organization owner's job (section B2). */
function MembersTab({ organizationId }: { organizationId: string }) {
  const toast = useToast()
  const [members, setMembers] = useState<OrganizationMember[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [confirmTarget, setConfirmTarget] = useState<OrganizationMember | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  function load() {
    setLoading(true)
    setLoadError("")
    apiGetOrganizationMembers(organizationId)
      .then((res) => setMembers(res.members))
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load members."))
      .finally(() => setLoading(false))
  }

  useEffect(load, [organizationId])

  async function handleDeactivate() {
    if (!confirmTarget) return
    setBusyId(confirmTarget.id)
    try {
      await apiDeactivateOrganizationMember(organizationId, confirmTarget.account_type, confirmTarget.id)
      toast.show(`${confirmTarget.name} deactivated.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not deactivate this member.", { tone: "danger" })
    } finally {
      setBusyId(null)
      setConfirmTarget(null)
    }
  }

  const columns: DataTableColumn<OrganizationMember>[] = [
    {
      key: "name",
      header: "Name",
      sortValue: (m) => m.name.toLowerCase(),
      render: (m) => <span className="font-medium text-fg-primary">{m.name}</span>,
    },
    { key: "email", header: "Email", sortValue: (m) => m.email.toLowerCase(), render: (m) => m.email },
    {
      key: "role",
      header: "Role",
      sortValue: (m) => m.role,
      render: (m) => roleLabel(m.role),
    },
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
      render: (m) =>
        m.is_active ? (
          <IconButton
            icon={UserX}
            label={`Deactivate ${m.name}`}
            disabled={busyId === m.id}
            onClick={() => setConfirmTarget(m)}
          />
        ) : null,
    },
  ]

  if (loadError && !loading) {
    return <EmptyState title="Couldn't load members" description={loadError} action={{ label: "Retry", onClick: load }} />
  }

  return (
    <div className="space-y-4">
      <DataTable
        columns={columns}
        rows={members ?? []}
        getRowId={(m) => `${m.account_type}:${m.id}`}
        ariaLabel="Organization members"
        loading={loading}
        emptyState={<EmptyState title="No members yet" description="This organization has no members yet." />}
      />

      <ConfirmDialog
        open={confirmTarget !== null}
        onClose={() => setConfirmTarget(null)}
        onConfirm={() => void handleDeactivate()}
        title={`Deactivate ${confirmTarget?.name}?`}
        impact="They will immediately lose access to sign in. This can be reversed later by the organization owner."
        confirmLabel="Deactivate"
        danger
      />
    </div>
  )
}

export default MembersTab
