# API Contract: Organizations, Access Control, Invitations

This documents the endpoints added/changed for the organization
management, SOC-mode, invitations and layered access-control feature.
It does not re-document the pre-existing auth endpoints
(`/auth/register`, `/verify-email`, `/login`, `/forgot-password`,
`/reset-password`) beyond what changed on them below -- see
`docs/architecture.md` for the overall backend layout.

Every business-rule/permission rejection anywhere in this feature
raises `HTTPException` with a **structured detail**:

```json
{ "detail": { "code": "stable_snake_case_code", "message": "Human-readable string." } }
```

The frontend should switch on `detail.code`, never parse `detail.message`.
A handful of pre-existing auth endpoints (`register`, `verify-email`,
`login`'s non-organization failures, `resend-verification`,
`forgot-password`, `reset-password`) still raise a bare string
`detail` -- those predate this convention and were left alone. `login`'s
two new organization-status failures (`organization_suspended`,
`organization_archived`) do use the structured shape; see below.

## Auth changes

### `POST /api/v1/auth/register`

Self-signup is now **organization-owner-only** -- there is no role
picker and no "join an existing organization" path.

```json
{ "name": "...", "email": "...", "password": "...", "organization_name": "...", "industry": "optional" }
```

`organization_name` is required for every email except the hardcoded
`SUPER_ADMIN_EMAILS` allow-list (which gets no organization at all).
Creates a `pending_registrations` row only; the real `admins` row and
its brand-new **pending** organization are created in `verify-email`,
once the OTP is confirmed.

### `POST /api/v1/auth/login`

Unchanged shape. Newly rejects with `401` and a structured code when
the account's own organization is `suspended` or `archived`:

```json
{ "detail": { "code": "organization_suspended", "message": "Your organization has been suspended." } }
{ "detail": { "code": "organization_archived", "message": "Your organization has been archived." } }
```

A **pending** organization's owner is allowed to log in (the frontend
needs a session to render the "awaiting approval" screen).

### `GET /api/v1/auth/me`

Response gained two fields, both `null` for `super_admin` /
`platform_soc_analyst` (neither is scoped to a single organization):

```json
{
  "...": "...",
  "organization": { "id": "...", "name": "...", "status": "pending|active|suspended|archived", "soc_mode": "managed|in_house" } | null,
  "effective_modules": { "assets": "read|write", "...": "..." } | null
}
```

