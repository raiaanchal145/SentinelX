import { useCallback, useEffect, useState } from "react"
import { Bot, CheckCircle, DollarSign, Percent, RefreshCw, Sliders } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import { apiAiMetrics } from "../../../lib/aiAnalysisApi"

type AiMetricsData = {
  total_analyses: number
  ai_analyses: number
  rules_analyses: number
  decisions: {
    total_decisions: number | null
    accepted: number
    edited: number
    rejected: number
    acceptance_rate: number
    override_rate: number
    average_confidence: number
  }
  cost: {
    total_spend_usd: number
  }
}

export default function AiMetricsCard({ organizationId }: { organizationId?: string }) {
  const [data, setData] = useState<AiMetricsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = useCallback(() => {
    setLoading(true)
    setError("")
    apiAiMetrics(organizationId)
      .then((res) => {
        setData(res)
        setError("")
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not load AI metrics.")
      })
      .finally(() => setLoading(false))
  }, [organizationId])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section aria-label="AI operations & metrics" className="rounded-card border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-brand-300" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-fg-primary">AI Operations &amp; Metrics</h2>
        </div>
        <IconButton icon={RefreshCw} label="Refresh AI metrics" onClick={load} />
      </div>

      {error ? (
        <div className="mt-3">
          <p className="text-xs text-danger-fg">{error}</p>
          <button type="button" onClick={load} className="mt-2 text-xs text-brand-400 hover:text-brand-300">
            Try again
          </button>
        </div>
      ) : loading && !data ? (
        <Skeleton className="mt-3 h-20 w-full" />
      ) : !data || data.total_analyses === 0 ? (
        <div className="mt-3 rounded-control border border-dashed border-line bg-surface-sunken p-3 text-xs text-fg-muted">
          No AI analyses recorded yet. Triage runs automatically for incoming alerts when AI is enabled.
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div className="rounded-control border border-line bg-surface-sunken p-2.5">
              <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                <CheckCircle size={12} className="text-success-fg" />
                Acceptance
              </span>
              <p className="mt-1 font-semibold text-fg-primary text-sm">
                {data.decisions.total_decisions ? `${Math.round(data.decisions.acceptance_rate * 100)}%` : "--"}
              </p>
              <p className="text-[10px] text-fg-faint">{data.decisions.accepted} accepted</p>
            </div>

            <div className="rounded-control border border-line bg-surface-sunken p-2.5">
              <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                <Percent size={12} className="text-brand-300" />
                Avg Confidence
              </span>
              <p className="mt-1 font-semibold text-fg-primary text-sm">
                {data.ai_analyses > 0 ? `${Math.round(data.decisions.average_confidence * 100)}%` : "--"}
              </p>
              <p className="text-[10px] text-fg-faint">{data.ai_analyses} AI runs</p>
            </div>

            <div className="rounded-control border border-line bg-surface-sunken p-2.5">
              <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                <Sliders size={12} className="text-warning-fg" />
                Override Rate
              </span>
              <p className="mt-1 font-semibold text-fg-primary text-sm">
                {data.decisions.total_decisions ? `${Math.round(data.decisions.override_rate * 100)}%` : "--"}
              </p>
              <p className="text-[10px] text-fg-faint">{data.decisions.edited} edited</p>
            </div>

            <div className="rounded-control border border-line bg-surface-sunken p-2.5">
              <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                <DollarSign size={12} className="text-fg-secondary" />
                Est. Cost
              </span>
              <p className="mt-1 font-semibold text-fg-primary text-sm">
                ${data.cost.total_spend_usd.toFixed(4)}
              </p>
              <p className="text-[10px] text-fg-faint">{data.total_analyses} total runs</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line/50 pt-2 text-xs">
            <span className="text-fg-muted">
              {data.rules_analyses > 0 ? (
                <span>
                  {data.rules_analyses} deterministic {data.rules_analyses === 1 ? "fallback" : "fallbacks"}
                </span>
              ) : (
                <span>All analyses generated by AI</span>
              )}
            </span>
            <div className="flex items-center gap-1.5">
              <Badge tone={data.decisions.rejected > 0 ? "danger" : "neutral"}>
                {data.decisions.rejected} rejected
              </Badge>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
