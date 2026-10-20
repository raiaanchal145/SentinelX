import { API_BASE } from "./apiBase"

export type ApprovalRiskLevel = "read_only" | "low" | "high"
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired"
export type ActorType = "user" | "admin" | "ai_agent" | "system"

export type ApprovalView = {
  id: string
  organization_id: string
  action_type: string
  tool?: string | null
  arguments?: Record<string, unknown> | null
  incident_id?: string | null
  risk_level: ApprovalRiskLevel
  status: ApprovalStatus
  requested_by_type: ActorType
  requested_by_id?: string | null
  requested_reason?: string | null
  decision_reason?: string | null
  reviewed_by_user_id?: string | null
  reviewed_at?: string | null
  expires_at?: string | null
  executed_at?: string | null
  created_at?: string | null
}

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
  }
}

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
    throw new ApiError("Could not reach the SentinelX server.", 0)
  }

  if (!response.ok) {
    let message = "Request failed."
    let code: string | undefined
    try {
      const data = await response.json()
      if (typeof data?.detail === "object" && data.detail !== null) {
        message = data.detail.message || message
        code = data.detail.code
      } else if (typeof data?.detail === "string") {
        message = data.detail
      }
    } catch {
      // response wasn't JSON
    }
    throw new ApiError(message, response.status, code)
  }

  return response.json()
}

export function apiListApprovals(view: "pending" | "mine" | "history" = "pending"): Promise<{ approvals: ApprovalView[] }> {
  return request(`/approvals?view=${view}`)
}

export function apiGetApproval(id: string): Promise<ApprovalView> {
  return request(`/approvals/${id}`)
}

export function apiApproveApproval(id: string, reason?: string): Promise<ApprovalView> {
  return request(`/approvals/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ reason: reason || null }),
  })
}

export function apiRejectApproval(id: string, reason: string): Promise<ApprovalView> {
  return request(`/approvals/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  })
}

export type ActionOutcome = {
  decision: "allow" | "needs_approval" | "deny"
  reason?: string
  approval_id?: string
  executed?: boolean
  result?: Record<string, unknown>
}

export function apiTriggerIncidentAction(
  incidentId: string,
  payload: { tool: string; arguments?: Record<string, unknown>; reason?: string; as_ai_agent?: boolean },
): Promise<ActionOutcome> {
  return request(`/incidents/${incidentId}/actions`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}
