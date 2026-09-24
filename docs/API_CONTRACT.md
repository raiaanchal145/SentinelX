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
`q` (free text over type/user/ip and the JSONB payloads). Pagination:
cursor (keyset on `occurred_at DESC, id DESC`; `limit` 1-200, default
50), response `{"events": [...], "next_cursor"}`. Detail `GET
/api/v1/events/{id}` adds `raw_data`. A different organization's event
id is `404 event_not_found` (existence never leaked).

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
normalization -- see "Event ingestion and read API" above).

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
