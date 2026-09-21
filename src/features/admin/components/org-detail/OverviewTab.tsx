import KpiCard from "../../../../components/ui/KpiCard"
import Badge from "../../../../components/ui/Badge"
import EmptyState from "../../../../components/EmptyState"
import type { OrganizationDetail } from "../../../../lib/api"

const STATUS_TONE: Record<OrganizationDetail["status"], "brand" | "success" | "danger" | "neutral"> = {
  active: "success",
  suspended: "danger",
  archived: "neutral",
}

function timestamp(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "Never"
}

function OverviewTab({ detail }: { detail: OrganizationDetail }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4 rounded-card border border-line bg-surface p-4">
        <div>
          <p className="text-xs text-fg-muted">Status</p>
          <Badge tone={STATUS_TONE[detail.status]}>{detail.status}</Badge>
        </div>
        <div>
          <p className="text-xs text-fg-muted">SOC mode</p>
          <Badge tone="neutral">{detail.soc_mode === "managed" ? "Managed" : "In-house"}</Badge>
        </div>
        <div>
          <p className="text-xs text-fg-muted">Owner</p>
          {detail.owner ? (
            <p className="text-sm text-fg-secondary">
              {detail.owner.name} &middot; {detail.owner.email}
            </p>
          ) : (
            <p className="text-sm text-fg-faint">Awaiting invite acceptance</p>
          )}
        </div>
        <div>
          <p className="text-xs text-fg-muted">Industry</p>
          <p className="text-sm text-fg-secondary">{detail.industry || "Not set"}</p>
        </div>
      </div>

      <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Members" value={detail.members} />
        <KpiCard label="Pending invites" value={detail.pending_invitations} />
        <KpiCard label="Assets" value={detail.assets} />
        <KpiCard label="Open incidents" value={detail.open_incidents} tone={detail.open_incidents > 0 ? "high" : "neutral"} />
        <KpiCard label="Open tickets" value={detail.open_tickets} tone={detail.open_tickets > 0 ? "medium" : "neutral"} />
      </section>

      <section aria-label="Recent activity" className="rounded-card border border-line bg-surface p-4">
        <h2 className="text-sm font-semibold text-fg-primary">Recent activity</h2>
        {detail.recent_activity.length === 0 ? (
          <div className="mt-3">
            <EmptyState title="No activity yet" description="Audit events for this organization will show up here." />
          </div>
        ) : (
          <ul className="mt-3 space-y-2">
            {detail.recent_activity.map((entry) => (
              <li
                key={entry.id}
                className="flex items-center justify-between rounded-control border border-line bg-surface-sunken p-2.5 text-xs"
              >
                <span className="font-medium text-fg-primary">{entry.action}</span>
                <span className="text-fg-muted">{timestamp(entry.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export default OverviewTab
