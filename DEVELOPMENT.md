# Development Guide

Guidance for anyone (or any AI coding assistant) working in this repo.
Read this before making changes -- it's shorter than re-deriving these
rules from the code every time.

## What this is

SentinelX — an AI-assisted Security Operations & Incident Response
platform, built as an MCA (LJ University) final-year project by a team of
three (Ansh, Riteka, Aanchal). Frontend: React 19 + TypeScript + Vite +
Tailwind v4 + react-router-dom v7. Backend: FastAPI + async SQLAlchemy
2.0 + Alembic + PostgreSQL. See `README.md` for day-to-day setup
(`npm run dev` does almost everything).

## Repo map

```
src/
  App.tsx              route table + ProtectedRoute (role-gated)
  layouts/UserLayout.tsx    top-nav shell for soc_analyst/it_developer/manager/auditor
  components/Sidebar.tsx   left-sidebar shell for admin roles (super_admin/organization_admin)
  lib/auth.ts          session read/write (localStorage), role helpers
  lib/roleNav.ts       which nav items each role sees, in UserLayout
  lib/scope.ts         role/org scoping for the mock data layer -- see below
  lib/data.ts          THE ONLY module dashboard pages should pull mock data through
  lib/api.ts           real backend HTTP client (auth, stats) -- separate from the mocks
  types/                shared domain types (Alert, Incident, Ticket, Asset, ...)
  mocks/seed.ts         deterministic mock data generator (no Math.random)
  mocks/store.tsx       React context + reducer -- in-memory cross-role/cross-page state
  components/ui/         design-system primitives (Button, DataTable, KpiCard, Dialog, Toast, ...)
  features/<role>/pages/ role-specific dashboard pages (soc, it, manager, auditor)
  pages/                admin dashboards, auth pages (Login/Register/...)
  styles/theme.css, theme/tokens.ts   design tokens -- see "Frozen" below

backend/
  app/main.py           FastAPI app setup, CORS, security headers, /health, router mounting
  app/scope.py           THE ONE PLACE current account/role/organization is resolved and
                         enforced -- Scope, org_scope, require_admin, require_roles,
                         scoped_to_org(). Every organization-scoped endpoint depends on this.
  app/routers/          auth.py, organizations.py, stats.py -- one file per resource
  app/models.py         every SQLAlchemy model + enum (single source of truth for the schema)
  app/config.py         Settings (env vars), SECRET_KEY enforcement outside ENV=dev
  app/security.py       password hashing, JWT create/decode
  app/database.py       async engine/session, get_db dependency, declarative Base
  migrations/           Alembic, hand-written (never --autogenerate against someone else's)
  tests/                pytest + pytest-asyncio, async Postgres test-DB fixture

scripts/dev.mjs + scripts/lib/   the `npm run dev` one-command launcher (see README)
```

## Git workflow

- **`ansh-dev` is the working branch.** All day-to-day commits land on
  `ansh-dev` first -- never commit directly to `main` (or any other
  branch). `main` is promoted from `ansh-dev` deliberately (a fast-
  forward or merge), not written to directly.
