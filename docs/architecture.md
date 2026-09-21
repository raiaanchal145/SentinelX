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

Two different shells exist for two different kinds of role:

- **`UserLayout`** (top navigation) — for `soc_analyst`, `it_developer`,
  `security_manager` ("manager"), and `auditor`. Which nav items each
  role sees is defined in `src/lib/roleNav.ts`.
- **`Sidebar`** (left sidebar, inside the admin pages under `src/pages/`)
  — for `super_admin` and `organization_admin`.

Current routes (see `App.tsx` for the authoritative list):

| Path | Role(s) | Notes |
|---|---|---|
| `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password` | anyone | real backend auth |
| `/admin` | super_admin, organization_admin | admin dashboard |
| `/organization-dashboard` | super_admin, organization_admin | org-scoped admin view |
| `/soc`, `/soc/alerts`, `/soc/incidents(/:id)`, `/soc/events`, `/soc/assets`, `/soc/reports` | soc_analyst | mock-data dashboards |
| `/it`, `/it/tickets(/:id)`, `/it/assets`, `/it/runbooks` | it_developer | mock-data dashboards |
| `/manager/*` | security_manager | mock-data dashboards |
| `/auditor/*` | auditor | mock-data dashboards |
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

An organization moves through `pending -> active -> suspended/archived`
(`organizations.status`). Self-signup always creates a **pending**
organization owned by a brand-new `organization_admin`; a platform
`super_admin` creates an already-**active** one directly. Only
`active` organizations can use their own member/invitation/access
endpoints (`require_active_organization`) -- `GET /auth/me` and the
owner's `GET /organization` overview are the two deliberate exceptions,
so the frontend always has something to read to show the right
pending/suspended/archived screen.

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
`approved_by_admin_id`/`approved_at`, `suspended_at`/`suspension_reason`;
`admins.admin_level` gained `platform_soc_analyst` (its `organization_id`
is `NULL`, same check-constraint shape as `super_admin`);
`pending_registrations` gained `organization_industry` (carries the
register form's optional industry field across to the organization
created at `verify-email`).

Every business-rule/permission rejection in this feature raises a
structured `{code, message}` detail rather than a bare string, so the
frontend can switch on `code` -- see `docs/API_CONTRACT.md` for the
full endpoint-by-endpoint reference and error code table, and
`docs/DECISIONS.md` for the ambiguities resolved and trade-offs made
while building it.

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
```

## Known gaps

- The frontend's mock-data dashboards (SOC/IT/manager/auditor pages)
  are still pinned to one hardcoded demo organization/session shape and
  don't yet read the real `organization`/`effective_modules` fields
  `GET /auth/me` now returns, or drive navigation from them -- that
  wiring, plus the platform admin/organization owner/public UI for
  this feature, is a separate, explicitly-gated frontend task (not yet
  started as of this section being written).
- The register page's role picker was removed as a small, approved
  frontend exception ahead of that larger task (self-signup is now
  organization-owner-only) -- see `src/pages/Register.tsx`.
- The pipeline tables (`alerts`, `incidents`, `tickets`, etc.) exist in
  the schema and migrations but have no real API endpoints yet -- the
  dashboards that display this data are still backed entirely by the
  mock layer described above.
