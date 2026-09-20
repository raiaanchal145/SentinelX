const API_BASE = "http://localhost:8000/api/v1"

export type ApiUser = {
  id: string
  name: string
  email: string
  role: string
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

    try {
      const data = await response.json()
      if (data?.detail) {
        message = data.detail
      }
    } catch {
      // response had no JSON body -- keep the default message
    }

    throw new Error(message)
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
  role: string,
) {
  return request<RegisterResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password, role }),
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
