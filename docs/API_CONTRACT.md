# API Contract: Organizations, Access Control, Invitations, Assets

This documents the endpoints added/changed for the organization
management, SOC-mode, invitations, layered access-control and asset
inventory features.
It does not re-document the pre-existing auth endpoints
(`/verify-email`, `/login`, `/forgot-password`, `/reset-password`)
beyond what changed on them below -- see
`docs/architecture.md` for the overall backend layout.

**SentinelX is invite-only** (docs/DECISIONS.md): there is no public
registration. `POST /auth/register` and the `pending_registrations`
flow were removed; accounts are created only by accepting an
invitation, or by the one-time `python -m app.create_super_admin`
bootstrap command. The complete anonymous surface is exactly:

```
POST /api/v1/auth/login
POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
POST /api/v1/auth/verify-email
POST /api/v1/auth/resend-verification
GET  /api/v1/invitations/{token}
POST /api/v1/invitations/accept
GET  /api/v1/health
```

`backend/tests/test_anonymous_routes.py` enumerates the app's routes
and fails the suite if any other anonymous endpoint appears.

Every business-rule/permission rejection anywhere in this feature
raises `HTTPException` with a **structured detail**:

```json
{ "detail": { "code": "stable_snake_case_code", "message": "Human-readable string." } }
```

The frontend should switch on `detail.code`, never parse `detail.message`.
A handful of pre-existing auth endpoints (`verify-email`,
`login`'s non-organization failures, `resend-verification`,
`forgot-password`, `reset-password`) still raise a bare string
`detail` -- those predate this convention and were left alone. `login`'s
two organization-status failures (`organization_suspended`,
`organization_archived`) do use the structured shape; see below.

## Auth changes

### `POST /api/v1/auth/register` -- REMOVED

The self-signup endpoint, its schemas, the `PendingRegistration` model
and the `pending_registrations` table are gone (migration
`d5e6f7a8b9c0` drops the table; unexpired registration codes in it were
discarded by design -- no flow can ever consume them). Unauthenticated
requests now get `404`.

### `POST /api/v1/auth/verify-email` and `POST /api/v1/auth/resend-verification` -- lockout only

These now serve exactly one flow: the **3-wrong-passwords lockout**.
After the third wrong password, `login` resets
`failed_login_attempts`, flips `is_verified` to `False`, and emails a
10-minute, single-use code; the account (admin or user) must verify
with that code before it can log in again. `resend-verification`
emails a fresh code to a locked account (throttled per email). Neither
endpoint creates anything anymore.

Both answer unknown emails, verified accounts, missing codes and wrong
codes with the **same generic response** (`400` on verify, the same
200 body on resend) so nothing on the anonymous surface reveals
whether an address has an account. Verify attempts are capped per
email (5 per 10-minute window). Codes are single-use and expire in 10
minutes -- `backend/tests/test_auth.py` pins all of it.

### `POST /api/v1/auth/login`

Unchanged shape. Newly rejects with `401` and a structured code when
the account's own organization is `suspended` or `archived`:

```json
{ "detail": { "code": "organization_suspended", "message": "Your organization has been suspended." } }
{ "detail": { "code": "organization_archived", "message": "Your organization has been archived." } }
```

Organization status rules at login: a **suspended** or **archived**
organization's members are refused outright (`401` with the structured
codes below) -- a suspended org's owner cannot even log in. There is
no pending state anymore; organizations are born active.

### `GET /api/v1/auth/me`

Response gained two fields, both `null` for `super_admin` /
`platform_soc_analyst` (neither is scoped to a single organization):

```json
{
  "...": "...",
  "organization": { "id": "...", "name": "...", "status": "active|suspended|archived", "soc_mode": "managed|in_house" } | null,
  "effective_modules": { "assets": "read|write", "...": "..." } | null
}
```

