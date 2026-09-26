import Badge from "../../../components/ui/Badge"
import DataTable, { type DataTableColumn } from "../../../components/ui/DataTable"
import EmptyState from "../../../components/EmptyState"
import SeverityBadge from "../../../components/SeverityBadge"
import type { AlertRow } from "../../../lib/api"
import { SEVERITY_ORDER } from "../../../types/common"

import { ageLabel } from "./alertShared"

type AlertTableProps = {
  alerts: AlertRow[]
  loading: boolean
  error?: string
  onRetry?: () => void
  onOpen: (alert: AlertRow) => void
  /** Human-readable names for organizations; when provided (and non-empty)
   * the Organization column is rendered -- only the platform-side multi-org
   * queue passes this. Single-organization viewers never see the column. */
  orgName?: (organizationId: string) => string
  /** Per-row assignee display name resolver (resolved client-side). */
  assigneeName?: (alert: AlertRow) => string | null
  /** Row-level hotkeys forwarded from DataTable (j/k/a handled by the page). */
  onRowKeyDown?: (alert: AlertRow, event: React.KeyboardEvent<HTMLTableRowElement>) => void
  emptyTitle?: string
  emptyDescription?: string
  ariaLabel?: string
}

function AlertTable({
  alerts,
  loading,
  error,
  onRetry,
  onOpen,
  orgName,
  assigneeName,
  onRowKeyDown,
  emptyTitle = "No alerts",
  emptyDescription = "No alerts match the current filters.",
  ariaLabel = "Alerts",
}: AlertTableProps) {
  const columns: DataTableColumn<AlertRow>[] = [
    {
      key: "severity",
      header: "Severity",
      width: "110px",
      sortValue: (a) => SEVERITY_ORDER[a.severity],
      render: (a) => <SeverityBadge severity={a.severity} showIcon />,
    },
    {
      key: "title",
      header: "Alert",
      render: (a) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-fg-primary" title={a.title}>
            {a.title}
          </p>
          <p className="truncate text-xs text-fg-muted" title={a.rule_name ?? undefined}>
            {a.rule_name ?? "--"}
          </p>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "110px",
      render: (a) => (
        <Badge tone={a.status === "new" ? "brand" : a.status === "dismissed" ? "neutral" : "neutral"}>{a.status}</Badge>
      ),
    },
    {
      key: "asset",
      header: "Asset",
      width: "140px",
      render: (a) =>
        a.asset_id ? (
          <span className="truncate font-mono text-xs text-fg-secondary" title={a.asset_id}>
            {a.asset_id.slice(0, 8)}…
          </span>
        ) : (
          <span className="text-fg-faint">--</span>
        ),
    },
    ...(orgName
      ? [
          {
            key: "organization",
            header: "Organization",
            width: "160px",
            render: (a: AlertRow) => <span className="truncate text-xs">{orgName(a.organization_id)}</span>,
          },
        ]
      : []),
    {
      key: "age",
      header: "Age",
      width: "80px",
      sortValue: (a) => (a.first_seen_at ? new Date(a.first_seen_at).getTime() : 0),
      render: (a) => (
        <span title={a.first_seen_at ? new Date(a.first_seen_at).toString() : undefined}>{ageLabel(a.first_seen_at)}</span>
      ),
    },
    {
      key: "events",
      header: "Events",
      width: "72px",
      sortValue: (a) => a.event_count,
      render: (a) => a.event_count,
    },
    {
      key: "assignee",
      header: "Assignee",
      width: "140px",
      render: (a) => {
        const name = assigneeName?.(a)
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
      <div className="space-y-2" role="status" aria-label="Loading alerts">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-10 animate-pulse rounded-control bg-surface-hover" style={{ animationDuration: "1.6s" }} />
        ))}
      </div>
    )
  }

  return (
    <DataTable
      columns={columns}
      rows={alerts}
      getRowId={(a) => a.id}
      ariaLabel={ariaLabel}
      onRowActivate={onOpen}
      onRowKeyDown={onRowKeyDown}
      emptyState={<EmptyState title={emptyTitle} description={emptyDescription} />}
    />
  )
}

export default AlertTable
