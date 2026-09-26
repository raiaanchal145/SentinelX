import KpiCard from "../../../components/ui/KpiCard"
import Skeleton from "../../../components/ui/Skeleton"
import type { AlertRow } from "../../../lib/api"

import { computeAlertKpis } from "./alertShared"

type AlertKpiRowProps = {
  alerts: AlertRow[]
  loading: boolean
  /** Links each KPI to its queue view; omit to render static cards. */
  alertsPath?: string
}

/**
 * The five SOC KPIs computed client-side from the (limit-capped) alert
 * page: open, unacknowledged, median age, and counts by severity.
 * Deliberately no new backend endpoint (docs/DECISIONS.md).
 */
function AlertKpiRow({ alerts, loading, alertsPath }: AlertKpiRowProps) {
  if (loading) {
    return (
      <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-card" />
        ))}
      </section>
    )
  }

  const kpis = computeAlertKpis(alerts)
  // When no queue path is given (read-only oversight), the cards render
  // without links instead of pointing at a page the viewer can't use.
  const link = (suffix = "") => (alertsPath ? `${alertsPath}${suffix}` : undefined)

  return (
    <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <KpiCard label="Open alerts" value={kpis.open} link={link()} />
      <KpiCard label="Unacknowledged" value={kpis.unacknowledged} link={link("?status=new")} tone="high" />
      <KpiCard label="Median age" value={kpis.medianAge === 0 ? "--" : `${kpis.medianAge}m`} />
      {(["critical", "high", "medium", "low"] as const).map((severity) => (
        <KpiCard
          key={severity}
          label={`${severity.charAt(0).toUpperCase()}${severity.slice(1)} severity`}
          value={kpis.bySeverity[severity] ?? 0}
          tone={severity === "critical" ? "critical" : severity === "high" ? "high" : severity === "medium" ? "medium" : "low"}
          link={link(`?severity=${severity}`)}
        />
      ))}
    </section>
  )
}

export default AlertKpiRow