- Before starting new work, make sure `ansh-dev` is at the same commit
  as `main` (`git merge --ff-only main` from `ansh-dev` if it's behind)
  so the two never silently diverge.
- Feature/chore branches (`feat/...`, `chore/...`) are short-lived: once
  merged into `ansh-dev`, delete them (`git branch -d <branch>`) rather
  than leaving merged branches around.
- Nothing is pushed to the shared remote without being asked explicitly.

## Hard constraints -- do not violate these without being told to

- **Theme tokens are frozen.** Never edit color values in `src/styles/theme.css`
  or `src/theme/tokens.ts`. Use only the existing token classes (bg-canvas,
  bg-surface*, border-line*, text-fg-*, brand-300..700, the severity tokens
  critical/high/medium/low/info, danger/success, radius-*). If a new color
  is genuinely needed, reuse the closest existing token and say so — don't
  invent one.
- **Admin layout (`Sidebar.tsx` + admin pages) stays structurally as-is**
  unless a task explicitly says to change it. Changing which routes its
  nav items point to is fine when asked; restructuring it is not.
- **No new npm dependencies** for the frontend without asking first —
  charts/visualizations are small inline-SVG components, not a charting
  library.
- **Never edit `backend/app/models.py` and hand-write a migration to
  match "close enough."** Migrations in this repo are hand-written, not
  `alembic revision --autogenerate`-generated, and were written to match
  models.py exactly (including raw `CREATE TYPE` statements for enums) --
  if you change a model, the migration must be written by hand to match,
  by whoever's task this is.
- **Login/registration pages and flows are stable** — don't change them
  as a side effect of an unrelated task.
- **Mock data must always be visually labelled** (the existing
  `DemoDataChip` component) on any page it backs. Never let mock data look
  like it came from the real API.

## Frontend: mock data vs. real backend

Two separate data paths currently coexist:

1. `src/lib/api.ts` — the real HTTP client, currently only used for
   auth (register/login/verify/me/forgot-reset password) and
   `/stats/overview`. Both of those now require an authenticated
   request (`Authorization: Bearer <token>`), which `api.ts`'s `request()`
   helper already attaches automatically when a token is in
   `localStorage`.
2. `src/mocks/` + `src/lib/data.ts` — a fully in-memory, deterministic
   mock backend for everything the real API doesn't implement yet
   (alerts, incidents, tickets, assets, audit log). `src/lib/data.ts` is
   the **only** module dashboard pages should import this data through;
   every function there takes `(state, scope)` and is already shaped to
   become an async real API call later without changing call sites. Role
   scoping is centralized in `src/lib/scope.ts` — note its comment that
   UI-side scoping is not a substitute for real backend authorization.

When wiring a new page, check `lib/data.ts` first — if the function you
need already exists, use it; don't reach into `mocks/store.tsx` state
directly from a page component.

## Backend: routers, scope, and tenant isolation

`app/main.py` only does app setup (CORS, security headers, `/health`)
and mounts three routers:

- `app/routers/auth.py` — register/verify-email/resend-verification/
  login/me/forgot-password/reset-password. Its own `_account_by_email` /
  `_role_value` helpers are for the email+password login path only.
- `app/routers/organizations.py` — create (admin-only) and list
  organizations, both tenant-scoped (see below).
- `app/routers/stats.py` — `/stats/overview`, tenant-scoped.

**`app/scope.py` is the one place "who is calling, what role, which
organization" is resolved and enforced.** Any endpoint that reads or
writes organization-scoped data must depend on one of:

- `org_scope` — resolves the bearer token into a `Scope` (account, role,
  `organization_id`, where `None` means "all organizations" and only
  ever applies to a `super_admin`).
- `require_admin` — like `org_scope`, but 403s anything that isn't an
  admin account.
- `require_roles(*roles)` — like `org_scope`, but 403s a `users` account
  whose role isn't one of `roles` (admins always pass).

...and filter its queries with `scoped_to_org(stmt, model, scope)`
rather than trusting a client-supplied organization id. The frontend has
a same-shaped `src/lib/scope.ts`, but that one is UI-only and explicitly
says so in its own comments -- `app/scope.py` is what actually enforces
the tenant boundary. See `backend/tests/test_scope.py` for the
tenant-isolation matrix (org A can never read org B's organizations/
stats) and role-guard tests -- extend that file with a case for every
new organization-scoped endpoint.

If you add a new resource (e.g. alerts, tickets), give it its own
`app/routers/<name>.py`, depend on `org_scope`/`require_admin`/
`require_roles` from `app/scope.py`, and add its isolation cases to
`test_scope.py` -- rather than growing `main.py` or inventing a new
auth pattern.

`SECRET_KEY` has a safe hardcoded default, but only while `ENV=dev`
(the default). Setting `ENV` to anything else and leaving `SECRET_KEY`
unset/default makes the app refuse to start — see
`app/config.py::_require_secret_key_in_non_dev`. Set a real `SECRET_KEY`
in `backend/.env` before ever running this outside localhost.

## Testing

Backend: `pytest` from `backend/`, after creating a separate test
database once (`createdb sentinelx_test`, or set `TEST_DATABASE_URL`).
See `backend/tests/conftest.py` — it creates every table fresh per test
and overrides `get_db` so requests hit the test database through an
httpx client wired directly to the FastAPI app (no server process
needed). Add new tests as `backend/tests/test_<resource>.py`.

Frontend: no test runner is set up yet. `npx tsc -b` (type-check) and
`npm run build` are the current gates; `npm run lint` runs `oxlint`.

## Environment quirk worth knowing

This project is developed partly through a Linux sandbox bridged to a
Windows machine's files. `npx tsc -b` runs fine there (pure JS, no
native binary), but `npm run build`'s Vite/Rolldown step and `npm run
lint`'s `oxlint` need native bindings that don't match across
Windows/Linux, and the npm/PyPI registries are blocked from that
sandbox — so those two, and any real Python import/run of the backend,
can only be verified on the actual (Windows) development machine.
