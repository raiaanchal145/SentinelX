import { Link, useNavigate } from "react-router-dom"
import Drawer from "../../../components/ui/Drawer"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import type { Alert, Asset, AppUser } from "../../../types"

type AlertDetailDrawerProps = {
  open: boolean
  onClose: () => void
  alert: Alert | null
  asset: Asset | undefined
  assignee: AppUser | undefined
}

/** Enter (or a row click) on the triage queue opens this. Related-event
 * detail is summarized from the alert's own eventCount -- there's no
 * separate per-event mock list yet, so this doesn't fabricate one. */
function AlertDetailDrawer({ open, onClose, alert, asset, assignee }: AlertDetailDrawerProps) {
  const navigate = useNavigate()
  if (!alert) return null

  const firstSeen = new Date(alert.firstSeenAt)
  const lastSeen = new Date(alert.lastSeenAt)

  return (
    <Drawer open={open} onClose={onClose} title={alert.title} side="right" widthClassName="w-full max-w-md">
      <div className="space-y-5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={alert.severity} showIcon />
          <Badge tone="neutral">{alert.status}</Badge>
          <Badge tone="brand">{alert.confidence}% confidence</Badge>
        </div>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Summary</h3>
          <p className="mt-1 text-fg-secondary">{alert.summary}</p>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Related events</h3>
          <p className="mt-1 text-fg-secondary">
            {alert.eventCount} related events, first seen{" "}
            <time dateTime={alert.firstSeenAt} title={firstSeen.toString()}>
              {firstSeen.toLocaleString()}
            </time>
            , most recently{" "}
            <time dateTime={alert.lastSeenAt} title={lastSeen.toString()}>
              {lastSeen.toLocaleString()}
            </time>
            .
          </p>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Affected asset</h3>
          {asset ? (
            <div className="mt-1 rounded-control border border-line bg-surface-sunken p-3">
              <p className="font-medium text-fg-primary">{asset.hostname}</p>
              <p className="mt-0.5 text-xs text-fg-muted">
                {asset.assetType} &middot; {asset.environment} &middot; criticality: {asset.criticality}
              </p>
              <Link to="/soc/assets" className="mt-2 inline-block text-xs font-medium text-brand-400 hover:text-brand-300">
                View in asset inventory
              </Link>
            </div>
          ) : (
            <p className="mt-1 text-fg-muted">No asset on file.</p>
          )}
        </section>

        <section className="rounded-panel border border-brand-500/20 bg-brand-500/5 p-3">
          <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-brand-300">
            AI analysis <span className="normal-case text-fg-faint">&middot; verify before acting</span>
          </h3>
          <p className="mt-1 text-fg-secondary">
            {alert.detectionRuleName} fired on {asset?.hostname ?? "this asset"} with {alert.eventCount} correlated
            events and {alert.confidence}% model confidence. Review the evidence above before treating this as
            confirmed.
          </p>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Assignee</h3>
          <p className="mt-1 text-fg-secondary">{assignee ? assignee.name : "Unassigned"}</p>
        </section>

        {alert.incidentId && (
          <Button
            variant="secondary"
            className="w-full"
            onClick={() => {
              onClose()
              navigate(`/soc/incidents/${alert.incidentId}`)
            }}
          >
            Open linked incident
          </Button>
        )}
      </div>
    </Drawer>
  )
}

export default AlertDetailDrawer