Deliberately does **not** require an active organization -- this is
one of the two endpoints (with the owner's `GET /organization`) that
must keep working regardless of status, so the frontend has something
to read in order to show the right suspended/archived screen.

## Platform admin: `/api/v1/admin/organizations` (super_admin-only)

| Method & path | Notes |
|---|---|
| `GET /` | `q`, `status`, `soc_mode`, `sort` (`created_at_desc\|created_at_asc\|name_asc\|name_desc`), `page`, `page_size`. Returns `{total, page, page_size, organizations: [...]}`. |
| `GET /{organization_id}` | Full detail: counts, `modules`, `assigned_soc_analysts`, `recent_activity` (last 20). |
| `POST /` | `{name, owner_email, soc_mode, industry?, max_members?}`. Creates an **active** organization, seeds every module enabled, and sends an `owner`-kind invitation to `owner_email` (the org has no owner account until that invitation is accepted). `409 email_already_registered` if the email already has an account. |
| `PATCH /{organization_id}` | `{name?, industry?, max_members?}`. |
| `GET /{organization_id}/invitations` | The organization's `owner`-kind invitations, any status -- the platform's "has the owner accepted yet?" view. Each row: `{id, email, kind, status, expired, created_at, expires_at, accepted_at}` (`expired: true` when still pending past `expires_at`). |
| `POST /{organization_id}/invitations/{invitation_id}/resend` | Rotates the pending owner invitation's token/expiry on the same row (the old link stops working) and re-sends the email. `409 invitation_not_pending` for an accepted/revoked row. |
| `DELETE /{organization_id}/invitations/{invitation_id}` | Revokes a pending owner invitation (`status=revoked`); the link then 404s. |
| `POST /{organization_id}/suspend` | `{reason}` (required, non-empty). `active -> suspended`. |
| `POST /{organization_id}/reactivate` | `suspended -> active` only. |
| `POST /{organization_id}/archive` | `active\|suspended -> archived`. Terminal -- nothing transitions out of `archived`. |
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
organization to be `active` -- a `suspended`/`archived`
organization gets `403` with code `organization_suspended` /
`organization_archived` from
`require_active_organization`.

| Method & path | Notes |
|---|---|
| `GET /` | The one exception above. Always returns the full payload -- counts + `recent_activity` (last 10) -- for the caller's own organization, whatever its status. |
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
| `GET /members/{user_id}/access` | Per-module `{role_has_default, platform_enabled, owner_enabled, soc_gated, denied, effective}` for this one member, layering their individual `UserAccessOverride` rows on top of the role-level picture `GET /access` returns. Added for the owner's per-member access drawer (Prompt B section B4), which needs to read a member's current state before showing the live effective preview -- there was previously no read endpoint, only the PUT below. |
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

## Assets: `/api/v1/assets`

The first real (non-mock) pipeline data: events, alerts, incidents and
tickets all point at an asset, so the inventory exists first. Router:
`app/routers/assets.py`.

| Method & path | Who | Notes |
|---|---|---|
| `GET /` | module `assets` read+ | `organization_id` (platform SOC only), `q` (name/hostname/IP), `asset_type`, `criticality`, `status` (`active\|retired`), `tag`, `owner_user_id`, `team_id`, `sort` (`created_at_desc\|created_at_asc\|name_asc\|name_desc`), `page`, `page_size` (max 100). Returns `{total, page, page_size, assets: [...]}`. Each row carries `can_edit` -- the caller's per-row write permission (it_developer: own or team's assets only; owner/manager: always; read roles: never). |
| `POST /` | module `assets` write | See create payload below. Returns 201 with the row. |
| `GET /{asset_id}` | module `assets` read+ | 404 `asset_not_found` for another organization's id (existence is never leaked). |
| `PATCH /{asset_id}` | module `assets` write + row | Omitted fields stay untouched; an explicitly-sent `null` **clears** the field (unassign owner/team, blank a hostname). `name` can't be blanked. |
| `DELETE /{asset_id}` | module `assets` write + row | **Soft delete only**: sets `status=retired`. There is no hard-delete path at all -- nothing later can orphan an `asset_id` (see docs/DECISIONS.md). 409 `asset_already_retired` on a second retire. |
| `PUT /{asset_id}/tags` | module `assets` write + row | Replaces the full tag set. Deduped, trimmed, empty strings dropped. |
| `GET /summary` | module `assets` read+ | `{by_type, by_criticality, by_status}` counts. |
| `GET /lookup` | module `assets` read+ | `{users, teams}` for the create/edit form's pickers (GET /organization/members and /teams are owner-only, so a manager/developer filling in this form needs this). Active users and all teams of the target organization. |

A platform_soc_analyst reaches all `GET`s read-only by passing
`?organization_id=` -- checked against `soc_visible_organization_ids()`
(assigned + `managed` + `active`); an unassigned or unknown id is 404
`organization_not_found`, and a missing id is 400
`organization_id_required`. super_admin does not use this router at all
(403 `platform_admin_not_supported`); they read through the endpoint
below instead.

