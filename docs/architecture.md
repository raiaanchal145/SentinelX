# Architecture

## High level

```
React SPA (Vite)  <-- HTTP -->  FastAPI  <-- asyncpg -->  PostgreSQL
   src/                          backend/app/
```

Two roughly independent layers exist on the frontend today:

- A **real** path: login/registration/session, and `/stats/overview`,
  talk to the actual FastAPI backend via `src/lib/api.ts`.
- A **mock** path: every operational dashboard (SOC, IT, admin oversight)
  runs entirely on in-memory generated data (`src/mocks/`), scoped by
  role/org (`src/lib/scope.ts`) and read through a single indirection
  layer (`src/lib/data.ts`) so it can be swapped for real endpoints
  later without changing the pages that call it.

## Frontend roles and routing

`src/App.tsx` defines every route and wraps role-restricted ones in
`ProtectedRoute`, which reads the session from `src/lib/auth.ts`
(role + account_type, currently stored in `localStorage` after login)
and redirects unauthenticated or wrong-role visitors.

Two different shells exist for two different kinds of role:- **`UserLayout`** (top navigation) — for `soc_analyst`, `it_developer`,
  `security_manager` ("manager"), and `auditor`. Which nav items each
  role sees is defined in `src/lib/roleNav.ts`, filtered further by
  each item's optional `module` against `useMe().effective_modules`
  (module-less items, i.e. each role's own overview, always show).
- **`Sidebar`** (left sidebar, composed directly by each page under
  `src/pages/` and `src/features/{admin,owner}/pages/` — it is not a
  layout route) — for `super_admin`, `organization_admin` (the
  organization owner), and `platform_soc_analyst`.

Every route inside the four `UserLayout` roles above, except each
role's own overview/home route, is additionally wrapped in
`ModuleGuard` (`src/components/ModuleGuard.tsx`): it reads
`effective_modules` from `useMe()` and redirects to `/no-access` if
the route's required module isn't in that map. This is a second,
independent check behind the nav filtering above, for anyone who
still has a direct URL to a module their organization or owner has
turned off. Separately, `UserLayout` and `OwnerDashboard` both watch
`useMe()`'s `organization.status` on every render and redirect to
`/organization-suspended` if it becomes `suspended`/`archived` —
an already-logged-in session's token and cached `effective_modules`
stay valid until the next `/auth/me` call, so without this an
employee or owner could sit on a stale page after their organization
is suspended mid-session.

Current routes / screens (see `App.tsx` for the authoritative list):

| Path | Role(s) | Notes |
|---|---|---|
| `/login`, `/verify-email`, `/forgot-password`, `/reset-password` | anyone | real backend auth. SentinelX is invite-only (docs/DECISIONS.md) -- there is no `/register`; the login page states that access is by invitation |
| `/accept-invite` | anyone (token from the invite link) | `src/pages/AcceptInvite.tsx` — sets a name/password for an owner-, member-, or platform-SOC-kind invitation and signs the new account in |
| `/organization-suspended`, `/no-access` | any authenticated account | `src/pages/OrganizationSuspended.tsx` / `NoAccess.tsx` — status/guard screens; each offers sign-out (the pending screen died with self-signup; organizations are born active) |
| `/admin/organizations`, `/admin/organizations/:id` | super_admin | `src/features/admin/pages/Organizations.tsx` (search/filter/sort/suspend/reactivate/archive, create-org dialog with the owner's email) and `OrganizationDetail.tsx` (Overview/Members/Access-and-modules/SOC/Assets/Activity/Settings tabs; the detail page shows the owner invitation's status with resend/revoke) |
| `/admin/soc-team` | super_admin | `src/features/admin/pages/SocTeam.tsx` — invite/list/deactivate platform SOC analysts, edit each one's assigned `managed` organizations |
| `/admin/soc-queue` | platform_soc_analyst | `src/features/admin/pages/SocQueue.tsx` — restricted nav (SOC Queue only), placeholder queue over this analyst's own assigned organizations, plus a read-only assets view of whichever assigned organization is selected |
| `/admin` | super_admin, organization_admin | admin dashboard (unchanged) |
| `/organization-dashboard` | super_admin, organization_admin | legacy org-scoped admin view, kept reachable for compatibility; the owner's real home is now `/organization` below |
| `/organization` | organization_admin | `src/features/owner/pages/OwnerDashboard.tsx` — reads `GET /organization` live and redirects to the pending/suspended screen if the organization isn't active |
| `/organization/members` | organization_admin | `OwnerMembers.tsx` — Members / Pending invitations tabs, invite-member dialog |
| `/organization/teams` | organization_admin | `OwnerTeams.tsx` — team CRUD, per-team membership drawer |
| `/organization/assets` | organization_admin | `OwnerAssets.tsx` — real asset inventory (write) over the shared AssetsPage |
| `/organization/access` | organization_admin | `OwnerAccess.tsx` — role x module access matrix, per-member override drawer |
| `/organization/settings` | organization_admin | `OwnerSettings.tsx` — read-only organization settings |
| `/admin/soc-oversight`, `/admin/it-oversight` | super_admin, organization_admin | aggregate rollups (unchanged) |
| `/soc`, `/soc/alerts`, `/soc/incidents(/:id)`, `/soc/events`, `/soc/assets`, `/soc/reports` | soc_analyst | `/soc/assets` is the real, read-only asset inventory; every other route is a mock-data dashboard; every route but `/soc` itself is `ModuleGuard`-wrapped (`soc`/`incidents`/`assets`/`reports`) |
| `/it`, `/it/tickets(/:id)`, `/it/assets`, `/it/runbooks` | it_developer | `/it/assets` is the real asset inventory (write; the backend scopes the IT developer's writes to assets they own or that belong to their team); every other route is a mock-data dashboard; every route but `/it` itself is `ModuleGuard`-wrapped (`it_tickets`/`assets`) |
| `/manager/*` | security_manager | `/manager/assets` is the real asset inventory (write); every other route is a mock-data dashboard; every route but `/manager` itself is `ModuleGuard`-wrapped (`incidents`/`approvals`/`reports`/`assets`/`audit_logs`) |
| `/auditor/*` | auditor | `/auditor/assets` is the real, read-only asset inventory; every other route is a mock-data dashboard; every route but `/auditor` itself is `ModuleGuard`-wrapped (`audit_logs`/`incidents`/`assets`/`reports`) |
| `/soc-dashboard`, `/it-dashboard` | -- | legacy paths, redirect to `/soc`/`/it` |

## Backend

`backend/app/models.py` is the single source of truth for the schema —
every table and enum is defined there as SQLAlchemy models, and the
Alembic migrations under `backend/migrations/versions/` are hand-written
to match it (not generated). Two account tables exist by design:
`admins` (super_admin/organization_admin) and `users` (soc_analyst,
security_manager, it_developer, auditor) — kept separate so admin auth
never shares a table, role enum, or query path with analyst/developer
accounts. `account_emails` enforces one email across both tables, since
Postgres can't put a single UNIQUE constraint across two tables.

`backend/app/main.py` only wires up the app (CORS, security headers,
`/health`) and mounts routers from `backend/app/routers/`:

- `auth.py` — registration (OTP-verified, organization-owner-only —
  see below), login (JWT), forgot/reset password, `/me`.
- `organizations.py` — legacy create/list, now super_admin-only (kept
  for compatibility; see `docs/DECISIONS.md`). Superseded by
  `admin_organizations.py` and `organization.py` below.
- `stats.py` — `/stats/overview`, tenant-scoped.
- `admin_organizations.py` — platform admin management of every
  organization (lifecycle, modules, soc-mode, members, activity).
  super_admin-only.
- `admin_soc.py` — platform SOC team management (invite, list, assign
  to managed organizations). super_admin-only.
- `organization.py` — an organization owner's own organization: members,
  invitations, teams, the access matrix. organization_admin-only, own
  organization only.
- `assets.py` — the asset inventory, the first real pipeline data (see
  docs/API_CONTRACT.md "Assets"): organization-side CRUD + tags +
  summary + lookup, with per-row `can_edit` on every row and full audit
  coverage. organization_admin/security_manager write; it_developer
  writes only its own/team's assets; soc_analyst/auditor read;
  platform_soc_analyst reads assigned organizations via an explicit
  `organization_id` checked against `soc_visible_organization_ids()`.
- `invitations.py` — public (no auth) invitation validate/accept; the
  only way to create a member account, a platform-created owner
  account, or a platform SOC analyst account.

`backend/app/scope.py` is the one place "who is calling, what role,
which organization" is resolved and enforced: `Scope` (account, role,
`organization_id` -- `None` means "every organization", for both
`super_admin` and the newer `platform_soc_analyst`), and the
dependencies `org_scope` / `require_admin` / `require_roles(*roles)`
that every organization-scoped endpoint depends on, plus
`scoped_to_org(stmt, model, scope)` to filter a query by the caller's
own organization. `app/access.py` builds on top of `scope.py` with the
organization-management-specific guards (`require_super_admin`,
`require_platform_admin`, `require_platform_soc`, `require_org_owner`,
`require_active_organization`, `require_module`) and the layered
effective-access calculation — see the section below.

Both `organizations` list and `stats/overview` require authentication;
originally neither check existed, which was both an information-leak
(readable with no token at all) and a tenant-isolation gap (any
authenticated account, in any organization, saw every organization's
data). `backend/tests/test_scope.py` is the regression suite for both,
plus a `scoped_to_org` fail-closed check for `platform_soc_analyst` and
an is-active-rechecked-on-every-request check.

## Organizations, access control and invitations

### How accounts are created (invite-only)

There is no public registration. Accounts come from exactly three
places, and every one of them is an invitation acceptance or the
server-side bootstrap command:

1. A platform `super_admin` creates an organization (status `active`
   immediately) together with the owner's invitation (`kind=owner`);
   the owner account comes into existence only when that invitation is
   accepted -- the link proves email ownership, so there is no OTP step
   at signup.
2. An organization's owner invites members by email (IT developers,
   security managers, auditors; SOC analysts only while the
   organization is `in_house`); they accept the same way.
