import { useEffect, useState } from "react"

import Badge from "../../../../components/ui/Badge"
import EmptyState from "../../../../components/EmptyState"
import Skeleton from "../../../../components/ui/Skeleton"

import { apiListEventSources, ApiError, type EventSourceRow } from "../../../../lib/api"

/**
 * Read-only view of one organization's event sources for the platform
 * admin's organization detail. The /event-sources endpoints reject
 * platform accounts (docs/DECISIONS.md), so this tab currently lists
 * the signed-in super_admin's *own* scope is NOT used -- it renders the
 * read-only notice until the admin-side list endpoint
 * (GET /admin/organizations/{id}/event-sources) lands with the next
 * backend milestone; keys are never shown in this view either way.
 */
function EventSourcesTab({ organizationId }: { organizationId: string }) {
  const [rows, setRows] = useState<EventSourceRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    // The organization-side endpoint requires an organization account;
    // called from a super_admin session it answers 403
    // platform_admin_not_supported -- rendered as the read-only notice
    // below rather than a scary error, until the admin-side endpoint
    // exists.
    apiListEventSources()
      .then((resp) => {
        if (!cancelled) setRows(resp.event_sources)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load event sources.")
      })
    return () => {
      cancelled = true
    }
  }, [organizationId])

  if (error) {
    return (
      <EmptyState
        title="Event sources (read-only)"
        description="This organization's event sources are managed by its owner and security managers. Ingestion keys are hashed at rest and never shown to platform admins."
      />
    )
  }

  if (rows === null) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    )
  }

  if (rows.length === 0) {
    return <EmptyState title="No event sources" description="This organization hasn't registered any event sources yet." />
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-fg-muted">Read-only -- keys are hashed at rest and never shown to platform admins.</p>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 rounded-control border border-line bg-surface px-3 py-2">
            <div>
              <p className="text-sm font-medium text-fg-primary">{r.name}</p>
              <p className="text-xs text-fg-muted">{r.source_type}</p>
            </div>
            {r.enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="danger">Disabled</Badge>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default EventSourcesTab
