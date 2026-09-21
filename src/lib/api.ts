const API_BASE = "http://localhost:8000/api/v1"

export type OrganizationSummary = {
  id: string
  name: string
  status: "pending" | "active" | "suspended" | "archived"
  soc_mode: "managed" | "in_house"
}

export type ModuleAccessLevel = "read" | "write"

export type ApiUser = {
  id: string
  name: string
  email: string
  role: string
  // "admin" (super_admin/organization_admin/platform_soc_analyst) or
  // "user" (soc_analyst, security_manager, it_developer, auditor) --
  // see backend UserOut.
  account_type: string
  // Both null for super_admin/platform_soc_analyst, who aren't scoped
  // to a single organization. See docs/API_CONTRACT.md.
  organization?: OrganizationSummary | null
  effective_modules?: Record<string, ModuleAccessLevel> | null
}

/**
 * Thrown for any non-OK response. Every new organization-management
 * endpoint (see docs/API_CONTRACT.md) raises a structured
 * `{code, message}` detail rather than a bare string -- `code` is
 * stable and meant for the frontend to switch on (e.g. to redirect, or
 * to disable a specific control), `message` is already a human-readable
 * string straight from the backend and safe to show as-is. A handful of
 * older auth endpoints still raise a bare string `detail`; those come
 * through here with `code` left undefined.
 */
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

type LoginResponse = {
  access_token: string
  token_type: string
  user: ApiUser
}

type RegisterResponse = {
  email: string
  message: string
}

type MessageResponse = {
  message: string
}

type StatsOverview = {
  users: number
  assets: number
  organizations: number
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
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
    throw new Error(
      "Could not reach the SentinelX server. Make sure the backend is running (uvicorn) on port 8000.",
    )
  }

  if (!response.ok) {
    let message = "Something went wrong. Please try again."
    let code: string | undefined

    try {
      const data = await response.json()
      if (typeof data?.detail === "string") {
        message = data.detail
      } else if (data?.detail && typeof data.detail === "object") {
        message = data.detail.message ?? message
        code = data.detail.code
      }
    } catch {
      // response had no JSON body -- keep the default message
    }

    throw new ApiError(message, response.status, code)
  }

  return response.json() as Promise<T>
}

export function apiLogin(email: string, password: string) {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  })
}

export function apiRegister(
  name: string,
  email: string,
  password: string,
  organizationName: string,
  industry?: string,
) {
  return request<RegisterResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      name,
      email,
      password,
      organization_name: organizationName,
      industry: industry || null,
    }),
  })
}

export function apiVerifyEmail(email: string, code: string) {
  return request<ApiUser>("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  })
}

export function apiResendVerification(email: string) {
  return request<MessageResponse>("/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export function apiForgotPassword(email: string) {
  return request<MessageResponse>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export function apiResetPassword(
  email: string,
  code: string,
  newPassword: string,
) {
  return request<MessageResponse>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ email, code, new_password: newPassword }),
  })
}

export function apiGetStatsOverview() {
  return request<StatsOverview>("/stats/overview")
}

export function apiGetMe() {
  return request<ApiUser>("/auth/me")
}

export type InvitationKind = "owner" | "platform_soc" | "member"

export type InvitationDetail = {
  kind: InvitationKind
  // null for a platform_soc invitation -- it isn't scoped to an organization.
  organization_name: string | null
  role: string
  email: string
  expires_at: string
}

export function apiGetInvitation(token: string) {
  return request<InvitationDetail>(`/invitations/${encodeURIComponent(token)}`)
}

export function apiAcceptInvitation(token: string, fullName: string, password: string) {
  return request<LoginResponse>("/invitations/accept", {
    method: "POST",
    body: JSON.stringify({ token, full_name: fullName, password }),
  })
}
