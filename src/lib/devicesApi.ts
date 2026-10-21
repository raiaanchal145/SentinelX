import { API_BASE } from "./apiBase"

export type DeviceStatus = "connected" | "stale" | "offline" | "revoked" | "pending_consent" | "expired"

export type ConsentCategory = {
  key: string
  label: string
  description: string
  event_types: string[]
  prohibited: string
}

export type DeviceRow = {
  id: string
  asset_id: string
  asset_name: string
  asset_type: string
  hostname: string | null
  ip_address: string | null
  status: DeviceStatus
  raw_status: string
  device_name: string | null
  operating_system: string | null
  agent_version: string | null
  last_seen_at: string | null
  last_heartbeat_at: string | null
  categories_granted: string[]
  created_at: string | null
}

export type ConsentRecordView = {
  id: string
  account_type: string
  account_id: string
  categories: string[]
  version: string
  ip: string | null
  consented_at: string
  revoked_at: string | null
  revocation_reason: string | null
}

export type DeviceDetail = {
  id: string
  organization_id: string
  asset: {
    id: string
    name: string
    hostname: string | null
    ip_address: string | null
    asset_type: string
    criticality: string
    operating_system: string | null
  }
  status: DeviceStatus
  raw_status: string
  device_name: string | null
  operating_system: string | null
  agent_version: string | null
  last_seen_at: string | null
  last_heartbeat_at: string | null
  enrolled_at: string | null
  active_consent: {
    id: string
    categories: string[]
    version: string
    consented_at: string
  } | null
  consent_history: ConsentRecordView[]
}

export type DevicesSummary = {
  connected: number
  stale: number
  offline: number
  revoked: number
  pending_consent: number
  total: number
}

export type TokenPreview = {
  token_prefix: string
  status: string
  expires_at: string
  organization_name: string
  asset: {
    id: string
    name: string
    asset_type: string
    operating_system: string | null
  }
  consent_version: string
  categories: ConsentCategory[]
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
      // non-json response
    }
    throw new ApiError(message, response.status, code)
  }

  return response.json()
}

export function apiListDevices(organizationId?: string): Promise<{ devices: DeviceRow[] }> {
  const q = organizationId ? `?organization_id=${organizationId}` : ""
  return request(`/devices${q}`)
}

export function apiGetDevicesSummary(organizationId?: string): Promise<DevicesSummary> {
  const q = organizationId ? `?organization_id=${organizationId}` : ""
  return request(`/devices/summary${q}`)
}

export function apiGetDeviceDetail(id: string): Promise<DeviceDetail> {
  return request(`/devices/${id}`)
}

export function apiCreateEnrollmentToken(payload: {
  asset_id: string
  device_name?: string
  operating_system?: string
}): Promise<{
  id: string
  token: string
  token_prefix: string
  expires_at: string
  asset_id: string
  asset_name: string
  enrollment_url: string
}> {
  return request("/devices/enrollment-tokens", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function apiPreviewEnrollmentToken(token: string): Promise<TokenPreview> {
  return request(`/devices/enrollment-tokens/${token}/preview`)
}

export function apiSubmitTokenConsent(
  token: string,
  categories: string[],
  version = "v1.0",
): Promise<{
  status: string
  consent_id: string
  asset_id: string
  categories_granted: string[]
  message: string
}> {
  return request(`/devices/enrollment-tokens/${token}/consent`, {
    method: "POST",
    body: JSON.stringify({ categories, consent_text_version: version }),
  })
}

export function apiUpdateDeviceConsent(
  id: string,
  categories: string[],
  version = "v1.0",
): Promise<{
  status: string
  consent_id: string
  categories_granted: string[]
}> {
  return request(`/devices/${id}/consent`, {
    method: "POST",
    body: JSON.stringify({ categories, consent_text_version: version }),
  })
}

export function apiRevokeDevice(id: string, reason: string): Promise<{ status: string; device_id: string }> {
  return request(`/devices/${id}/revoke`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  })
}

export function apiGetConsentCategories(): Promise<{ version: string; categories: ConsentCategory[] }> {
  return request("/devices/consent-categories")
}