Deliberately does **not** require an active organization -- this is
one of the two endpoints (with the owner's `GET /organization`) that
must keep working regardless of status, so the frontend has something
to read in order to show the right pending/suspended/archived screen.

## Platform admin: `/api/v1/admin/organizations` (super_admin-only)

| Method & path | Notes |
|---|---|
| `GET /` | `q`, `status`, `soc_mode`, `sort` (`created_at_desc\|created_at_asc\|name_asc\|name_desc`), `page`, `page_size`. Returns `{total, page, page_size, organizations: [...]}`. |
| `GET /{organization_id}` | Full detail: counts, `modules`, `assigned_soc_analysts`, `recent_activity` (last 20). |
| `POST /` | `{name, owner_email, soc_mode, industry?, max_members?}`. Creates an **active** organization, seeds every module enabled, and sends an `owner`-kind invitation to `owner_email` (the org has no owner account until that invitation is accepted). |
| `PATCH /{organization_id}` | `{name?, industry?, max_members?}`. |
| `POST /{organization_id}/approve` | `pending -> active` only. |
| `POST /{organization_id}/suspend` | `{reason}` (required, non-empty). `active\|pending -> suspended`. |
| `POST /{organization_id}/reactivate` | `suspended -> active` only. |
| `POST /{organization_id}/archive` | `active\|pending\|suspended -> archived`. Terminal -- nothing transitions out of `archived`. |
| `PUT /{organization_id}/modules` | `{modules: {<all 9 keys>: bool}}` -- the payload must name **every** module key, no more, no fewer. Returns `{modules, changed}`. |
| `PUT /{organization_id}/soc-mode` | `{soc_mode}`. Returns `{organization, soc_analyst_count, message?, warning?}` -- `message` when switching to `managed` strands existing `soc_analyst` members' soc/incidents access; `warning` when switching to `in_house` with zero `soc_analyst` members yet. |
| `GET /{organization_id}/members` | Owner(s) + `users` rows, flattened into one list with `account_type`. |
| `POST /{organization_id}/members/{account_type}/{account_id}/deactivate` | `account_type` is `admin\|user`. Refuses (`409 last_owner_protected`) to deactivate an organization's last active owner. |
| `GET /{organization_id}/activity` | Paginated `audit_logs` for the organization. |

An invalid status transition is `409 invalid_status_transition`;
an unknown organization id is `404 organization_not_found` everywhere
in this router.

## Platform admin: `/api/v1/admin/soc-analysts` (super_admin-only except `GET /me`)

| Method & path | Notes |
|---|---|
| `POST /` | `{email}`. Sends a `platform_soc`-kind invitation (no organization). `409 email_already_registered` if the email already has an account. |
| `GET /` | Every `platform_soc_analyst` admin, each with `assigned_organizations`. |
| `GET /me` | **platform_soc_analyst-only** (not super_admin). `{assigned_organizations}` for the calling analyst -- added so the SOC Team page's "your assigned organizations" placeholder has a real endpoint to read, since `GET /` above is super_admin-only. |
| `PATCH /{admin_id}` | `{is_active}`. |
| `PUT /{admin_id}/organizations` | `{organization_ids: [uuid, ...]}`. Replaces the full assignment set. Every id must currently be `soc_mode=managed` and not `archived`, or the whole request is rejected with `400 invalid_organization_assignment` (naming the offending ids) -- no partial application. |

## Organization owner: `/api/v1/organization` (organization_admin-only, own organization only)

Every endpoint below except `GET /` (the overview) also requires the
organization to be `active` -- a `pending`/`suspended`/`archived`
organization gets `403` with code `organization_pending` /
`organization_suspended` / `organization_archived` from
`require_active_organization`.

| Method & path | Notes |
|---|---|
| `GET /` | The one exception above. Returns a minimal `{id, name, status, soc_mode, message}` while `pending`; full counts + `recent_activity` (last 10) once approved. |
| `GET /members` | This organization's `users` rows. |
| `PATCH /members/{user_id}` | `{role?, is_active?, team_id?}`. Setting `role=soc_analyst` while `soc_mode != in_house` is `422 soc_analyst_requires_in_house`. |
| `DELETE /members/{user_id}` | Hard-deletes if nothing (`audit_logs`, `tickets.assigned_user_id`, `escalations`) references the user; otherwise soft-deactivates instead. Response says which: `{deleted, deactivated}`. |
| `POST /invitations` | `{email, role, team_id?}`. `409 email_already_registered` / `409 invitation_already_pending` / `422 soc_analyst_requires_in_house` / `409 member_limit_reached` (against `organizations.max_members`) / `429 invitation_rate_limited` (20/org/hour). |
| `GET /invitations` | This organization's invitations, any status. |
| `POST /invitations/{id}/resend` | Only a `pending` invitation; rotates the token/expiry on the same row (the old link stops working). |
| `DELETE /invitations/{id}` | Only a `pending` invitation; sets `status=revoked`. |
| `GET /teams`, `POST /teams`, `PATCH /teams/{id}`, `DELETE /teams/{id}` | Standard CRUD. Deleting a team sets its members' `team_id` to `NULL` (`ON DELETE SET NULL`), it does not remove them. |
| `PUT /teams/{id}/members` | `{user_ids: [...]}`. Replaces the team's membership set (via `users.team_id` -- see `docs/DECISIONS.md` on why this is single-team, not many-to-many). |
| `GET /access` | The full role x module matrix: `{platform_enabled, role_has_default, owner_enabled, soc_gated, effective}` per `(role, module)` cell. |
| `PUT /access` | `{updates: [{role, module_key, enabled}, ...]}`. Rejects a module that isn't a default for that role (`422 module_not_default_for_role`) or that the platform has disabled for this organization (`422 module_disabled_by_platform`). |
| `PUT /members/{user_id}/access` | `{denied_modules: [module_key, ...]}`. Replaces that member's full override set to exactly the given list (an omitted previously-denied key is un-denied). |

## Public: `/api/v1/invitations` (no authentication)

| Method & path | Notes |
|---|---|
| `GET /{token}` | Validates a token. `404 invitation_not_found` for unknown, expired, *and* revoked alike -- never distinguished, so a stale link reveals nothing. Reading an expired-but-still-`pending` row flips its status to `expired` as a side effect. Returns `{kind, organization_name, role, email, expires_at}`. |
| `POST /accept` | `{token, full_name, password}`. Creates the account the invitation names (`owner` -> `admins`/`organization_admin`; `platform_soc` -> `admins`/`platform_soc_analyst`, no organization; `member` -> `users`/the invited role), marks the invitation `accepted` (single-use), and returns a normal login-shaped `{access_token, token_type, user}` so the invitee is immediately signed in. `409 email_already_registered` if the email became a registered account after the invite was sent. |

## Module keys

The 9 keys used throughout `organization_modules` /
`organization_role_access` / `user_access_overrides` /
`GET /organization/access`'s matrix (`app/modules.py`):

```
assets, soc, incidents, it_tickets, approvals, ai_agents, device_agents, reports, audit_logs
```

## Error code reference (structured-detail endpoints only)

| Code | Status | Where |
|---|---|---|
| `organization_pending` / `organization_suspended` / `organization_archived` | 403 (401 at login) | `require_active_organization`; `login` (401 only) |
| `super_admin_required` / `platform_admin_required` / `platform_soc_required` / `org_owner_required` | 403 | `app/access.py` role guards |
| `organization_not_found` | 404 | most `/admin/organizations`, `/organization`, `require_module` |
| `invalid_status` / `invalid_soc_mode` / `invalid_status_transition` | 400 / 400 / 409 | `admin_organizations.py` |
| `suspension_reason_required` | 400 | `admin_organizations.py` suspend |
| `unknown_module_key` / `incomplete_module_list` | 400 | `admin_organizations.py` modules PUT, `organization.py` member access PUT |
| `invalid_account_type` / `member_not_found` / `last_owner_protected` | 400 / 404 / 409 | `admin_organizations.py` deactivate-member |
| `soc_analyst_not_found` / `invalid_organization_assignment` | 404 / 400 | `admin_soc.py` |
| `email_already_registered` | 409 | org create, soc invite, member invite, invitation accept |
| `invitation_already_pending` / `invitation_not_found` / `invitation_not_pending` / `invitation_rate_limited` | 409 / 404 / 409 / 429 | `organization.py` invitations, `invitations.py` |
| `soc_analyst_requires_in_house` | 422 | `organization.py` member role patch/invite |
| `member_limit_reached` | 409 | `organization.py` invite |
| `team_not_found` | 404 | `organization.py` teams/members |
| `invalid_role` | 400 | `organization.py` `_validate_role` |
| `module_not_default_for_role` / `module_disabled_by_platform` | 422 | `organization.py` access matrix PUT |
| `module_not_available` | 403 | `require_module` |