3. A platform `super_admin` invites platform SOC analysts
   (`kind=platform_soc`, no organization).

The **first** `super_admin` is created by the one-time, server-side
command `python -m app.create_super_admin` (interactive getpass
prompts, or `SEED_SUPER_ADMIN_EMAIL`/`SEED_SUPER_ADMIN_PASSWORD`/
`SEED_SUPER_ADMIN_NAME` for non-interactive dev). It refuses a second
bootstrap and never prints the password. The dev launcher
(`npm run dev`) checks for an existing active super_admin after
migrations and offers to run the command on a first run; once one
exists, it stays silent.

### Organization status

An organization is **active** from the moment the platform admin
creates it, and moves through `active -> suspended/archived`
(`organizations.status` -- there is no `pending` value anymore;
migration `d5e6f7a8b9c0` removed it after converting any historical
rows to active). Only `active` organizations can use their own
member/invitation/access endpoints (`require_active_organization`) --
`GET /auth/me` and the owner's `GET /organization` overview are the two
deliberate exceptions, so the frontend always has something to read to
show the right suspended/archived screen.

`organizations.soc_mode` is `managed` (platform SOC staff, assigned via
`soc_organization_assignments`, work its alerts/incidents; the owner
sees `soc`/`incidents` read-only) or `in_house` (the organization's own
`soc_analyst` members work them, at full access; a `soc_analyst` role
can only be assigned/invited while `in_house`).