### Asset row shape

```json
{
  "id": "uuid", "name": "...", "hostname": null, "ip_address": null,
  "asset_type": "server", "criticality": "medium",
  "operating_system": null, "environment": null, "description": null,
  "owner_user_id": null, "owner_name": null,
  "team_id": null, "team_name": null,
  "status": "active", "last_seen_at": null, "created_at": "...",
  "tags": [], "can_edit": true
}
```

Create payload: `name` (required), `asset_type` (required), `hostname`,
`ip_address` (validated), `operating_system`, `environment`
(`production|staging|development`), `criticality` (default `medium`),
`owner_user_id`, `team_id`, `description`, `tags`. All the optional
strings are nullable -- an `application`/`cloud_resource` asset need not
have a hostname.

Every mutating action writes an audit entry (`asset.create`,
`asset.update`, `asset.status_change`, `asset.retire`,
`asset.tags_change`) with a before/after summary under `details`.

## Platform admin: `GET /api/v1/admin/organizations/{id}/assets`

super_admin-only read view of one organization's assets -- same list
filters, sort and row shape as `GET /assets` above, with `can_edit`
always `false`. Write endpoints reject platform accounts everywhere
(`403 platform_admin_not_supported`), matching how every other
admin-side view of one organization's data is read-only.

## Asset error code reference

