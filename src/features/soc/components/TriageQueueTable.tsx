import { CheckCheck, Siren, UserPlus, XCircle } from "lucide-react"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import IconButton from "../../../components/ui/IconButton"
import Tooltip from "../../../components/ui/Tooltip"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import EmptyState from "../../../components/EmptyState"
import type { TriageRow } from "../../../lib/data"
import { SEVERITY_ORDER } from "../../../types"

type TriageQueueTableProps = {
  rows: TriageRow[]
  loading: boolean
  onOpenDetail: (row: TriageRow) => void
  onAcknowledge: (row: TriageRow) => void
  onAssignToMe: (row: TriageRow) => void
  onDismiss: (row: TriageRow) => void
  onEscalate: (row: TriageRow) => void
}

function ageLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.round(hours / 24)}d`
}

/** Alerts needing action, sorted severity then age. Row actions stop
 * propagation so clicking an icon doesn't also open the detail drawer;
 * Enter (handled by DataTable) and "a"/"d" hotkeys (via onRowKeyDown)
 * both route through the same handlers as the buttons. */
function TriageQueueTable({
  rows,
  loading,
  onOpenDetail,
  onAcknowledge,
  onAssignToMe,
  onDismiss,
  onEscalate,
}: TriageQueueTableProps) {
  const columns: DataTableColumn<TriageRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      sortValue: (row) => SEVERITY_ORDER[row.alert.severity],
      render: (row) => <SeverityBadge severity={row.alert.severity} showIcon />,
    },
    {
      key: "title",
      header: "Alert",
      render: (row) => (
        <div>
          <p className="font-medium text-fg-primary">{row.alert.title}</p>
          <p className="text-xs text-fg-muted">{row.alert.detectionRuleName}</p>
        </div>
      ),
    },
    {
      key: "asset",
      header: "Asset",
      render: (row) =>
        row.asset ? (
          <div>
            <p className="text-fg-secondary">{row.asset.hostname}</p>
            <p className="text-xs text-fg-muted">criticality: {row.asset.criticality}</p>
          </div>
        ) : (
          <span className="text-fg-faint">--</span>
        ),
    },
    {
      key: "age",
      header: "Age",
      width: "72px",
      sortValue: (row) => new Date(row.alert.firstSeenAt).getTime(),
      render: (row) => <span title={new Date(row.alert.firstSeenAt).toString()}>{ageLabel(row.alert.firstSeenAt)}</span>,
    },
    {
      key: "events",
      header: "Events",
      width: "72px",
      sortValue: (row) => row.alert.eventCount,
      render: (row) => row.alert.eventCount,
    },
    {
      key: "confidence",
      header: "AI confidence",
      width: "110px",
      sortValue: (row) => row.alert.confidence,
      render: (row) => `${row.alert.confidence}%`,
    },
    {
      key: "status",
      header: "Status",
      width: "110px",
      render: (row) => <Badge tone="neutral">{row.alert.status}</Badge>,
    },
    {
      key: "assignee",
      header: "Assignee",
      render: (row) => row.assignee?.name ?? <span className="text-fg-faint">Unassigned</span>,
    },
    {
      key: "actions",
      header: "Actions",
      width: "140px",
      render: (row) => (
        <div className="flex items-center gap-1">
          <Tooltip label="Acknowledge (a)">
            <IconButton
              icon={CheckCheck}
              label={`Acknowledge ${row.alert.title}`}
              size={14}
              onClick={(e) => {
                e.stopPropagation()
                onAcknowledge(row)
              }}
            />
          </Tooltip>
          <Tooltip label="Assign to me">
            <IconButton
              icon={UserPlus}
              label={`Assign ${row.alert.title} to me`}
              size={14}
              onClick={(e) => {
                e.stopPropagation()
                onAssignToMe(row)
              }}
            />
          </Tooltip>
          <Tooltip label="Dismiss as false positive (d)">
            <IconButton
              icon={XCircle}
              label={`Dismiss ${row.alert.title} as false positive`}
              size={14}
              onClick={(e) => {
                e.stopPropagation()
                onDismiss(row)
              }}
            />
          </Tooltip>
          <Tooltip label="Escalate to incident">
            <IconButton
              icon={Siren}
              label={`Escalate ${row.alert.title} to an incident`}
              size={14}
              onClick={(e) => {
                e.stopPropagation()
                onEscalate(row)
              }}
            />
          </Tooltip>
        </div>
      ),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={rows}
      getRowId={(row) => row.alert.id}
      ariaLabel="Triage queue"
      loading={loading}
      onRowActivate={onOpenDetail}
      onRowKeyDown={(row, event) => {
        if (event.key === "a" || event.key === "A") {
          event.preventDefault()
          onAcknowledge(row)
        } else if (event.key === "d" || event.key === "D") {
          event.preventDefault()
          onDismiss(row)
        }
      }}
      emptyState={
        <EmptyState
          title="Queue is clear"
          description="Nothing needs your attention right now -- new alerts will show up here as they come in."
        />
      }
    />
  )
}

export default TriageQueueTable