Effective module access for an organization's own accounts
(`app/access.py::get_effective_access`) is four layers, each only ever
narrowing what an earlier layer already allowed, never widening it:

```
organization_modules (platform on/off per org)
  AND role default map (ROLE_DEFAULT_MODULES, per UserRole)
  AND organization_role_access (owner's per-role narrowing)
  AND user_access_overrides (owner's per-person narrowing)
  = effective_modules, {module_key: "read"|"write"}
```

The organization owner (`organization_admin`) isn't a `UserRole` and
isn't subject to the three narrowing tables above; their effective
access is every platform-enabled module at `write`, except `soc`/
`incidents` drop to `read` while `soc_mode = managed` (see
`docs/DECISIONS.md`). `super_admin` and `platform_soc_analyst` don't go
through this calculation at all -- they reach organization data through
`/admin/*` endpoints and their own `require_*` guards.

The only way to create a member account, a platform-created owner
account, or a `platform_soc_analyst` account is an **invitation**
(`invitations` table): a 7-day, single-use, SHA-256-hashed token
(`app/security.py::generate_invitation_token`/`hash_invitation_token`
-- a cheaper, deliberately different mechanism than password bcrypt
hashing), rate-limited to 20 per organization per hour (globally for
platform-SOC invitations, which have no organization). `app/invite_service.py`
holds the create/rotate logic shared by every router that sends one;
`app/routers/invitations.py` is the public accept side.