| Code | Status | Where |
|---|---|---|
| `asset_not_found` | 404 | get/patch/delete/tags, incl. another organization's id |
| `duplicate_hostname` | 409 | create/patch -- same (organization, lower(hostname)) as another asset; hostname is optional, uniqueness applies only when set |
| `invalid_asset_type` / `invalid_criticality` / `invalid_environment` / `invalid_status` / `invalid_ip_address` | 400 | field validation on create/patch and list filters |
| `name_required` | 400 | create/patch with a blank name |
| `owner_not_found` / `team_not_found` | 404 | owner_user_id/team_id not in this organization |
| `asset_not_editable` | 403 | caller has module write but not row-level write on this asset |
| `asset_already_retired` | 409 | double retire |
| `organization_id_required` | 400 | platform SOC analyst GET without organization_id |
| `platform_admin_not_supported` | 403 | super_admin on /assets/*, or any platform account on a write endpoint |

## Event sources: `/api/v1/event-sources`

Registered event sources (a linux auth collector, an application, docker,
a network probe, a custom JSON feed) and their ingestion API keys.
`app/routers/event_sources.py`.

Access: **organization_admin (owner) and security_manager only** for
all write endpoints and key management (docs/DECISIONS.md -- minting
keys is security administration, not `assets`-write); soc_analyst and
auditor get the read-only list; platform accounts are rejected (403
`platform_admin_not_supported`) -- a per-organization read view belongs
on an admin-side endpoint in a later milestone.

| Endpoint | Who | Notes |
|---|---|---|
| `GET /` | any active-org account | `{event_sources: [...]}`, newest first; each row: `id, name, source_type, asset_id, enabled, status, last_event_at, created_at, can_manage` |
| `POST /` | owner / security_manager | `{name, source_type, asset_id?, enabled?=true, config?}`; 201, audit `event_source.create` |
| `GET /{id}` | any active-org account | one row; another org's id is 404 |
| `PATCH /{id}` | owner / security_manager | partial; `enabled: false` audits `event_source.disable` |
| `DELETE /{id}` | owner / security_manager | soft-disable only (history keeps the source); audit `event_source.disable` |
| `POST /{id}/keys` | owner / security_manager | 201 with the FULL key **exactly once**; only `key_hash` (SHA-256) + short `prefix` are stored; audit `api_key.create` stores the prefix, never the key |
| `GET /{id}/keys` | owner / security_manager | `prefix`, `created_at`, `last_used_at`, `revoked`, `revoked_at` -- never the key or its hash |
| `DELETE /{id}/keys/{key_id}` | owner / security_manager | revoke (not delete); collectors using it fail immediately; audit `api_key.revoke` |

**Ingestion authentication** (used by the P07 ingestion endpoints):
`Authorization: Bearer sx_<prefix>_<secret>` resolved by the reusable
dependency `get_event_source_from_api_key` -- constant-time hash
compare, `last_used_at` updated, per-key `rate_limit_for_key` hook (stub
until P07), revoked key -> 401 `invalid_api_key`, disabled source -> 403
`event_source_disabled`. Key format: 32+ random bytes, shown once.

### Event source error codes

| Code | Status | Where |
|---|---|---|
| `event_source_not_found` | 404 | get/patch/delete/keys, incl. another organization's id |
| `event_source_already_disabled` | 409 | double disable |
| `event_source_disabled` | 403 | valid key whose source is disabled |
| `invalid_api_key` | 401 | missing/garbled/unknown/revoked key -- one identical response for every failure shape |
| `api_key_not_found` / `api_key_already_revoked` | 404 / 409 | revoke |
| `invalid_source_type` / `name_required` / `asset_not_found` | 400 | field validation |
| `event_sources_write_required` | 403 | authenticated org account without the owner/security_manager role |
| `platform_admin_not_supported` | 403 | platform accounts on this router |

## Event ingestion and read API: `/api/v1/events`

The event pipeline: a collector POSTs raw records; the API validates
them cheaply and enqueues; the Arq worker normalizes, deduplicates,
enriches and stores (`security_events`); the SOC-side read API serves
them back. Router: `app/routers/events.py`; shared validation logic
(`app/event_ingestion.py`); worker job (`app/worker/event_jobs.py`);
parsers (`app/worker/parsers.py`). List-query performance is measured
against 100k rows in `docs/reports/event-ingestion.md`.

### `POST /api/v1/events` (ingestion -- API key, no user login)

Auth: `Authorization: Bearer sx_<prefix>_<secret>` (P06's
`get_event_source_from_api_key` -- constant-time hash compare, updates
`last_used_at`). One key = one event source = one organization. An
`organization_id` in the payload is never read: the organization always
decides from the key.

Body: one event object, a list of event objects, or `{"events": [...]}`.
Limits (settings-configurable): at most 500 events per batch and at
most 1 MiB per request (checked before parsing; `413`). A fixed-window
per-key rate limit in Redis defaults to **600 events/minute**
(`events_rate_limit_per_minute`); the request itself costs one slot at
auth time and the endpoint tops up the remaining `accepted - 1`, so a
batch of N costs exactly N (`429 rate_limited` when exhausted). Redis
being down degrades the limit to "no limit" rather than failing
ingestion.

Response: `202` with `{"status", "accepted", "rejected", "results":
[{"index", "status": "accepted"|"rejected", "reason"?}, ...]}` -- per-item
reasons for every rejected record. Nothing heavy happens inline:
accepted records are handed to the worker via `enqueue_work
("process_events", ...)`; if Redis is unreachable the response is still
202 with an `X-Ingestion-Warning: queued=false` header telling the
collector to re-send the batch.

Request-level errors: `413 request_too_large` / `413 batch_too_large`,
`400 invalid_json`, `400 invalid_batch`, `400 empty_batch`, `401
invalid_api_key`, `403 event_source_disabled`, `429 rate_limited`.

### The versioned event schema (`schema_version` "1.0")

Every record is validated against this schema (`app/event_ingestion.py
::validate_event_record`):

| Field | Required | Rules |
|---|---|---|
| `schema_version` | no | Defaults to "1.0". Bumped when the schema changes; the worker keeps honoring versions it knows. |
| `timestamp` | yes | ISO-8601 (naive = UTC). Rejected when more than **24 hours in the future** or **older than 30 days** (per-item reason). |
| `source_type` | yes | One of `linux_auth`, `application`, `docker`, `network`, `windows`, `custom_json`, `test` (the `EventSourceType` enum; `windows` is for the endpoint agent arriving in P21). |
| `event_type` | yes | **Fixed vocabulary** below. Anything else is rejected at the API with a per-item reason. |
| `message` | yes | Non-empty string; the human-readable event text. |
| `host` / `asset` | no | Strings; host/asset identifier used for asset enrichment by hostname/IP match. |
| `user` | no | String; the acting/target user. |
| `ip` | no | String; the source IP. |
| `process` | no | String; the producing process/service. |
| `severity_hint` | no | One of `critical\|high\|medium\|low\|info`. Wins over the severity defaults. |
| `raw` | no | The verbatim original record (string or JSON object), kept for the parsers and stored size-capped in `raw_data`. |

### The fixed `event_type` vocabulary

39 values, grouped by the source types that produce them
(`app/event_ingestion.py::EVENT_TYPE_VOCABULARY` is the authoritative
list -- keep that dict and this table in sync):

- **linux_auth:** `auth_success`, `auth_failure`, `sudo_command`,
  `user_add`, `user_delete`, `group_change`, `package_install`
- **application:** `app_error`, `app_warning`, `app_login`,
  `app_login_failed`, `config_change`, `permission_change`,
  `api_request`, `api_error`
- **docker:** `container_start`, `container_stop`, `container_kill`,
  `container_create`, `container_destroy`, `image_pull`, `image_push`,
  `docker_daemon_event`
- **network:** `firewall_allow`, `firewall_deny`, `port_scan`,
  `ids_alert`, `connection_allowed`, `connection_blocked`, `dns_query`,
  `dns_response`
- **windows (P21 agent):** `logon_success`, `logon_failure`,
  `process_create`, `service_install`, `account_created`,
  `account_disabled`, `account_lockout`, `log_cleared`,
  `policy_change`, `scheduled_task`
- **custom_json / test / fallback:** `custom`, `test_event`, `other`

### Normalization (the worker)

The `process_events` job parses each record with its source-type parser
into the normalized schema and stores `raw_data` (size-capped at
64 KB) and `normalized_data` (schema_version, types, message,
host/user/ip/process, asset context, parser-extracted fields). Merge
rules: the collector's explicit fields win over parser guesses; a
parser-recognized raw record re-classifies the event type (raw content
is ground truth); a recognized verb with no vocabulary mapping stores
`event_type: "other"` with the raw record kept verbatim; an
unparseable record keeps the declared type. Severity: `severity_hint`
> the event-type default (e.g. `log_cleared` critical, `port_scan`
high, `auth_failure` medium) > `info`.

**Dedup:** `dedup_hash` = SHA-256 over (organization, source,
second-truncated timestamp, event_type, host, user, ip, message),
uniquely indexed per organization
(`uq_security_events_org_dedup_hash`); the worker inserts with
`ON CONFLICT DO NOTHING`, so replaying an identical batch adds zero
rows. The organization id in the hash means two organizations can
never collide on identical content.

**Enrichment:** the event's asset context (asset id, criticality,
owner) is resolved by exact case-insensitive hostname match first,
then IP, against the organization's active assets; matched, it fills
`asset_id` and the `normalized_data.asset` object.

### `GET /api/v1/events` (read -- user token, module `soc` read)

Filters: `time_from`, `time_to` (ISO-8601), `source_id`, `event_type`
(vocabulary), `severity`, `asset_id`, `user` (partial match), `ip`,
`q` (free text over type/user/ip and the JSONB payloads), and
`organization_id` (optional; super_admin / platform SOC scoping the UI
to one organization -- an id the caller cannot see, or one that doesn't
exist, is `404 organization_not_found` so a guessed id reveals
nothing). Pagination: cursor (keyset on `occurred_at DESC, id DESC`;
`limit` 1-200, default 50), response `{"events": [...],
"next_cursor"}`. Detail `GET /api/v1/events/{id}` adds `raw_data`. A
different organization's event id is `404 event_not_found` (existence
never leaked).

### `GET /api/v1/events/summary` (aggregates for the SOC Overview tile)

Same auth, visibility and filters as the list endpoint (including
`organization_id`). One indexed aggregate over the window ending now:
`{"total", "buckets", "bucket_hours", "timeline": [count per bucket,
oldest first], "by_severity": {...}, "by_type": {...}}`. `buckets`
(1-48, default 12) and `bucket_hours` (1-720, default 2) size the
timeline. A platform SOC analyst with zero assigned organizations gets
all zeros. Defined before `/{event_id}` so `summary` is never read as
an event id.

Visibility (the access matrix; `app/access.py
::soc_visible_organization_ids` plus the owner's oversight rule):

| Caller | Sees |
|---|---|
| `super_admin` | every organization. |
| `platform_soc_analyst` | assigned + `managed` + `active` organizations only; zero assigned -> an empty list. |
| In-house organization's accounts with module `soc` read | their own organization. |
| **Managed** organization's owner | read-only oversight of their organization's events (`soc: read` under managed mode). |
| Managed organization's own members (non-owner) | `403 module_not_available` -- platform SOC staff work managed orgs. |
| Organization with the `soc` module disabled | `403 module_not_available`. |

### Event error codes

| Code | Status | Where |
|---|---|---|
| `request_too_large` / `batch_too_large` | 413 | body > 1 MiB / batch > 500 events |
| `invalid_json` / `invalid_batch` / `empty_batch` | 400 | body shape |
| `invalid_api_key` / `event_source_disabled` | 401 / 403 | key auth (P06 semantics) |
| `rate_limited` | 429 | per-key fixed window exhausted |
| `invalid_time_range` / `invalid_event_type` / `invalid_severity` / `invalid_cursor` | 400 | read-API filter validation |
| `event_not_found` | 404 | detail, incl. another organization's id |
| `soc_not_visible` | 403 | caller with no events visibility at all |

## Detection rules: `/api/v1/detection`

The deterministic rule engine running in the worker over normalized
events (P23). Rules are DATA: every rule's `condition` is a JSON
definition validated by Pydantic (`app/detection/definitions.py`), and
only the three evaluator functions are code. Router:
`app/routers/detection.py`; engine: `app/detection/`.

### Rule types and their definitions

| Type | Definition fields | Fires when |
|---|---|---|
| `threshold` | `event_types` (1+), `threshold` (2..10000), `window_seconds` (60..86400), `group_by` (`user\|ip\|host`, default `user`) | any group reaches `threshold` matching events inside the window |
| `sequence` | `steps` (2..5, each `{event_type, fields?}`), `window_seconds`, `group_by` | the steps occur IN ORDER within the window for the same group key |
| `pattern` | `match` (1+ conditions, AND), `exclude` (0+ conditions, the allowlist/blocklist) | an event matches all `match` conditions and none of `exclude` |

A condition is `{field, op, value}` with `op` one of `eq`, `contains`,
`starts_with`, `ends_with`, `regex`; `field` names a normalized column
(`event_type`, `user`, `ip`, `host`, `process`, ...) or digs one level
into the payloads with `raw.<key>` / `normalized.<key>`. Events missing
the `group_by` value are skipped for that rule (never folded into one
shared None group). Windows are LEFT-EDGE INCLUSIVE; out-of-order
arrival never matters (evaluators sort by time).

### Built-in rules (8, seeded idempotently at worker startup)

`organization_id` is NULL on these rows; the partial unique index on
`name WHERE organization_id IS NULL` makes the seed's
`ON CONFLICT DO UPDATE` safe -- re-seeding refreshes
definition/description/severity but never touches per-organization
enable/disable. All 8 carry a MITRE ATT&CK technique id and a one-line
"why it matters":

| Stable id | Name | Type | Severity | MITRE |
|---|---|---|---|---|
| `repeated-failed-logins` | Repeated failed logins | threshold: 20 failures / 10 min / per user | high | T1110 |
| `success-after-failures` | Successful login after many failures | sequence: failure -> success / 15 min / per user | critical | T1110 |
| `privileged-group-change` | Privileged group membership change | pattern: group_change/process_create naming sudo, wheel, Domain Admins; `svc.*` excluded | high | T1098 |
| `new-local-user` | New local user created | pattern: `user_add` or `account_created` | medium | T1136 |
| `service-installed` | Service installed | pattern: `service_install` (7045) | high | T1543.003 |
| `audit-log-cleared` | Audit log cleared | pattern: `log_cleared` (1102) | critical | T1070.001 |
| `suspicious-process-path` | Suspicious process from a user-writable path | pattern: `process_create` from Temp/Downloads/AppData; msedge.exe excluded | high | T1059 |
| `admin-login-new-ip` | Admin login from a new IP | sequence: app_login -> sudo_command / 30 min / per IP | high | T1078 |

### `GET /api/v1/detection/rules` (module `soc` read)

Built-in rules + this organization's own (custom creation arrives in
P24), sorted by name, each row:

```json
{
  "id": "uuid", "name": "...", "description": "...",
  "rule_type": "threshold|sequence|pattern", "condition": {...},
  "severity": "critical|high|medium|low|info",
  "mitre_technique": "T1110", "builtin": true,
  "default_enabled": true, "enabled": true,
  "organization_id": null, "created_at": "..."
}
```

`default_enabled` is the rule row's own flag; `enabled` is the
EFFECTIVE state (the organization's `organization_rule_settings`
override when present, else the default). Platform accounts get `403
platform_admin_not_supported`.

### `PATCH /api/v1/detection/rules/{id}/enabled`

Body `{"enabled": bool}`. The organization owner
(organization_admin) or a security_manager only -- the event-sources
guard pattern (toggling detections is security administration, not
soc-write). Never touches the shared rule row: the choice is written
to `organization_rule_settings` (one row per explicit override,
survives re-seeding) and audited as `detection_rule.enable` /
`detection_rule.disable`. Unknown or another organization's rule id is
`404 detection_rule_not_found`.

### Rule hits (worker output, P10's input)

Every newly stored event batch is evaluated inline at the end of
`process_events` against the organization's enabled rules; a match
writes a `rule_hits` row -- `{rule, organization, rule_name, severity,
group_key ("user=alice" / "ip=1.2.3.4" / "event=<id>"), event_ids,
event_count, window_start, window_end}`. Chosen over a queue message:
hits need queryable history (see docs/DECISIONS.md). Sliding-window
state lives in Redis sorted sets keyed by
`detection:window:{org}:{rule}:{group_by}:{group_value}` -- the
organization id in the key makes cross-organization isolation
structural; Redis down degrades to in-memory windows (a detection may
be delayed, never fabricated). A disabled rule never fires, and a
replayed batch (already-deduplicated events) evaluates nothing new.

### Detection error code reference

| Code | Status | Where |
|---|---|---|
| `detection_rule_not_found` | 404 | PATCH enabled, incl. another organization's id |
| `detection_rules_write_required` | 403 | PATCH enabled by a non-owner/non-security_manager |
| `platform_admin_not_supported` | 403 | platform accounts on both endpoints |

## Alerts: `/api/v1/alerts`

P10: rule hits become deduplicated alerts, related alerts are
correlated, and everything is routed by the organization's soc mode.
Pipeline: `app/alerting.py` (worker-side, INLINE at the end of
`process_events`, the same transaction as the hit writes -- a failure
rolls back hits and alerts together and the next batch retries);
API: `app/routers/alerts.py`.

### Dedup (hit -> alert)

One alert per (organization, rule, group key, time bucket). The bucket
is the hit's `window_end` floored to the rule's
`dedup_window_seconds` (default 900 = 15 minutes, per-rule column).
Repeated hits inside the window FOLD into the existing alert:
`event_count` grows, `first_seen_at`/`last_seen_at` extend,
`alert_events` gains links (capped at 50 stored links per alert -- the
true count lives in `event_count`). A hit in a fresh bucket creates a
new alert. The fold is race-safe via the partial unique index on
`(organization_id, dedup_key) WHERE dedup_key IS NOT NULL`; the dedup
key is `{rule_name}:{group_key}:{bucket}`. Correlation keys
(username/source_ip/asset_id) are resolved from the supporting events'
normalized view -- a pattern hit's group key names ONE event, so the
"same user/ip/asset" matching needs the resolved values.

### Correlation (exactly one built-in rule)

The `correlation_rules` row "Brute force followed by privileged
activity" (built-in, `organization_id` NULL, seeded idempotently at
worker startup like the detection rules -- `correlation_rules` carries
the same partial unique name index): repeated failed logins + a
successful login + a privileged group action for the SAME user within
30 minutes => ONE high-severity correlated alert ALONGSIDE the three
underlying ones (they stay visible in the queue -- docs/DECISIONS.md),
a `correlations` row with the human-readable reasoning ("why these
were grouped"), and `correlation_alerts` links to the grouped alerts.
Grouping key: the username every candidate alert shares (resolved from
the supporting events' normalized view); the source IP is only a
fallback signature when no username resolved -- assets correlate only
through the user acting on them. Correlation dedup key
`corr:{rule}:{user}=<name>:{bucket}` -- re-running the same attack
window never stacks a second correlation.

### Routing matrix (who sees / works which queue)

| Caller | Sees | Writes |
|---|---|---|
| super_admin | everything | yes |
| platform_soc_analyst assigned to the org (managed+active) | that org's queue | yes |
| platform_soc_analyst, unassigned | empty queue (200) | -- (404 on any id) |
| owner, soc_mode=managed | own org, read-only | 403 `alert_write_not_allowed` |
| security_manager, soc_mode=managed | own org, read-only | 403 `alert_write_not_allowed` |
| soc_analyst, soc_mode=managed | nothing (403) | -- |
| auditor / it_developer | nothing (403) | -- |
| owner / security_manager, soc_mode=in_house | own org | yes |
| soc_analyst, soc_mode=in_house | own org | yes |

A managed organization's alerts are worked by platform SOC staff only;
its own owner/security_manager keep read oversight. Existence never
leaks: an invisible or cross-organization id is 404.

### `GET /api/v1/alerts` (module `soc` read)

Query: `status`, `severity`, `rule_id`, `asset_id`, `assigned_to_me`,
`time_from`/`time_to` (ISO-8601, on `last_seen_at`), `organization_id`
(platform roles; a non-visible id is 404), `limit` (1..200), `cursor`.
Sort `(last_seen_at DESC, id DESC)`, keyset cursor (base64 `{t, id}`),
response `{alerts: [...], next_cursor}`. Each row: id,
organization_id, kind ("detection"|"correlation"), rule_id,
rule_name, asset_id, severity, status, title, summary, group_key,
username, source_ip, event_count, first_seen_at, last_seen_at,
dismissed_reason, assigned_account_type, assigned_account_id,
correlation_id (pointer when the alert belongs to one), created_at.

### `GET /api/v1/alerts/{id}`

The alert plus: `events` (the supporting security_events, ordered by
occurred_at, max 200), `rule` (the detection rule; null on
correlation alerts), `correlation` (null, or {title, severity,
reasoning, first_seen_at, last_seen_at, event_count,
grouped_alerts: [...]} -- grouped_alerts are full alert rows), and
`history` (the alert's own timeline).

### Status transitions (one map, tested)

```
new          -> triaged | dismissed
triaged      -> investigating | dismissed
investigating -> triaged | dismissed | converted
dismissed    -> (only via /reopen)
converted    -> (terminal)
```

`ALERT_TRANSITIONS` in `app/routers/alerts.py` is the single source of
truth; an invalid move is `409 invalid_alert_transition`.

- `POST .../acknowledge` -- new -> triaged ONLY.
- `POST .../assign` -- body `{account_type: "admin"|"user",
  account_id}`. An in-house queue assigns to that org's own
  soc_analyst users; a platform-SOC-worked queue assigns to a platform
  SOC analyst assigned to that organization. Wrong-org/role targets
  are `422 assignee_not_in_scope` (unknown account:
  `404 assignee_not_found`).
- `POST .../dismiss` -- body `{reason}` REQUIRED (missing/empty: 422);
  the reason is stored on the alert and in history/audit.
- `POST .../reopen` -- only from dismissed, back to new; clears the
  dismissal reason.

Every change writes ONE `alert_history` row (the per-alert timeline;
worker-created alerts carry a `create` row with actor_type=system) and
ONE `audit_logs` row (`alert.acknowledge|assign|dismiss|reopen`).

### Alerts error code reference

| Code | Status | Where |
|---|---|---|
| `soc_not_visible` | 403 | list/detail for callers with no soc access at all |
| `alert_not_found` | 404 | invisible or cross-org ids; unassigned platform SOC |
| `alert_write_not_allowed` | 403 | managed-org accounts attempting writes |
| `invalid_alert_transition` | 409 | moves outside the map; reopen of a non-dismissed alert |
| `assignee_not_found` | 404 | assign to an unknown account |
| `assignee_not_in_scope` | 422 | assign outside the queue's scope rules |
| `invalid_status` / `invalid_severity` | 400 | unknown filter values on the list |
| `invalid_time_range` / `invalid_cursor` | 400 | malformed time/cursor query values |

## Background worker

`app/worker/` (Arq -- docs/DECISIONS.md) consumes the Redis queue
(`settings.redis_url`). The API enqueues through `enqueue_work`, which
never fails a request when Redis is down. The worker's heartbeat cron
(every 30s) upserts the single `worker_status` row (`id=1`:
`last_heartbeat_at`, `worker_name`, `pid`) so liveness is readable from
Postgres alone; worker startup fails fast with a clear error when Redis
is unreachable. The dev launcher starts Redis and a worker terminal
with the rest of the stack and checks both in `dev:doctor`.

The worker's jobs: `heartbeat` and `process_events` (event
normalization, then inline detection evaluation AND the P10 alerting
halves -- see "Event ingestion and read API", "Detection rules" and
"Alerts" above). Worker startup also seeds the 8 built-in detection
rules and the built-in correlation rule idempotently.

## Error code reference (structured-detail endpoints only)

| Code | Status | Where |
|---|---|---|
| `organization_suspended` / `organization_archived` | 403 (401 at login) | `require_active_organization`; `login` (401 only) |
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
