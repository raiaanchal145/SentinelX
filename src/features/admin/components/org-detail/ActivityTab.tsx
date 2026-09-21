import { useEffect, useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"

import EmptyState from "../../../../components/EmptyState"
import IconButton from "../../../../components/ui/IconButton"
import Skeleton from "../../../../components/ui/Skeleton"
import { apiGetOrganizationActivity, ApiError, type AuditEntry } from "../../../../lib/api"

const PAGE_SIZE = 20

function ActivityTab({ organizationId }: { organizationId: string }) {
  const [page, setPage] = useState(1)
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  function load() {
    setLoading(true)
    setLoadError("")
    apiGetOrganizationActivity(organizationId, page, PAGE_SIZE)
      .then((res) => {
        setEntries(res.entries)
        setTotal(res.total)
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load activity."))
      .finally(() => setLoading(false))
  }

  useEffect(load, [organizationId, page])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  if (loadError && !loading) {
    return <EmptyState title="Couldn't load activity" description={loadError} action={{ label: "Retry", onClick: load }} />
  }

  if (loading) {
    return <Skeleton count={8} className="h-10 w-full" />
  }

  if (entries.length === 0) {
    return <EmptyState title="No activity yet" description="Audit events for this organization will show up here." />
  }

  return (
    <div className="space-y-4">
      <ul className="divide-y divide-line rounded-card border border-line bg-surface">
        {entries.map((entry) => (
          <li key={entry.id} className="flex items-center justify-between gap-4 p-3 text-sm">
            <div>
              <p className="font-medium text-fg-primary">{entry.action}</p>
              <p className="text-xs text-fg-muted">
                {entry.actor_type}
                {entry.target_type ? ` -> ${entry.target_type}` : ""}
              </p>
            </div>
            <span className="shrink-0 text-xs text-fg-muted">
              {entry.created_at ? new Date(entry.created_at).toLocaleString() : "--"}
            </span>
          </li>
        ))}
      </ul>

      <div className="flex items-center justify-between text-xs text-fg-muted">
        <span>
          Page {page} of {totalPages} &middot; {total} entries
        </span>
        <div className="flex items-center gap-2">
          <IconButton icon={ChevronLeft} label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} />
          <IconButton
            icon={ChevronRight}
            label="Next page"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          />
        </div>
      </div>
    </div>
  )
}

export default ActivityTab