New tables (`backend/app/models.py`, migration
`a4b5c6d7e8f9_org_management_and_access_control`):

| Table | Purpose | Key columns |
|---|---|---|
| `organization_modules` | Platform on/off per module per organization (widest access layer). | `organization_id`, `module_key`, `enabled` |
| `organization_role_access` | Owner's per-role narrowing of the role default map. | `organization_id`, `role`, `module_key`, `enabled` |
| `user_access_overrides` | Owner's per-person narrowing (deny-only). | `user_id`, `organization_id`, `module_key`, `allowed` |
| `invitations` | The only path to a member/owner/platform_soc account. | `organization_id` (NULL for `platform_soc`), `email`, `kind`, `role`, `token_hash`, `status`, `expires_at` |
| `soc_organization_assignments` | Which `platform_soc_analyst` admins see which `managed` organizations. | `admin_id`, `organization_id` |

Changed columns: `organizations` gained `status` (now a real enum, was
a plain string), `soc_mode`, `max_members`, `created_via`,
`approved_by_admin_id`/`approved_at` (kept as the record of which
super_admin created the organization and when -- the approve flow itself
is gone), `suspended_at`/`suspension_reason`; `admins.admin_level`
gained `platform_soc_analyst` (its `organization_id`
is `NULL`, same check-constraint shape as `super_admin`). The
`pending_registrations` table was dropped by migration `d5e6f7a8b9c0`
(invite-only); unexpired registration codes it held were discarded.

Every business-rule/permission rejection in this feature raises a
structured `{code, message}` detail rather than a bare string, so the
frontend can switch on `code` -- see `docs/API_CONTRACT.md` for the
full endpoint-by-endpoint reference and error code table, and
`docs/DECISIONS.md` for the ambiguities resolved and trade-offs made
while building it.

## Assets: the first real pipeline feature

`app/routers/assets.py` serves the asset inventory everything else
(events → alerts → incidents → tickets) will point at. Deletion is
**soft only** (`status=retired`; there is no hard-delete path in the API
at all), hostnames are optional but unique per organization when set
(partial unique index `(organization_id, lower(hostname))` in migration
`b8c9d0e1f2a3`), and every create/update/status-change/tag-change/retire
writes an `asset.*` audit entry with a before/after summary.

Role access (module floor via `require_module("assets", ...)` plus
row-level checks in `_can_write_asset`):

| Role | Access |
|---|---|
| organization_admin (owner) | write |
| security_manager | write |
| it_developer | write, row-scoped to assets they own or that sit on their team |
| soc_analyst, auditor | read |
| platform_soc_analyst | read, assigned `managed` organizations only, via `?organization_id=` |
| super_admin | `GET /admin/organizations/{id}/assets`, read-only |

On the frontend, one shared component —
`src/features/assets/AssetsPage.tsx` — is reused by the owner
(`/organization/assets`, write), IT (`/it/assets`, write with per-row
own/team scoping), manager (`/manager/assets`, write), SOC
(`/soc/assets`, read) and auditor (`/auditor/assets`, read). Write
controls render only when `effective_modules.assets` is `write`, and
per-row actions follow the backend-computed `can_edit`. The platform
admin's organization detail has a read-only Assets tab backed by
`GET /admin/organizations/{id}/assets`, and the platform SOC queue embeds
a read-only assets view of the selected assigned organization.

## The mock data layer (frontend)

