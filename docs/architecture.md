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

- `auth.py` — registration (OTP-verified), login (JWT), forgot/reset
  password, `/me`; also exports the `get_current_user` /
  `get_current_admin` / `require_roles` dependencies every other router
  uses.
- `organizations.py` — create (admin-only) / list (any authenticated
  account).
- `stats.py` — `/stats/overview` (any authenticated account).

Both `organizations` list and `stats/overview` require authentication;
they did not originally, which was an information-leak (org names,
user/asset counts) to anyone who could reach the API unauthenticated.

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

- The frontend session/`UserOut` payload carries no `organization_id`,
  so real multi-tenant scoping isn't wired to identity yet -- every
  non-super-admin mock session is pinned to one hardcoded demo
  organization. Only `super_admin`'s org switcher is fully live across
  the mock orgs.
- The pipeline tables (`alerts`, `incidents`, `tickets`, etc.) exist in
  the schema and migrations but have no real API endpoints yet -- the
  dashboards that display this data are still backed entirely by the
  mock layer described above.
