import Badge from "../../../components/ui/Badge"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import EmptyState from "../../../components/EmptyState"
import SeverityBadge from "../../../components/SeverityBadge"
import type { IncidentRow } from "../../../lib/api"
import { SEVERITY_ORDER } from "../../../types/common"

import { ageLabel } from "./alertShared"
import { INCIDENT_STATUS_LABELS } from "./incidentShared"

/** Tone for an incident status badge (no new colors -- the Badge tones
 * already in use across the SOC workspace). */
function statusTone(status: IncidentRow["status"]): "brand" | "neutral" | "danger" | "success" {
  switch (status) {
    case "NEW":
    case "REOPENED":
      return "brand"
    case "RESOLVED":
      return "success"
    case "FALSE_POSITIVE":
    case "DUPLICATE":
      return "neutral"
    default:
      return "neutral"
  }
}

type IncidentTableProps = {
  incidents: IncidentRow[]
  loading: boolean
  error?: string
  onRetry?: () => void
  onOpen: (incident: IncidentRow) => void
  /** Human-readable names for organizations; when provided (and non-empty)
   * the Organization column is rendered -- only the platform-side multi-org
   * views pass this. Single-organization viewers never see the column. */
  orgName?: (organizationId: string) => string
  /** Per-row assignee display name resolver (resolved client-side). */
  assigneeName?: (incident: IncidentRow) => string | null
  emptyTitle?: string
  emptyDescription?: string
  ariaLabel?: string
}

function IncidentTable({
  incidents,
  loading,
  error,
  onRetry,
  onOpen,
  orgName,
  assigneeName,
  emptyTitle = "No incidents",
  emptyDescription = "No incidents match the current filters.",
  ariaLabel = "Incidents",
}: IncidentTableProps) {
  const columns: DataTableColumn<IncidentRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      sortValue: (i) => SEVERITY_ORDER[i.severity],
      render: (i) => <SeverityBadge severity={i.severity} showIcon />,
    },
    {
      key: "title",
      header: "Incident",
      render: (i) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-fg-primary" title={i.title}>
            {i.title}
          </p>
          {i.summary && (
            <p className="truncate text-xs text-fg-muted" title={i.summary}>
              {i.summary}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "140px",
      render: (i) => <Badge tone={statusTone(i.status)}>{INCIDENT_STATUS_LABELS[i.status] ?? i.status}</Badge>,
    },
    ...(orgName
      ? [
          {
            key: "organization",
            header: "Organization",
            width: "160px",
            render: (i: IncidentRow) => <span className="truncate text-xs">{orgName(i.organization_id)}</span>,
          },
        ]
      : []),
    {
      key: "age",
      header: "Age",
      width: "80px",
      sortValue: (i) => (i.opened_at ? new Date(i.opened_at).getTime() : 0),
      render: (i) => <span title={i.opened_at ? new Date(i.opened_at).toString() : undefined}>{ageLabel(i.opened_at)}</span>,
    },
    {
      key: "alerts",
      header: "Alerts",
      width: "64px",
      sortValue: (i) => i.alert_count ?? 0,
      render: (i) => i.alert_count ?? 0,
    },
    {
      key: "ticket",
      header: "Ticket",
      width: "120px",
      render: (i) =>
        i.open_ticket ? (
          <span className="flex items-center gap-1.5 text-xs">
            <span className="font-mono" title={i.open_ticket.ticket_number}>
              {i.open_ticket.ticket_number}
            </span>
            <Badge tone={i.open_ticket.status === "VERIFICATION" ? "brand" : "neutral"}>{i.open_ticket.status}</Badge>
          </span>
        ) : (
          <span className="text-xs text-fg-faint">--</span>
        ),
    },
    {
      key: "assignee",
      header: "Assignee",
      width: "140px",
      render: (i) => {
        const name = assigneeName?.(i)
        return name ? <span className="truncate text-xs">{name}</span> : <span className="text-xs text-fg-faint">Unassigned</span>
      },
    },
  ]

  if (error) {
    return (
      <div className="rounded-card border border-danger-fg/30 bg-surface p-6 text-center">
        <p className="text-sm text-danger-fg">{error}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-control border border-line px-3 py-1.5 text-xs text-fg-secondary hover:border-line-strong"
          >
            Try again
          </button>
        )}
      </div>
    )
  }

  if (loading) {
    return (
      <div className="space-y-2" role="status" aria-label="Loading incidents">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-10 animate-pulse rounded-control bg-surface-hover" style={{ animationDuration: "1.6s" }} />
        ))}
      </div>
    )
  }

  return (
    <DataTable
      columns={columns}
      rows={incidents}
      getRowId={(i) => i.id}
      ariaLabel={ariaLabel}
      onRowActivate={onOpen}
      emptyState={<EmptyState title={emptyTitle} description={emptyDescription} />}
    />
  )
}

export default IncidentTable
