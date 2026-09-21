# Decisions: Organizations, Access Control, Invitations, Assets

Ambiguities and non-obvious choices made while implementing the
organization-management/SOC-mode/invitations/layered-access-control and
asset-inventory features, recorded here so they're auditable and easy
to revisit rather than only living in code comments.

## Role default module read/write split

The spec's role-default-module table wasn't unambiguous about which
modules a role gets at "read" vs "write". Adopted a literal reading:
a module is "read" only where the spec explicitly wrote "(read)" next
to it for that role; every other module listed for that role is
"write". See `app/access.py`'s `ROLE_DEFAULT_MODULES` for the resulting
map and this same note in-line, so it's easy to correct if the literal
reading turns out to be wrong for a specific role/module.

## Owner's soc/incidents oversight rule is computed, not stored

The spec says the organization owner sees `soc`/`incidents` as
read-only oversight while `soc_mode = managed` (platform SOC staff do
the real work) and at full write while `soc_mode = in_house` (the
organization runs its own SOC). This is implemented as a runtime branch
in `get_effective_access()` rather than a static entry in a default-map
table, because it depends on the organization's *current* `soc_mode`,
which can change at any time -- a stored value would need to be kept in
sync on every soc-mode switch instead of just being computed fresh.

## `scoped_to_org` fails closed for `platform_soc_analyst`

`platform_soc_analyst` is a new admin_level whose `organization_id` is
always `NULL` -- the same shape as `super_admin`. The pre-existing
`scoped_to_org()` helper used to treat `organization_id is None` as
"this is a super_admin, don't filter" -- a real gap once a second
admin_level shares that shape. Fixed to check
`scope.role == AdminLevel.super_admin.value` specifically, so a
`platform_soc_analyst` hitting any endpoint that uses the generic
`scoped_to_org` helper gets **zero rows** rather than unrestricted
access. Their real visibility (assigned + `managed` + `active`
organizations) requires an async query the synchronous helper can't
perform, so it lives in its own function,
`access.soc_visible_organization_ids()` -- any future SOC-data endpoint
reachable by a `platform_soc_analyst` must call that explicitly rather
than relying on `scoped_to_org`.

## `is_active` is re-checked on every request, not just at login

