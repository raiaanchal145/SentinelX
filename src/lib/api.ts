import { API_BASE } from "./apiBase"

export type OrganizationSummary = {
  id: string
  name: string
  status: "active" | "suspended" | "archived"
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
    // fetch() itself failed (backend down, wrong port, CORS, offline --
    // there was no HTTP response at all). This has to be an ApiError,
    // not a plain Error: every call site across the app does
    // `err instanceof ApiError ? err.message : "<generic fallback>"`,
    // so a plain Error here used to get silently replaced by whatever
    // generic string that call site had, hiding the one message that
    // actually explains what's wrong. Status 0 is a safe sentinel --
    // real HTTP responses are always 200-599, and nothing in the app
    // branches on ApiError.status or .code === "network_error".
    throw new ApiError(
      "Could not reach the SentinelX server. Make sure the backend is running (uvicorn) on port 8000.",
      0,
      "network_error",
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

// ---------------------------------------------------------------------
// Platform admin: organizations (super_admin-only). See
// docs/API_CONTRACT.md ("Platform admin: /api/v1/admin/organizations").
// ---------------------------------------------------------------------

export type OrganizationRow = {
  id: string
  name: string
  industry: string | null
  status: "active" | "suspended" | "archived"
  soc_mode: "managed" | "in_house"
  max_members: number | null
  created_via: string | null
  created_at: string | null
  owner: { name: string; email: string } | null
  members: number
  pending_invitations: number
  assets: number
  open_incidents: number
  open_tickets: number
  last_activity_at: string | null
}

export type OrganizationListResponse = {
  total: number
  page: number
  page_size: number
  organizations: OrganizationRow[]
}

export type OrganizationListParams = {
  q?: string
  status?: string
  soc_mode?: string
  sort?: string
  page?: number
  page_size?: number
}

export function apiListOrganizations(params: OrganizationListParams = {}) {
  const query = new URLSearchParams()
  if (params.q) query.set("q", params.q)
  if (params.status) query.set("status", params.status)
  if (params.soc_mode) query.set("soc_mode", params.soc_mode)
  if (params.sort) query.set("sort", params.sort)
  if (params.page) query.set("page", String(params.page))
  if (params.page_size) query.set("page_size", String(params.page_size))
  const qs = query.toString()
  return request<OrganizationListResponse>(`/admin/organizations${qs ? `?${qs}` : ""}`)
}

export type OrganizationCreatePayload = {
  name: string
  owner_email: string
  soc_mode: "managed" | "in_house"
  industry?: string
  max_members?: number
}

export function apiCreateOrganization(payload: OrganizationCreatePayload) {
  return request<OrganizationRow>("/admin/organizations", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}



export function apiSuspendOrganization(organizationId: string, reason: string) {
  return request<OrganizationRow>(`/admin/organizations/${organizationId}/suspend`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  })
}

export function apiReactivateOrganization(organizationId: string) {
  return request<OrganizationRow>(`/admin/organizations/${organizationId}/reactivate`, { method: "POST" })
}

export function apiArchiveOrganization(organizationId: string) {
  return request<OrganizationRow>(`/admin/organizations/${organizationId}/archive`, { method: "POST" })
}

export type AuditEntry = {
  id: string
  action: string
  actor_type: string
  actor_id: string | null
  target_type: string | null
  target_id: string | null
  created_at: string | null
  details: Record<string, unknown> | null
}

export type OrganizationMember = {
  account_type: "admin" | "user"
  id: string
  name: string
  email: string
  role: string
  is_active: boolean
  last_login_at: string | null
}

export type OrganizationDetail = OrganizationRow & {
  modules: Record<string, boolean>
  assigned_soc_analysts: { id: string; name: string; email: string }[]
  recent_activity: AuditEntry[]
}

export function apiGetOrganizationDetail(organizationId: string) {
  return request<OrganizationDetail>(`/admin/organizations/${organizationId}`)
}

export function apiPatchOrganization(
  organizationId: string,
  payload: { name?: string; industry?: string; max_members?: number },
) {
  return request<OrganizationRow>(`/admin/organizations/${organizationId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  })
}

export function apiGetOrganizationMembers(organizationId: string) {
  return request<{ members: OrganizationMember[] }>(`/admin/organizations/${organizationId}/members`)
}

export function apiDeactivateOrganizationMember(
  organizationId: string,
  accountType: "admin" | "user",
  accountId: string,
) {
  return request<{ id: string; is_active: boolean }>(
    `/admin/organizations/${organizationId}/members/${accountType}/${accountId}/deactivate`,
    { method: "POST" },
  )
}

export function apiUpdateOrganizationModules(organizationId: string, modules: Record<string, boolean>) {
  return request<{ modules: Record<string, boolean>; changed: Record<string, boolean> }>(
    `/admin/organizations/${organizationId}/modules`,
    { method: "PUT", body: JSON.stringify({ modules }) },
  )
}

export function apiUpdateOrganizationSocMode(organizationId: string, socMode: "managed" | "in_house") {
  return request<{
    organization: OrganizationRow
    soc_analyst_count: number
    message?: string
    warning?: string
  }>(`/admin/organizations/${organizationId}/soc-mode`, {
    method: "PUT",
    body: JSON.stringify({ soc_mode: socMode }),
  })
}

export function apiGetOrganizationActivity(organizationId: string, page = 1, pageSize = 25) {
  return request<{ total: number; page: number; page_size: number; entries: AuditEntry[] }>(
    `/admin/organizations/${organizationId}/activity?page=${page}&page_size=${pageSize}`,
  )
}

// The organization's owner invitation(s) as the platform admin sees them
// -- "has the owner accepted yet?", with resend/revoke for a stale one.
// Member invitations are the owner's business, not the platform's.
export type OwnerInvitationRow = {
  id: string
  email: string
  kind: string
  status: "pending" | "accepted" | "expired" | "revoked"
  expired: boolean
  created_at: string | null
  expires_at: string | null
  accepted_at: string | null
}

export function apiListOwnerInvitationsForOrg(organizationId: string) {
  return request<{ invitations: OwnerInvitationRow[] }>(
    `/admin/organizations/${organizationId}/invitations`,
  )
}

export function apiResendOwnerInvitation(organizationId: string, invitationId: string) {
  return request<{ id: string; status: string; expires_at: string }>(
    `/admin/organizations/${organizationId}/invitations/${invitationId}/resend`,
    { method: "POST" },
  )
}

export function apiRevokeOwnerInvitation(organizationId: string, invitationId: string) {
  return request<{ id: string; status: string }>(
    `/admin/organizations/${organizationId}/invitations/${invitationId}`,
    { method: "DELETE" },
  )
}

// ---------------------------------------------------------------------
// Platform admin: platform SOC team (super_admin-only). See
// docs/API_CONTRACT.md ("Platform admin: /api/v1/admin/soc-analysts").
// ---------------------------------------------------------------------

export type SocAnalystAssignedOrg = {
  id: string
  name: string
  status: "active" | "suspended" | "archived"
  soc_mode: "managed" | "in_house"
}

export type SocAnalyst = {
  id: string
  name: string
  email: string
  is_active: boolean
  last_login_at: string | null
  assigned_organizations: SocAnalystAssignedOrg[]
}

export function apiListSocAnalysts() {
  return request<{ soc_analysts: SocAnalyst[] }>("/admin/soc-analysts")
}

export function apiInviteSocAnalyst(email: string) {
  return request<{ id: string; email: string; status: string }>("/admin/soc-analysts", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export function apiPatchSocAnalyst(adminId: string, isActive: boolean) {
  return request<{ id: string; is_active: boolean }>(`/admin/soc-analysts/${adminId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  })
}

export function apiUpdateSocAnalystOrganizations(adminId: string, organizationIds: string[]) {
  return request<{ id: string; assigned_organizations: SocAnalystAssignedOrg[] }>(
    `/admin/soc-analysts/${adminId}/organizations`,
    { method: "PUT", body: JSON.stringify({ organization_ids: organizationIds }) },
  )
}

/** Self-service equivalent for the calling platform_soc_analyst -- see
 * docs/API_CONTRACT.md ("GET /me"). GET /admin/soc-analysts above is
 * super_admin-only, so this is what the SOC Team member's own "SOC
 * queue" page reads to show their assigned organizations. */
export function apiGetMyAssignedOrganizations() {
  return request<{ assigned_organizations: SocAnalystAssignedOrg[] }>("/admin/soc-analysts/me")
}

// ---------------------------------------------------------------------
// Organization owner (organization_admin-only, own organization only).
// See docs/API_CONTRACT.md ("Organization owner: /api/v1/organization").
// Every endpoint below except apiGetOrganizationOverview() 403s with a
// structured organization_pending/organization_suspended/
// organization_archived code unless the organization is active.
// ---------------------------------------------------------------------

export type OrganizationOverview = {
  id: string
  name: string
  status: "active" | "suspended" | "archived"
  soc_mode: "managed" | "in_house"
  // Only present while pending (see backend get_overview()).
  message?: string
  // Only present once active.
  industry?: string | null
  max_members?: number | null
  members?: number
  pending_invitations?: number
  assets?: number
  open_incidents?: number
  open_tickets?: number
  last_activity_at?: string | null
  recent_activity?: { id: string; action: string; created_at: string | null }[]
}

export function apiGetOrganizationOverview() {
  return request<OrganizationOverview>("/organization")
}

export type OwnerMember = {
  id: string
  name: string
  email: string
  role: string
  team_id: string | null
  is_active: boolean
  last_login_at: string | null
}

export function apiGetOwnerMembers() {
  return request<{ members: OwnerMember[] }>("/organization/members")
}

export function apiPatchOwnerMember(
  userId: string,
  payload: { role?: string; is_active?: boolean; team_id?: string },
) {
  return request<{ id: string; role: string; is_active: boolean; team_id: string | null }>(
    `/organization/members/${userId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  )
}

export function apiRemoveOwnerMember(userId: string) {
  return request<{ id: string; deleted: boolean; deactivated: boolean }>(`/organization/members/${userId}`, {
    method: "DELETE",
  })
}

export type OwnerInvitation = {
  id: string
  email: string
  kind: string
  role: string | null
  status: string
  created_at: string | null
  expires_at: string | null
}

export function apiCreateMemberInvitation(email: string, role: string, teamId?: string) {
  return request<{ id: string; email: string; role: string; status: string; expires_at: string }>(
    "/organization/invitations",
    { method: "POST", body: JSON.stringify({ email, role, team_id: teamId }) },
  )
}

export function apiListOwnerInvitations() {
  return request<{ invitations: OwnerInvitation[] }>("/organization/invitations")
}

export function apiResendInvitation(invitationId: string) {
  return request<{ id: string; status: string; expires_at: string }>(
    `/organization/invitations/${invitationId}/resend`,
    { method: "POST" },
  )
}

export function apiRevokeInvitation(invitationId: string) {
  return request<{ id: string; status: string }>(`/organization/invitations/${invitationId}`, {
    method: "DELETE",
  })
}

export type Team = {
  id: string
  name: string
  description: string | null
  member_count: number
}

export function apiListTeams() {
  return request<{ teams: Team[] }>("/organization/teams")
}

export function apiCreateTeam(name: string, description?: string) {
  return request<Team>("/organization/teams", {
    method: "POST",
    body: JSON.stringify({ name, description: description || undefined }),
  })
}

export function apiPatchTeam(teamId: string, payload: { name?: string; description?: string }) {
  return request<Team>(`/organization/teams/${teamId}`, { method: "PATCH", body: JSON.stringify(payload) })
}

export function apiDeleteTeam(teamId: string) {
  return request<{ id: string; deleted: boolean }>(`/organization/teams/${teamId}`, { method: "DELETE" })
}

export function apiSetTeamMembers(teamId: string, userIds: string[]) {
  return request<{ id: string; member_ids: string[] }>(`/organization/teams/${teamId}/members`, {
    method: "PUT",
    body: JSON.stringify({ user_ids: userIds }),
  })
}

export type AccessCell = {
  platform_enabled: boolean
  role_has_default: boolean
  owner_enabled: boolean
  soc_gated: boolean
  effective: boolean
}

export type AccessMatrixResponse = {
  organization: { soc_mode: "managed" | "in_house" }
  matrix: Record<string, Record<string, AccessCell>>
}

export function apiGetAccessMatrix() {
  return request<AccessMatrixResponse>("/organization/access")
}

export function apiUpdateAccessMatrix(updates: { role: string; module_key: string; enabled: boolean }[]) {
  return request<{ updates: { role: string; module_key: string; enabled: boolean }[] }>("/organization/access", {
    method: "PUT",
    body: JSON.stringify({ updates }),
  })
}

export type MemberAccessCell = AccessCell & { denied: boolean }

export type MemberAccessResponse = {
  user_id: string
  role: string
  modules: Record<string, MemberAccessCell>
}

export function apiGetMemberAccess(userId: string) {
  return request<MemberAccessResponse>(`/organization/members/${userId}/access`)
}

export function apiUpdateMemberAccess(userId: string, deniedModules: string[]) {
  return request<{ id: string; denied_modules: string[] }>(`/organization/members/${userId}/access`, {
    method: "PUT",
    body: JSON.stringify({ denied_modules: deniedModules }),
  })
}

// ---------------------------------------------------------------------
// Assets -- the first real, non-mock pipeline data (see
// docs/API_CONTRACT.md "Assets"). Same endpoints serve every role via
// the shared AssetsPage: organization-level callers hit /assets, a
// platform SOC analyst passes ?organization_id=, and super_admin reads
// through the nested /admin/organizations/{id}/assets view.
// ---------------------------------------------------------------------

export type AssetCriticality = "critical" | "high" | "medium" | "low"

export type AssetRow = {
  id: string
  name: string
  hostname: string | null
  ip_address: string | null
  asset_type: string
  criticality: AssetCriticality
  operating_system: string | null
  environment: string | null
  description: string | null
  owner_user_id: string | null
  owner_name: string | null
  team_id: string | null
  team_name: string | null
  status: "active" | "retired"
  last_seen_at: string | null
  created_at: string | null
  tags: string[]
  /** Per-row write permission the backend computes for the caller
   * (it_developer is scoped to assets they own or that belong to their
   * team; everyone with module write gets true; read-only roles false). */
  can_edit: boolean
}

export type AssetListResponse = {
  total: number
  page: number
  page_size: number
  assets: AssetRow[]
}

export type AssetListParams = {
  organization_id?: string
  q?: string
  asset_type?: string
  criticality?: string
  status?: string
  tag?: string
  owner_user_id?: string
  team_id?: string
  sort?: string
  page?: number
  page_size?: number
}

function assetQuery(params: AssetListParams): string {
  const query = new URLSearchParams()
  if (params.organization_id) query.set("organization_id", params.organization_id)
  if (params.q) query.set("q", params.q)
  if (params.asset_type) query.set("asset_type", params.asset_type)
  if (params.criticality) query.set("criticality", params.criticality)
  if (params.status) query.set("status", params.status)
  if (params.tag) query.set("tag", params.tag)
  if (params.owner_user_id) query.set("owner_user_id", params.owner_user_id)
  if (params.team_id) query.set("team_id", params.team_id)
  if (params.sort) query.set("sort", params.sort)
  if (params.page) query.set("page", String(params.page))
  if (params.page_size) query.set("page_size", String(params.page_size))
  const qs = query.toString()
  return qs ? `?${qs}` : ""
}

export function apiListAssets(params: AssetListParams = {}) {
  return request<AssetListResponse>(`/assets${assetQuery(params)}`)
}

export type AssetsSummary = {
  by_type: Record<string, number>
  by_criticality: Record<string, number>
  by_status: Record<string, number>
}

export function apiGetAssetsSummary(organizationId?: string) {
  const query = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ""
  return request<AssetsSummary>(`/assets/summary${query}`)
}

export type AssetsLookup = {
  users: { id: string; name: string }[]
  teams: { id: string; name: string }[]
}

export function apiGetAssetsLookup(organizationId?: string) {
  const query = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ""
  return request<AssetsLookup>(`/assets/lookup${query}`)
}

export type AssetPayload = {
  name: string
  asset_type: string
  hostname?: string | null
  ip_address?: string | null
  operating_system?: string | null
  environment?: string | null
  criticality?: string
  owner_user_id?: string | null
  team_id?: string | null
  description?: string | null
  tags?: string[]
}

export function apiCreateAsset(payload: AssetPayload) {
  return request<AssetRow>("/assets", { method: "POST", body: JSON.stringify(payload) })
}

export function apiGetAsset(assetId: string, organizationId?: string) {
  const query = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ""
  return request<AssetRow>(`/assets/${assetId}${query}`)
}

export function apiUpdateAsset(assetId: string, payload: Partial<AssetPayload> & { status?: string }) {
  return request<AssetRow>(`/assets/${assetId}`, { method: "PATCH", body: JSON.stringify(payload) })
}

export function apiRetireAsset(assetId: string) {
  return request<AssetRow>(`/assets/${assetId}`, { method: "DELETE" })
}

export function apiSetAssetTags(assetId: string, tags: string[]) {
  return request<AssetRow>(`/assets/${assetId}/tags`, { method: "PUT", body: JSON.stringify({ tags }) })
}

/** super_admin-only read view of one organization's assets (the write
 * endpoints reject platform accounts) -- used by the organization
 * detail page's Assets tab. */
export function apiListOrganizationAssets(organizationId: string, params: Omit<AssetListParams, "organization_id"> = {}) {
  return request<AssetListResponse>(`/admin/organizations/${organizationId}/assets${assetQuery(params)}`)
}

// ---------------------------------------------------------------------------
// Event sources + their ingestion API keys (routers/event_sources.py).
// The full key is returned EXACTLY ONCE by apiCreateEventSourceKey --
// the list endpoints only ever see prefix/created/last-used/revoked.
// ---------------------------------------------------------------------------

export type EventSourceRow = {
  id: string
  name: string
  source_type: string
  asset_id: string | null
  enabled: boolean
  status: string
  last_event_at: string | null
  created_at: string | null
  can_manage: boolean
}

export type EventSourceKeyRow = {
  id: string
  prefix: string
  created_at: string | null
  last_used_at: string | null
  revoked: boolean
  revoked_at: string | null
  /** Only present on the create-key response. */
  key?: string
}

export function apiListEventSources() {
  return request<{ event_sources: EventSourceRow[] }>("/event-sources")
}

export function apiCreateEventSource(payload: { name: string; source_type: string; asset_id?: string | null; enabled?: boolean }) {
  return request<EventSourceRow>("/event-sources", { method: "POST", body: JSON.stringify(payload) })
}

export function apiUpdateEventSource(sourceId: string, payload: { name?: string; asset_id?: string | null; enabled?: boolean }) {
  return request<EventSourceRow>(`/event-sources/${sourceId}`, { method: "PATCH", body: JSON.stringify(payload) })
}

export function apiDisableEventSource(sourceId: string) {
  return request<EventSourceRow>(`/event-sources/${sourceId}`, { method: "DELETE" })
}

export function apiCreateEventSourceKey(sourceId: string) {
  return request<EventSourceKeyRow>(`/event-sources/${sourceId}/keys`, { method: "POST" })
}

export function apiListEventSourceKeys(sourceId: string) {
  return request<{ keys: EventSourceKeyRow[]}>(`/event-sources/${sourceId}/keys`)
}

export function apiRevokeEventSourceKey(sourceId: string, keyId: string) {
  return request<EventSourceKeyRow>(`/event-sources/${sourceId}/keys/${keyId}`, { method: "DELETE" })
}

// ---------------------------------------------------------------------------
// Alerts -- the SOC queue (docs/API_CONTRACT.md "Alerts"). List/detail
// are module `soc` READ; acknowledge/assign/dismiss/reopen are the four
// write actions with the backend's transition map and per-queue
// visibility deciding who may write (a managed org's own accounts get
// 403 alert_write_not_allowed). Visibility itself is entirely
// server-side: the frontend just renders what comes back.
// ---------------------------------------------------------------------------

export type AlertStatus = "new" | "triaged" | "investigating" | "dismissed" | "converted"
export type AlertSeverity = "critical" | "high" | "medium" | "low" | "info"
export type AlertKind = "detection" | "correlation"

export type AlertRow = {
  id: string
  organization_id: string
  kind: AlertKind
  rule_id: string | null
  rule_name: string | null
  asset_id: string | null
  severity: AlertSeverity
  status: AlertStatus
  title: string
  summary: string
  group_key: string | null
  username: string | null
  source_ip: string | null
  event_count: number
  first_seen_at: string | null
  last_seen_at: string | null
  dismissed_reason: string | null
  assigned_account_type: string | null
  assigned_account_id: string | null
  correlation_id: string | null
  created_at: string | null
}

export type AlertListParams = {
  status?: AlertStatus
  severity?: AlertSeverity
  rule_id?: string
  asset_id?: string
  assigned_to_me?: boolean
  time_from?: string
  time_to?: string
  /** Platform roles scoping the queue to one organization; an id the
   * caller cannot see is a 404 from the backend. */
  organization_id?: string
  limit?: number
  cursor?: string | null
}

export type AlertListResponse = {
  alerts: AlertRow[]
  next_cursor: string | null
}

export type AlertHistoryEntry = {
  action: string
  actor_type: string
  actor_id: string | null
  status_from: string | null
  status_to: string | null
  detail: Record<string, unknown> | null
  created_at: string | null
}

export type AlertSupportingEvent = {
  id: string
  event_type: string
  username: string | null
  source_ip: string | null
  occurred_at: string | null
  message: string | null
}

export type AlertCorrelation = {
  id: string
  title: string
  severity: AlertSeverity
  reasoning: string
  first_seen_at: string | null
  last_seen_at: string | null
  event_count: number
  grouped_alerts: AlertRow[]
}

export type AlertRule = {
  id: string
  name: string
  description: string | null
  severity: AlertSeverity
  mitre_technique: string | null
}

export type AlertDetail = {
  alert: AlertRow
  rule: AlertRule | null
  events: AlertSupportingEvent[]
  correlation: AlertCorrelation | null
  history: AlertHistoryEntry[]
}

function alertQuery(params: AlertListParams): string {
  const query = new URLSearchParams()
  if (params.status) query.set("status", params.status)
  if (params.severity) query.set("severity", params.severity)
  if (params.rule_id) query.set("rule_id", params.rule_id)
  if (params.asset_id) query.set("asset_id", params.asset_id)
  if (params.assigned_to_me) query.set("assigned_to_me", "true")
  if (params.time_from) query.set("time_from", params.time_from)
  if (params.time_to) query.set("time_to", params.time_to)
  if (params.organization_id) query.set("organization_id", params.organization_id)
  if (params.limit) query.set("limit", String(params.limit))
  if (params.cursor) query.set("cursor", params.cursor)
  const qs = query.toString()
  return qs ? `?${qs}` : ""
}

export function apiListAlerts(params: AlertListParams = {}) {
  return request<AlertListResponse>(`/alerts${alertQuery(params)}`)
}

export function apiGetAlert(alertId: string) {
  return request<AlertDetail>(`/alerts/${alertId}`)
}

export function apiAcknowledgeAlert(alertId: string) {
  return request<{ id: string; status: AlertStatus; previous_status: AlertStatus }>(
    `/alerts/${alertId}/acknowledge`,
    { method: "POST" },
  )
}

export function apiAssignAlert(
  alertId: string,
  payload: { account_type: "admin" | "user"; account_id: string },
) {
  return request<{
    id: string
    assigned_account_type: string
    assigned_account_id: string
    previous_assigned_account_id: string | null
  }>(`/alerts/${alertId}/assign`, { method: "POST", body: JSON.stringify(payload) })
}

export function apiDismissAlert(alertId: string, reason: string) {
  return request<{ id: string; status: AlertStatus; dismissed_reason: string; previous_status: AlertStatus }>(
    `/alerts/${alertId}/dismiss`,
    { method: "POST", body: JSON.stringify({ reason }) },
  )
}

export function apiReopenAlert(alertId: string) {
  return request<{ id: string; status: AlertStatus; previous_status: AlertStatus }>(
    `/alerts/${alertId}/reopen`,
    { method: "POST" },
  )
}

// ---------------------------------------------------------------------------
// Events -- the read side of the ingestion pipeline (docs/API_CONTRACT.md
// "Event ingestion and read API"). Cursor pagination is keyset on
// (occurred_at DESC, id DESC); visibility (super_admin vs platform SOC
// vs own organization) is decided by the backend.
// ---------------------------------------------------------------------------

export type EventRow = {
  id: string
  organization_id: string
  event_source_id: string
  asset_id: string | null
  occurred_at: string | null
  ingested_at: string | null
  event_type: string
  severity: string
  username: string | null
  source_ip: string | null
  normalized_data: Record<string, unknown> | null
  /** Only present on the detail endpoint. */
  raw_data?: Record<string, unknown> | unknown[] | string | null
}

export type EventListParams = {
  time_from?: string
  time_to?: string
  source_id?: string
  event_type?: string
  severity?: string
  asset_id?: string
  user?: string
  ip?: string
  q?: string
  /** Optional organization scope (super_admin / platform SOC UIs).
   * An invisible or unknown id is a 404 from the backend. */
  organization_id?: string
  limit?: number
  cursor?: string | null
}

export type EventListResponse = {
  events: EventRow[]
  next_cursor: string | null
}

export type EventSummary = {
  total: number
  buckets: number
  bucket_hours: number
  timeline: number[]
  by_severity: Record<string, number>
  by_type: Record<string, number>
}

function eventQuery(params: EventListParams): string {
  const query = new URLSearchParams()
  if (params.time_from) query.set("time_from", params.time_from)
  if (params.time_to) query.set("time_to", params.time_to)
  if (params.source_id) query.set("source_id", params.source_id)
  if (params.event_type) query.set("event_type", params.event_type)
  if (params.severity) query.set("severity", params.severity)
  if (params.asset_id) query.set("asset_id", params.asset_id)
  if (params.user) query.set("user", params.user)
  if (params.ip) query.set("ip", params.ip)
  if (params.q) query.set("q", params.q)
  if (params.organization_id) query.set("organization_id", params.organization_id)
  if (params.limit) query.set("limit", String(params.limit))
  if (params.cursor) query.set("cursor", params.cursor)
  const qs = query.toString()
  return qs ? `?${qs}` : ""
}

export function apiListEvents(params: EventListParams = {}) {
  return request<EventListResponse>(`/events${eventQuery(params)}`)
}

export function apiGetEvent(eventId: string) {
  return request<EventRow>(`/events/${eventId}`)
}

export function apiGetEventsSummary(params: Omit<EventListParams, "limit" | "cursor"> & { buckets?: number; bucket_hours?: number } = {}) {
  const { buckets, bucket_hours, ...rest } = params
  const query = new URLSearchParams(eventQuery(rest).replace(/^\?/, ""))
  if (buckets) query.set("buckets", String(buckets))
  if (bucket_hours) query.set("bucket_hours", String(bucket_hours))
  const qs = query.toString()
  return request<EventSummary>(`/events/summary${qs ? `?${qs}` : ""}`)
}