```
mocks/seed.ts    deterministic generator: orgs, users, assets, alerts,
                 incidents, tickets, audit entries. No Math.random --
                 same data every load, timestamps computed relative to
                 load time so SLA countdowns still feel live.
mocks/store.tsx  React context + useReducer wrapping the seed data,
                 mounted once near the app root (src/main.tsx) so every
                 page/role in a session shares the same state and sees
                 each other's actions (e.g. a SOC analyst escalating an
                 alert to an incident is visible on the admin oversight
                 view in the same session).
lib/scope.ts     scopeFor(session) -> {role, accountType, organizationId,
                 userId, teamId}. Centralizes "what can this role see" in
                 one place. Explicitly documented as UI-only -- the real
                 backend must enforce the same rules independently once
                 these dashboards talk to real endpoints.
lib/data.ts      getSocKpis(state, scope), getTriageQueue(...), etc. --
                 the only functions pages should pull dashboard data
                 through. Each already takes (state, scope) and is
                 latency-simulated, so swapping in real API calls later
                 is a signature-preserving change.
```## Known gaps

- The platform admin, organization owner, and public UI for this
  feature is now built (organizations list + 6-tab detail, platform
  SOC team + queue, owner dashboard/members/teams/access/settings,
  accept-invite, and the suspended/no-access screens -- see
  the routes table above), and `UserLayout`'s nav plus `ModuleGuard`
  now drive navigation and route access from the real
  `organization`/`effective_modules` fields `GET /auth/me` returns.
  Auth pages are invite-only: `/register` and the organization-pending
  screen are deleted (see docs/DECISIONS.md).
  What's still mock-backed is the *content* inside the SOC/IT/manager/
  auditor dashboards themselves (KPIs, queues, tables) -- with one
  exception: **assets are real end to end** (see the section above);
  every role's Assets page talks to the actual `/assets` API. The
  remaining mock-backed content is alerts/incidents/events/tickets
  queues and KPIs. See the pipeline-tables bullet below.
- The register page was removed entirely along with self-signup
  (invite-only, docs/DECISIONS.md) -- accounts exist only through
  invitation acceptance or the create_super_admin bootstrap.
- The pipeline tables (`alerts`, `incidents`, `tickets`, etc.) exist in
  the schema and migrations but have no real API endpoints yet -- the
  dashboards that display this data are still backed entirely by the
  mock layer described above. `assets` is the exception: its endpoints
  (`app/routers/assets.py`) and UI are real, which is what the events,
  alerts, incidents and tickets work will point at. Event sources
  (`app/routers/event_sources.py`) and the background worker
  (`app/worker/`) are the second and third real pieces: sources
  register collectors and mint hashed API keys (`sx_<prefix>_<secret>`,
  shown once, SHA-256 at rest, owner + security_manager only --
  docs/DECISIONS.md), and the Arq worker consumes the Redis queue
  (`settings.redis_url`) with a 30s heartbeat cron upserting the
  single `worker_status` row the API reads for liveness. The dev
  launcher runs the whole stack: Postgres + Redis (docker compose),
  uvicorn, the worker (`python -m arq app.worker.WorkerSettings`), and
  Vite. Ingestion endpoints (P07) authenticate with the
  `get_event_source_from_api_key` dependency and enqueue parse jobs
  through `enqueue_work`.
- **Events are real end to end (P07)** -- the pipeline's second real
  piece after assets: `POST /api/v1/events` (API-key auth from the
  event-source keys, batch limits, per-key Redis rate limit, no payload
  organization_id ever trusted) -> the `process_events` worker job
  (per-source-type parsers -> normalized schema, dedup via
  `uq_security_events_org_dedup_hash` + `ON CONFLICT DO NOTHING`,
  asset enrichment by hostname/IP, severity defaulting, size-capped
  `raw_data`) -> `GET /api/v1/events[/{id}]` (user token, module `soc`
  read, keyset cursor pagination, visibility through
  `soc_visible_organization_ids()` plus the managed-mode owner's
  read-only oversight). The fixed `event_type` vocabulary and the full
  schema/access matrix are documented in docs/API_CONTRACT.md "Event
  ingestion"; the list query is measured against 100k rows in
  docs/reports/event-ingestion.md. Parsers for all seven source types
  (`linux_auth`, `application`, `docker`, `network`, `windows`,
  `custom_json`, `test`) live in `app/worker/parsers.py`; the `windows`
  parser is for the endpoint agent arriving in P21.
