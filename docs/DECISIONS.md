# Decisions: Organizations, Access Control, Invitations

Ambiguities and non-obvious choices made while implementing the
organization-management/SOC-mode/invitations/layered-access-control
feature, recorded here so they're auditable and easy to revisit rather
than only living in code comments.

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