`get_current_account` (`app/scope.py`) now 401s a deactivated account
on its very next request, even mid-session with an otherwise-valid
token. Previously `is_active` was only checked at login, so a token
issued before deactivation kept working until it expired on its own.
This closes a real, pre-existing gap the spec explicitly required
("deactivated users cannot log in and existing tokens stop working on
the next request").

## Teams use `users.team_id` (single team), not a many-to-many

`PUT /organization/teams/{id}/members` sets each user's single
`team_id` column rather than writing rows into a separate
many-to-many `team_members` table. This is a deliberate, documented
scope-limiting decision matching the level of detail in both the
backend spec and the (separately gated) frontend task's teams
requirements -- a person belongs to at most one team. Revisit if a
future requirement needs multi-team membership.

## Legacy `GET/POST /api/v1/organizations` were tightened, not removed

`admin_organizations.py` and `organization.py` now cover every
legitimate caller of "list organizations" (a platform admin) and "read
my organization" (an owner). The original `organizations.py` endpoints
had no remaining legitimate caller below `super_admin`, so they were
tightened to `require_super_admin` rather than deleted outright --
deleting them is unrequested destructive scope creep this task didn't
ask for, while leaving them at their old permission level would have
violated the "no anonymous endpoint may list organizations" requirement.
Kept only for whatever, if anything, still points at them.

## One Alembic migration, amended in place while still unexecuted

The spec calls for one new migration. Partway through, it became clear
`pending_registrations` needed a new `organization_industry` column to
carry the register form's optional industry field across the
register -> verify-email OTP gap (there was nowhere else to hold it
before the organization row exists). Rather than adding a second
migration, the not-yet-delivered, never-run-anywhere migration file was
amended in place to add that column. This is safe specifically because
the migration had not been executed against any real database yet --
amending an already-applied migration would be a different, much
riskier thing, and this repo's conventions explicitly forbid that.

## `pending_registrations.organization_industry` vs `organization_name`

Both are plain nullable string columns on `pending_registrations`,
carried across to the real `organizations` row created in
`verify-email`. Neither is validated beyond "non-empty" for
`organization_name` (checked in `register`) -- there is no
organization-name-uniqueness constraint, matching the rest of the
schema's existing looseness around free-text organization metadata
(`industry`, `environment`, `timezone` already had none).

## `docs/DATA_DICTIONARY.md` was not created as a new file

The original task referenced regenerating "the affected tables" in
`docs/DATA_DICTIONARY.md`. That file does not exist anywhere in this
repository (a similarly-named document exists only in the attached
claude.ai Project's own knowledge base, which is a separate thing and
not a repo file). Rather than inventing a brand-new, repo-wide data
dictionary file that would need to document every existing table to be
consistent with its own name -- well beyond what was asked -- the new
tables (`organization_modules`, `organization_role_access`,
`user_access_overrides`, `invitations`, `soc_organization_assignments`)
and the changed `organizations`/`admins`/`pending_registrations`
columns are documented instead in `docs/architecture.md`'s new
"Organizations, access control and invitations" section, alongside the
existing schema overview. `docs/API_CONTRACT.md` and this file
(`docs/DECISIONS.md`) were created fresh, as explicitly agreed.

## Migration correctness can't be a pytest test in this repo's fixtures

`backend/tests/conftest.py`'s `db_session` fixture builds the test
schema via `Base.metadata.create_all`/`drop_all` directly from
`app/models.py` -- it never runs `alembic upgrade`/`downgrade` at all,
for any migration, old or new. That means this migration's own
correctness (including the `platform_soc_analyst` enum-value
add-then-possibly-remove dance, and the backfill of
`organization_modules` for pre-existing organizations) is not, and
structurally cannot be, covered by the pytest suite as it exists today.
It needs a manual `alembic upgrade head` / `alembic downgrade -1`
run against a real Postgres database -- see the final manual checklist
for the exact commands.

## Assets: DELETE is soft-only; there is no hard-delete path at all

The brief said "DELETE: soft (status=retired); block hard delete when
events/incidents/tickets reference it." Rather than build a hard-delete
path guarded by three reference checks, `DELETE /assets/{id}` only ever
sets `status=retired` -- there is no code path in the assets router that
issues a SQL DELETE on an `assets` row, so there is nothing that could
orphan an event's, alert's, incident's or ticket's `asset_id`, now or
after those routers exist. Same observable behavior for the caller, one
less way to lose referenced history. Revisit only if a real "purge"
requirement shows up.

## Assets: it_developer's write is row-scoped, not module-scoped

The role map gives it_developer module-level `assets: write`, but the
spec's intent ("IT: own/team assets") is narrower than the module flag:
`_can_write_asset()` in `app/routers/assets.py` additionally requires
the caller to own the asset or sit on its team (organization_admin and
security_manager are unrestricted). The list endpoint stamps each row
with the caller's per-row `can_edit` so the UI can mirror the rule
without a second round-trip; the backend, not the flag, is the
authority on every write. As a corollary, an it_developer creating an
asset with no owner and no team gets themselves as the owner, so a
create never produces a row its own creator immediately can't edit.

## Assets: hostname is optional but unique per organization when set

An `application` or `cloud_resource` asset may have no hostname, so the
column is nullable; but when it IS set it's unique per organization,
case-insensitively -- enforced twice: an API check (`409
duplicate_hostname`) and a partial unique index
`(organization_id, lower(hostname)) WHERE hostname IS NOT NULL`
(migration `b8c9d0e1f2a3`) so a race can't sneak a duplicate past the
API check. Two assets with no hostname never collide.

## Assets: platform SOC reads via an explicit organization_id, 404 on what it can't see

A platform_soc_analyst has no organization of their own, so every
assets GET takes `?organization_id=` and checks it against
`soc_visible_organization_ids()`. An assigned-but-not-managed,
unassigned, or unknown id is a **404** `organization_not_found`, not a
403 -- a guessed id reveals nothing (same convention as the rest of the
org-scoped endpoints). super_admin is deliberately barred from this
router entirely and reads through
`GET /admin/organizations/{id}/assets` instead, matching every other
admin-side view of one organization's data.

## Assets: PATCH distinguishes "omitted" from "explicitly null"

`PATCH /assets/{id}` uses Pydantic's `model_fields_set`: a field the
client omitted is untouched, a field the client sent as `null` clears
the value (unassign an owner/team, blank a hostname). A plain
`is not None` chain can't tell those apart, and the edit dialog needs
both. `name` can never be cleared. Relatedly, a PATCH that results in
no actual change writes no `asset.update` audit row -- the audit log is
for state, not keystrokes.

## Assets: one shared frontend page, write controls from effective access

Every organization-side role renders the same
`src/features/assets/AssetsPage.tsx`; the role differences live in two
props/facts: module-level access (`read`/`write` from
`effective_modules`) deciding whether write controls render at all, and
the backend's per-row `can_edit` deciding whether a row shows edit/
retire. The UI only mirrors what the server already decided -- no
frontend role list to drift out of sync with `access.py`.

## The pytest fixture needed models.py changes the migrations didn't

The test schema is built with `Base.metadata.create_all` (never alembic,
see the earlier note on migration testing), and the
`organizations.approved_by_admin_id`/`created_by_admin_id` FKs back to
`admins` created a dependency cycle `create_all`/`drop_all` cannot sort
(`CircularDependencyError` on every fixture setup). The hand-written
migrations create these via ALTER TABLE with named constraints; the
models now name them identically and mark them `use_alter=True` so
metadata can order the DDL. No migration file was added or changed by
this -- it only makes the test schema match the real one. Separately,
the test engine now uses `NullPool`: pytest-asyncio runs each test on a
fresh event loop, and a pooled asyncpg connection created on one test's
loop is unusable on the next test's (failures that only appeared after
the first test in a session).

## Login's "Invalid email or password." stays deliberately generic

Asked directly whether a wrong email and a wrong password should get
distinct messages ("no account with that email" vs "wrong password").
Kept the single generic message (`app/routers/auth.py::login`) on
purpose: splitting it enables user enumeration -- an attacker probing
emails to learn which ones have accounts, before even attempting a
password, then focusing brute-force/credential-stuffing effort only on
confirmed accounts. This is a standard, well-known login anti-pattern
(OWASP calls it out explicitly), and avoiding it matters especially
here since SentinelX is itself a security-operations tool. The
existing lockout behavior (3 failed attempts on a real account force
re-verification -- see `login`'s `failed_login_attempts` handling)
already gives a legitimate user enough signal that something's wrong
without telling an attacker which half of their guess was right.
