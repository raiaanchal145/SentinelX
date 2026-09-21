import { useCallback, useEffect, useState } from "react"
import { Plus, Settings2, UserCheck, UserX } from "lucide-react"

import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ConfirmDialog from "../../../components/ui/ConfirmDialog"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import EmptyState from "../../../components/EmptyState"
import IconButton from "../../../components/ui/IconButton"
import { useToast } from "../../../components/ui/Toast"
import InviteSocAnalystDialog from "../components/InviteSocAnalystDialog"
import EditSocAssignmentsDrawer from "../components/EditSocAssignmentsDrawer"

import { apiListSocAnalysts, apiPatchSocAnalyst, ApiError, type SocAnalyst } from "../../../lib/api"

/** Platform admin: the platform SOC team roster (Prompt B section A4).
 * See docs/API_CONTRACT.md ("Platform admin: /api/v1/admin/soc-
 * analysts"). */
function SocTeam() {
  const toast = useToast()
  const [analysts, setAnalysts] = useState<SocAnalyst[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [inviteOpen, setInviteOpen] = useState(false)
  const [editingAnalyst, setEditingAnalyst] = useState<SocAnalyst | null>(null)
  const [statusTarget, setStatusTarget] = useState<SocAnalyst | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError("")
    apiListSocAnalysts()
      .then((res) => setAnalysts(res.soc_analysts))
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load the SOC team."))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleToggleActive() {
    if (!statusTarget) return
    setBusyId(statusTarget.id)
    try {
      await apiPatchSocAnalyst(statusTarget.id, !statusTarget.is_active)
      toast.show(`${statusTarget.name} ${statusTarget.is_active ? "deactivated" : "reactivated"}.`, {
        tone: "success",
      })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update this analyst.", { tone: "danger" })
    } finally {
      setBusyId(null)
      setStatusTarget(null)
    }
  }

  const columns: DataTableColumn<SocAnalyst>[] = [
    {
      key: "name",
      header: "Name",
      sortValue: (a) => a.name.toLowerCase(),
      render: (a) => <span className="font-medium text-fg-primary">{a.name}</span>,
    },
    { key: "email", header: "Email", sortValue: (a) => a.email.toLowerCase(), render: (a) => a.email },
    {
      key: "status",
      header: "Status",
      width: "100px",
      sortValue: (a) => (a.is_active ? 0 : 1),
      render: (a) => <Badge tone={a.is_active ? "success" : "neutral"}>{a.is_active ? "Active" : "Inactive"}</Badge>,
    },
    {
      key: "assigned",
      header: "Assigned organizations",
      render: (a) =>
        a.assigned_organizations.length === 0 ? (
          <span className="text-fg-faint">None</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {a.assigned_organizations.map((org) => (
              <Badge key={org.id} tone="neutral">
                {org.name}
              </Badge>
            ))}
          </div>
        ),
    },
    {
      key: "last_login",
      header: "Last login",
      width: "160px",
      sortValue: (a) => a.last_login_at ?? "",
      render: (a) => (a.last_login_at ? new Date(a.last_login_at).toLocaleString() : "Never"),
    },
    {
      key: "actions",
      header: "",
      width: "100px",
      render: (a) => (
        <div className="flex items-center gap-1.5">
          <IconButton
            icon={Settings2}
            label={`Edit assignments for ${a.name}`}
            onClick={() => setEditingAnalyst(a)}
          />
          <IconButton
            icon={a.is_active ? UserX : UserCheck}
            label={a.is_active ? `Deactivate ${a.name}` : `Reactivate ${a.name}`}
            disabled={busyId === a.id}
            onClick={() => setStatusTarget(a)}
          />
        </div>
      ),
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
              <p className="text-sm text-brand-400">System Administration</p>
              <h1 className="mt-2 text-2xl font-semibold text-fg-primary">Platform SOC Team</h1>
              <p className="mt-1 text-xs text-fg-muted">
                Platform SOC analysts and which managed organizations they're assigned to.
              </p>
            </div>
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setInviteOpen(true)}>
              Invite SOC analyst
            </Button>
          </div>

          {loadError && !loading ? (
            <EmptyState title="Couldn't load the SOC team" description={loadError} action={{ label: "Retry", onClick: load }} />
          ) : (
            <DataTable
              columns={columns}
              rows={analysts}
              getRowId={(a) => a.id}
              ariaLabel="Platform SOC analysts"
              loading={loading}
              emptyState={
                <EmptyState
                  title="No platform SOC analysts yet"
                  description="Invite one to start staffing managed organizations' SOC."
                />
              }
            />
          )}
        </div>
      </main>

      <InviteSocAnalystDialog
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onInvited={() => {
          toast.show("Invitation sent.", { tone: "success" })
          load()
        }}
      />

      <EditSocAssignmentsDrawer analyst={editingAnalyst} onClose={() => setEditingAnalyst(null)} onSaved={load} />

      <ConfirmDialog
        open={statusTarget !== null}
        onClose={() => setStatusTarget(null)}
        onConfirm={() => void handleToggleActive()}
        title={statusTarget?.is_active ? `Deactivate ${statusTarget?.name}?` : `Reactivate ${statusTarget?.name}?`}
        impact={
          statusTarget?.is_active
            ? "They will immediately lose access to sign in. Their organization assignments are kept and apply again if reactivated."
            : "They will be able to sign in again."
        }
        confirmLabel={statusTarget?.is_active ? "Deactivate" : "Reactivate"}
        danger={!!statusTarget?.is_active}
      />
    </div>
  )
}

export default SocTeam
