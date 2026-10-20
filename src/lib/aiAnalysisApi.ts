/**
 * AI analyses API surface (AlertDrawer / IncidentDetail panels).
 *
 * All requests go through the SAME fetch conventions as src/lib/api.ts
 * (sentinelx_token header, ApiError with the backend's structured
 * detail). The API base comes from src/lib/apiBase.ts -- no URL is
 * inlined here (docs/CONVENTIONS.md).
 */

import { API_BASE } from "./apiBase"

export type AiAnalysisDecision = {
  decision: "accepted" | "edited" | "rejected"
  reason?: string | null
  edits?: Record<string, unknown> | null
  decided_by?: string | null
  decided_at?: string | null
}

export type AiAnalysisView = {
  id: string
  organization_id: string
  agent_run_id: string
  target_type: "alert" | "incident"
  target_id: string
  source: "ai" | "rules" | null
  summary: string | null
  reasoning?: string | null
  confidence: number | null
  severity_suggestion?: string | null
  recommended_actions: Record<string, unknown>
  evidence_ids: string[]
  false_positive_likelihood: number | null
  accepted_by_user_id?: string | null
  accepted_at?: string | null
  decision?: AiAnalysisDecision | null
  created_at?: string | null
}

export class ApiErrorLike extends Error {}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("sentinelx_token")
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    })
  } catch {
    throw new ApiErrorLike("Could not reach the SentinelX server.")
  }
  if (!response.ok) {
    let message = "Something went wrong. Please try again."
    try {
      const data = await response.json()
      if (typeof data?.detail === "string") message = data.detail
      else if (data?.detail?.message) message = data.detail.message
    } catch {
      // no body
    }
    throw new ApiErrorLike(message)
  }
  return response.json() as Promise<T>
}

/** The latest analysis for one alert or incident. `analysis: null` is
 * a NORMAL state (AI off, over budget, or still generating). */
export function apiGetAiAnalysis(
  targetType: "alert" | "incident",
  targetId: string,
): Promise<{ analysis: AiAnalysisView | null }> {
  return request(`/ai/${targetType === "alert" ? "alerts" : "incidents"}/${targetId}/analysis`)
}

export function apiRegenerateAiAnalysis(
  targetType: "alert" | "incident",
  targetId: string,
): Promise<{ analysis: AiAnalysisView | null }> {
  return request(`/ai/${targetType === "alert" ? "alerts" : "incidents"}/${targetId}/regenerate`, {
    method: "POST",
  })
}

export function apiDecideAiAnalysis(
  analysisId: string,
  payload: { decision: "accepted" | "edited" | "rejected"; reason?: string; edits?: Record<string, unknown> },
): Promise<{ analysis: AiAnalysisView }> {
  return request(`/ai-analyses/${analysisId}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function apiAiMetrics(organizationId?: string) {
  const qs = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ""
  return request<{
    organization_id: string | null
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
    cost: { total_spend_usd: number }
  }>(`/ai/metrics${qs}`)
}
