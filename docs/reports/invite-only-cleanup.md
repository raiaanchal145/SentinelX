# Invite-only cleanup — usage matrix and deletion list

Branch: `chore/r1-invite-only`. SentinelX becomes invite-only: there is no
public registration and no organization self-signup. Accounts come from
exactly three places — (a) a platform admin creates an organization and
invites the owner, (b) an owner invites members by email (soc_analyst only
while `soc_mode = in_house`), (c) a platform admin invites platform SOC
analysts. The first super_admin is created by `python -m app.create_super_admin`,
never through a public page.

This report is the mandatory STEP 1 usage matrix plus the final list of
everything deleted. Every DELETE below was verified reference-by-reference
before deletion.

## Usage matrix

### Backend

| Candidate | Every reference found | Verdict |
|---|---|---|
| `POST /auth/register` + `RegisterRequest`/`RegisterResponse` | `app/routers/auth.py` (impl); frontend `apiRegister`/`RegisterResponse`; tests `test_auth.py` (4 tests), `test_org_lifecycle.py` (step 1); docs (API_CONTRACT, architecture, DECISIONS); README | DELETE — tests rewritten/removed, docs updated, frontend caller deleted |
| `SUPER_ADMIN_EMAILS` allow-list (`auth.py`) | Only inside `register()`/registration branch of `verify_email()` | DELETE — replaced by `app/create_super_admin.py`; existing allow-list super_admin accounts keep working (their rows are untouched) |
| Registration branch of `POST /auth/verify-email` (pending_registrations lookup, org creation, account creation, `seed_default_modules` call there) | `auth.py`; `test_org_lifecycle.py` step 1, `test_auth.py` main flow | DELETE — endpoint keeps only the account-re-verify (lockout) branch |
| Registration branch of `POST /auth/resend-verification` | `auth.py`; `test_auth.py` | DELETE |
| Unknown-email 404s on verify/resend ("No pending registration found… register again") and forgot-password | `auth.py` | MODIFY — all three become generic responses that never reveal whether an email exists (they did reveal before; tests now assert identical shaped responses) |
| Rate limiting on verify/resend | None existed | ADD — small per-email resend limit (60 s) + in-memory attempt cap on verify, with tests; codes were already single-use and 10-minute expiry |
| Lockout flow: 3 wrong passwords → reset `failed_login_attempts`, `is_verified=false`, 10-minute code emailed → verify → login | `auth.py` (`login`), `models.py` columns, `email_utils.send_verification_email`, Login.tsx redirect, VerifyEmail.tsx | KEEP — verified and now covered by a dedicated lockout test file |
| `is_verified`, `verification_code`, `verification_code_expires_at`, `failed_login_attempts` columns (admins + users) | `models.py`, `auth.py`, `scope.py` (is_active), tests | KEEP |
| `POST /admin/organizations/{id}/approve` + `organization.approve` audit action | `admin_organizations.py`; frontend `apiApproveOrganization`, Approve/Reject actions, pending filter/badge in `Organizations.tsx`; `test_org_lifecycle.py`; API_CONTRACT | DELETE — platform-created organizations are active immediately; no pending organizations exist after migration |
| `OrganizationStatus.pending` enum value | `models.py`; `access.py` (`organization_pending` 403), `auth.py` login/`me` branches, `organization.py` overview pending branch + `require_active_organization` message, `admin_organizations.py` `_transition` allowed_from sets; frontend status unions + STATUS_TONE + Login/OwnerDashboard redirects; migration `a4b5c6d7e8f9` (creates the type — old migration untouched; new migration rebuilds the type) | DELETE — value removed from the DB type via rename/create/alter/drop; every producing/consuming code path removed |
| `organization_pending` 403 code + `require_active_organization` pending branch | `access.py`; `test_org_lifecycle.py`; API_CONTRACT | DELETE (pending can no longer exist) |
| `pending_registrations` table + `PendingRegistration` model (+ `organization_industry` column) | `models.py`; `auth.py`; migrations `c9d3e4f5a6b7` (create), `f2a3b4c5d6e7` (alter), `a4b5c6d7e8f9` (add org name/industry columns — historical, untouched); `test_auth.py`, `test_org_lifecycle.py`; docs | DELETE model + code; new migration drops the table (existing unexpired registration codes are discarded — noted in the migration) |
| `created_via` column (`self_signup`/`platform_admin`) | `models.py`; `admin_organizations.py` (sets `platform_admin`), `auth.py` (self_signup — deleted with register), `organizations.py`; exposed in `_org_row`; frontend `OrganizationRow.created_via` | KEEP — per decision; only `platform_admin` is ever written now |
| `approved_by_admin_id` / `approved_at` columns | `models.py`; set at platform-created org creation in `admin_organizations.py`; approve endpoint (deleted); `_transition` approve apply (deleted) | KEEP — still meaningful ("which super_admin created/approved this org at creation"); renaming would be churn; documented in DECISIONS |
| `GET/POST /api/v1/organizations` (legacy router) | `routers/organizations.py`; `main.py` include; `test_scope.py` (3 tests), `test_auth.py` (1); **no frontend caller** (UI uses `/admin/organizations`) | DELETE — router, include, and its tests (isolation coverage already exists against the real surfaces) |
| Owner invitation lifecycle (create at org creation; resend/revoke) | Create: `admin_organizations.py`. Resend/revoke: only owner-side `organization.py` endpoints exist (`GET/POST/DELETE /organization/invitations*`, org-scoped) — **no super_admin path existed** | KEEP create; ADD super_admin view/resend/revoke (`GET/POST/DELETE /admin/organizations/{id}/invitations…`) + admin UI |
| `send_verification_email` ("If you didn't create a SentinelX account…" copy) | lockout flow + tests | KEEP — copy reworded for the lockout-only use |
| `send_password_reset_email`, `send_invitation_email`, `generate_verification_code` | forgot/reset, invitations | KEEP |
| `validators.py` (`is_valid_email_format`, `is_valid_name_format`) | `auth.py` login/verify, `invitations.py` accept | KEEP (register's name validation dies with register; both helpers still used) |
| `invite_service.py` (rate limit, create, rotate) | admin_organizations, admin_soc, organization | KEEP |
| `seed_default_modules` | `admin_organizations.py`, `organizations.py` (dies), `access.py` def, tests helpers | KEEP (used at platform-created org creation) |
| `getpass`-style password input | nothing | ADD — `app/create_super_admin.py` (stdlib only; no new dependency) |

### Frontend

| Candidate | Every reference found | Verdict |
|---|---|---|
| `Register.tsx`, `/register` route, `apiRegister`, `RegisterResponse` | `App.tsx`, `lib/api.ts`, `Login.tsx` "Register" link | DELETE |
| "Create account / Sign up" links | Login page only | DELETE — replaced by the invitation-only line |
| `OrganizationPending.tsx`, `/organization-pending` route, Login + OwnerDashboard redirects | `App.tsx`, `Login.tsx`, `OwnerDashboard.tsx` | DELETE (suspended/archived/no-access screens stay) |
| `organization_pending` handling in frontend guards | Login.tsx navigate, OwnerDashboard navigate | DELETE with the screen |
| Approve/Reject/pending UI in `Organizations.tsx` (`handleApprove`, actions, `<option value="pending">`, STATUS_TONE.pending, "approve new sign-ups" copy, reject-confirm copy) | `Organizations.tsx`, `lib/api.ts` | DELETE |
| `apiApproveOrganization` | `lib/api.ts`, `Organizations.tsx` | DELETE |
| VerifyEmail page + route + api functions | App.tsx, lib/api.ts, Login redirect | KEEP — copy updated to lockout wording; entry point stays (login redirect) |
| Login verify-redirect on "verify" message | Login.tsx | KEEP |
| Owner invitation status UI in admin org detail/list | none today | ADD — status badge (pending/expired/accepted), resend + revoke, "Owner has not accepted yet" on the list row |
| Mocks (`src/mocks/`), theme/tokens, admin layout | untouched by this feature | KEEP |

### Dead-code scan

- `npx tsc -b` compiles with `noUnusedLocals`/`noUnusedParameters` on — the
  build gate IS the unused-code scan for TS; kept green after deletions.
- `oxlint`: 0 errors before and after; warning count did not increase.
- `python -m vulture`: **not installed** in this environment — skipped per
  instruction (nothing installed). Manual grep-audit of `validators.py`,
  `security.py`, `email_utils.py`, `invite_service.py` found no unused
  helpers after the change (all referenced by surviving flows above).

## Deleted (final list)

Endpoints:

- `POST /api/v1/auth/register`
- `POST /api/v1/admin/organizations/{id}/approve`
- `GET /api/v1/organizations`, `POST /api/v1/organizations` (legacy router)

Code:

- `RegisterRequest`/`RegisterResponse` schemas; the registration branches of
  `verify-email`/`resend-verification`; `SUPER_ADMIN_EMAILS`
- `PendingRegistration` model
- `OrganizationStatus.pending` member and every `organization_pending` path
  (access.py branch, login allowed-while-pending branch, overview pending
  branch, transition sets, frontend screens/guards)
- Legacy `app/routers/organizations.py` and its `main.py` include
- Frontend: `src/pages/Register.tsx`, `src/pages/OrganizationPending.tsx`,
  `apiRegister`/`RegisterResponse`, approve/reject/pending UI and
  `apiApproveOrganization`

Database (one new migration):

- Table `pending_registrations` (dropped; any unexpired registration codes in
  it are discarded by design)
- Enum value `pending` removed from `organization_status` (type rebuilt);
  existing `pending` organizations (count checked at migration time; 0 in the
  dev database) are converted to `active` first
- Downgrade recreates the empty table and the old enum type (no data restore)

Dependencies: none added or removed (report-only rule respected; vulture was
not installed and was not installed for this task).

## Test coverage after the cleanup

- `tests/test_auth.py` (13 tests): the lockout flow end to end -- 3rd
  wrong password trips it, correct password refused until verified,
  wrong code, expiry, resend rotation, single use, capped verify
  attempts -- plus byte-identical known/unknown-email responses on
  verify and resend, register 404, and the authz regression tests.
- `tests/test_org_lifecycle.py` (4 tests): platform admin creates an
  active org + owner invitation; owner accepts and reaches the
  dashboard; module denial; managed->in_house switch and full
  soc_analyst access; owner-invitation list/resend (token rotation,
  expired reads as expired)/revoke (link 404s); suspended/archived
  login and endpoint behavior.
- `tests/test_anonymous_routes.py` (3 tests): enumerates every route,
  walks the FULL dependency tree, and fails on any anonymous endpoint
  outside the allowed list; pins that no anonymous route can create an
  account or organization.
- `tests/test_super_admin.py` (6 tests): the bootstrap transaction
  (admins + account_emails + system audit row in one), duplicate-email
  refusal, second-super-admin refusal, password never printed, and the
  non-interactive SEED_SUPER_ADMIN_* path -- which exposed a real bug
  (the env-var branch never assigned the password;
  `UnboundLocalError`) that is fixed here.
- `tests/test_migration_invite_only.py` (1 test): d5e6f7a8b9c0 on a
  scratch database -- empty upgrade (enum + table state), downgrade -1
  (structures recreated), populated upgrade (pending org converted,
  registration row discarded). It exposed a downgrade FK-name mismatch
  in the recreated table (now carries the original
  `fk_pending_registrations_organization` name) and a missing role on
  the seed row.
- `tests/test_scope.py` / `test_admin_organizations.py` /
  `test_organization_owner.py` / `test_assets.py`: legacy
  `/organizations` tests re-pointed at `/admin/organizations` or
  rewritten to pin the router's removal; `organization_pending`
  coverage replaced with suspended/archived equivalents.

Full suite: 135 passed. Frontend gates after the cleanup: `tsc -b`
clean, oxlint 0 errors (26 pre-existing-style warnings), `npm run build`
ok.

## Dev launcher first-run path

`scripts/dev.mjs` checks for an active super_admin after migrations
(inline Python probe; a broken probe only skips the offer, never blocks
the dev flow). On a first run it offers to run
`python -m app.create_super_admin` interactively (stdio inherited so
getpass works) or prints the exact command for later; once a super_admin
exists, every run is completely silent.
