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

## SentinelX is invite-only (R1)

There is no public registration and no organization self-signup.
Accounts come from exactly three places: (a) the platform admin
creates an organization and enters the owner's email -- the owner gets
an invitation link, sets a password and lands on the organization
dashboard; (b) an owner invites members by email (SOC analysts only
while `soc_mode = in_house`); (c) the platform admin invites platform
SOC analysts. The first `super_admin` is created by the one-time
server-side command `python -m app.create_super_admin` -- never
through a public page or endpoint. Email ownership is proven by the
invitation link itself, so invited users do not do an OTP step at
signup.

Deleted with self-signup (all confirmed by the usage matrix in
docs/reports/invite-only-cleanup.md): `POST /auth/register` and its
schemas, the `PendingRegistration` model and `pending_registrations`
table (dropped by migration `d5e6f7a8b9c0`; unexpired registration
codes it held were discarded -- no flow can ever consume them, and the
emails they reserved are freed), the registration branch of
`verify-email`/`resend-verification`, the `SUPER_ADMIN_EMAILS`
allow-list, `POST /admin/organizations/{id}/approve`, the `pending`
value of `organization_status` (historical rows converted to `active`
before the enum was rebuilt), the legacy `GET/POST /organizations`
router, and the frontend `Register.tsx` / `OrganizationPending.tsx`
pages with their routes and API wrappers. `verify-email` and
`resend-verification` remain for exactly one flow: the 3-wrong-passwords
lockout.

## The `pending` enum value was removed, not just orphaned

Postgres cannot `DROP VALUE` from an enum, so migration `d5e6f7a8b9c0`
rebuilt the type (rename old, create new without `pending`, alter
column, drop old), converting any `pending` organizations to `active`
first and logging the count. `downgrade -1` recreates the full
four-value enum and the empty `pending_registrations` table -- data is
not restored. The recreated table's FK carries the original name
(`fk_pending_registrations_organization`) because the older
`f2a3b4c5d6e7` migration's own downgrade drops it by name; an
auto-generated name would break downgrade chains through that
revision. The empty+populated+downgrade paths are pinned by
`backend/tests/test_migration_invite_only.py` on a scratch database.

## `organizations.approved_by_admin_id`/`approved_at` are kept

With the approve flow gone these could look dead, but
`POST /admin/organizations` sets both at creation -- they are the
record of which super_admin created the organization and when. Renaming
them (e.g. to `created_by_admin_id`/`created_at`) would be pure churn
against the FK name the migrations and the test-schema `use_alter`
notes depend on; `created_via` (`always "platform_admin"` now) is kept
for the same reason and documented here rather than dropped.

## Anonymous verify/resend answers are identical for known and unknown emails

The lockout surface is anonymous, so it follows the same rule as
login: unknown email, verified account, missing code, expired code and
wrong code all return the same generic 400 (`verify-email`) or the
same 200 body (`resend-verification`). This was *added* in R1 -- the
old registration-serving branch distinguished unknown emails, which
revealed account existence. Resend is throttled per email and verify
attempts are capped (5 per 10-minute window); codes stay single-use
with a 10-minute expiry. `test_auth.py` asserts the known-vs-unknown
responses are byte-identical, and `test_anonymous_routes.py` pins the
whole anonymous surface to the allowed list so a future anonymous
account-creation path fails the suite rather than a security review.

## Dev sharing: LAN by default, session-scoped, never a wildcard

Emailed links point at `FRONTEND_URL` (default `http://localhost:5173`),
so they only open on the machine running the dev server. The launcher
therefore LAN-shares **by default** (revised 2026-09-23 after the
original opt-in design confused the demo flow -- the team wants every
 emailed link to just work on a phone): plain `npm run dev` detects the
machine's LAN IP, serves Vite on all interfaces, and sets
`FRONTEND_URL`/`DEV_SHARE_ORIGINS` for that one run via `-- --no-share`
turns it off; `-- --tunnel` adds a public cloudflared quick tunnel for
devices outside the Wi-Fi. Nothing is written to any `.env` file and
localhost keeps working unchanged. The backend's CORS allow-list grows
by exactly the sharing origin; the parser refuses `*` and empty
entries, and a test pins that an unknown origin is still rejected while
sharing is active. cloudflared is an external CLI the launcher never
installs -- it prints the install command instead -- and the frontend's
API base follows the page origin (with Vite proxying `/api` to
loopback) so a phone hits the right backend without the backend ever
leaving localhost. Emails baked with a localhost URL before a share
session keep that URL forever; the launcher tells the user to resend.

## Background work: Arq over RQ, Redis in compose

The backend is async end to end (FastAPI + async SQLAlchemy + asyncpg),
so the worker runs **Arq** (async job functions share the app's session
factory) rather than RQ, whose sync jobs would need a second sync DB
engine or loop-wrangling. Arq also ships cron scheduling (the worker
heartbeat is config, not a hand-rolled loop) and graceful SIGTERM
drain. `redis:7-alpine` joins docker-compose with a **named volume**
(jobs in flight survive a restart, same pattern as pgdata) and a
healthcheck; `settings.redis_url` points at it, and the dev launcher
starts Redis, a worker terminal, and checks both in `dev:doctor`.
Dependencies added: `arq`, `redis` (the async redis-py client) --
nothing else.

## Event ingestion (P07): the timestamp bucket is whole seconds

The brief's dedup formula named a "timestamp bucket" without saying how
wide. Chose **truncation to whole seconds** (not minutes): collectors
that replay a batch replay identical timestamps, so second-truncation
deduplicates replays exactly, while two genuinely distinct events a
couple of seconds apart stay distinct -- a minute-wide bucket would
swallow real events. Anything differing only in sub-second precision is
deduplicated; document if a future collector emits real sub-second
distinct events.

## Parser output vs the declared event_type (merge rules)

When the worker's parser disagrees with the collector's declared
`event_type`, the resolution is (see `app/worker/parsers.py`'s
docstring): (1) parser-extracted **fields fill blanks** -- a value the
collector explicitly sent always wins over a parser guess; (2) if the
parser RECOGNIZES the raw content and derives a concrete classification,
its event_type wins (raw content is ground truth -- a collector that
mislabels "Failed password" as `auth_success` does not get to keep the
mislabel); (3) a recognized verb with no mapping in the fixed vocabulary
stores `other` with the raw record kept verbatim; (4) an unparseable
record keeps the declared type, which the API already guaranteed is in
the vocabulary. Parsers are pure functions and individually wrapped in
a catch-all so a parser bug degrades to "keep the declared type" and
never drops an event.

## Rate limit counts events, not requests

The per-key limit (600 events/minute default) is enforced so that a
batch of N costs exactly N: the request itself consumes one slot at
authentication time (via P06's `rate_limit_for_key` seam -- a flood of
garbage requests still burns slots), and the endpoint tops up the
remaining `accepted - 1` slots after validation, so rejected items cost
nothing and single-event requests cost exactly 1. Counting requests
would let a 500-event batch through at 1/500th of its real cost.

## Redis outages degrade, never block: the rate limit and the queue

Both pieces of ingestion infrastructure are optional to a request's
success. `enqueue_work` returning None (Redis down) still yields a 202
with an `X-Ingestion-Warning: queued=false` header -- the collector is
told to re-send. The rate limiter similarly degrades to "no limit" for
that request when Redis is unreachable (logged once). Ingestion is the
write path for every security event; a Redis blip must not 500 it. The
counter is deliberately short-expired (120s) so a crashed request never
leaks quota.

## Event sources are managed by organization_admin + security_manager

Minting ingestion API keys is security administration, not device
management. Reusing the `assets`-write module rule would let IT
developers mint keys for their team's assets, widening the key-minting
surface for no operational need; the dedicated role check keeps key
creation with the owner and security manager (the same audience as the
frontend page). soc_analyst and auditor get read-only lists. Keys are
SHA-256 hashed (format `sx_<prefix>_<secret>`, shown exactly once),
revocable, and record `last_used_at`; a rate-limit hook exists for P07
to implement.

## Rule hits are a table (rule_hits), not a queue message

A detection match needs queryable history: which rule, which group key,
WHICH contributing event ids, over which window -- and P10's alert
pipeline wants to read "recent hits for this organization" with
filters, not consume fire-and-forget messages. A Redis Streams/list
entry would force hits to be read exactly once and lose the window
context; a table is trivially auditable and re-readable, and the
worker already owns a Postgres session at evaluation time. Duplicates
are acceptable at this layer (an ongoing attack re-fires while the
window stays saturated); coalescing/deduplication into alerts is
P10's job, where `dedup_key` already exists on `alerts`.

## Detection evaluates inline at the end of process_events (no second queue hop)

A separate `evaluate_detections` job would buy nothing and cost two
things: ordering (arq makes no cross-job ordering guarantees, so two
batches could evaluate out of arrival order and split a threshold
across workers) and failure isolation that is already handled better
inline -- the events are committed before detection runs, so a
detection failure logs and rolls back only the hit writes, never the
events. Inline evaluation on the same batch keeps determinism (one
worker, batch order = arrival order) and makes the
simulator-scenario tests pin real end-to-end behavior.

## Detection sliding windows live in Redis; Redis down degrades to in-memory

Incremental evaluation needs each (organization, rule, group) window
kept between batches. Redis sorted sets (score = event epoch, member =
event JSON) give O(log n) sliding windows and -- because the
organization id is IN the key name -- structural cross-organization
isolation, the same stance as per-organization dedup hashes. When
Redis is unreachable the worker falls back to per-process in-memory
windows: a lost window can only DELAY a detection until real events
refill it, never fabricate one, and ingestion itself never blocks
(same degradation philosophy as the rate limit and the queue).

## Built-in rules seed by name with ON CONFLICT DO UPDATE, per-org settings survive

Built-in rules are platform data every environment should converge
on, so worker startup re-seeds the 8 rows (refreshing definition,
description, severity, MITRE id) against a partial unique index on
`name WHERE organization_id IS NULL`. An organization's
enable/disable choice deliberately lives in a SEPARATE table
(`organization_rule_settings`, one row per explicit override,
absence = use the default) rather than mutating the shared rule row:
the choice survives re-seeding and never leaks across organizations.
Custom rules (P24) may reuse a built-in's name, hence the partial
index.

## Detection rules are toggled by owner + security_manager (not soc-write)

Same call as event-source key minting: flipping a detection on or off
changes what an organization's SOC can and cannot see, which is
security administration, not analyst work. Reusing the `assets`-write
module rule would hand it_developers detection control over their own
assets' telemetry. The PATCH endpoint therefore guards on
organization_admin/security_manager (the event-sources pattern), is
audited as `detection_rule.enable`/`detection_rule.disable`, and
never touches the shared built-in row -- per-organization overrides
only.

## Alerting runs inline at the end of process_events, one transaction with the hits

P10 continues P23's shape: `create_alerts_for_hits` and
`run_correlations` run inside the same session/transaction that wrote
the batch's rule hits, committed together. A failure rolls back hits
AND alerts as one unit and the next batch re-evaluates and re-alerts
from the same events -- ingestion itself is never affected (events are
committed first). A separate queue job would reintroduce the ordering
problem P23 rejected and make "hits exist but their alert vanished"
a possible state.

## Alert dedup buckets on {rule, group key, floored window}, not "latest open alert"

The dedup key is `{rule_name}:{group_key}:{bucket}` where bucket =
`window_end` epoch floored to the rule's `dedup_window_seconds`. A
lookup-then-fold keyed on "the newest open alert for this rule+key"
would need row locking to be race-safe and has no deterministic
answer for which alert a hit belongs to after a quiet gap. A floored
bucket is stateless, race-safe via the partial unique index on
`(organization_id, dedup_key)`, and matches analyst intuition: one
alert per rule per entity per time slice. Folding (not updating by
conflict -- the fold extends windows, counts and links) happens in
Python inside the same transaction.

## Correlated alerts sit ALONGSIDE the underlying ones (no hiding)

When the correlation rule fires, the queue gains a fourth high-severity
alert; the three detection alerts it groups stay visible. Hiding or
collapsing the underlying alerts would break the SOC's ability to triage
the pieces independently (acknowledge/dismiss one, keep another) and
make the "exactly one correlated alert" property untestable from the
queue alone. `correlations` + `correlation_alerts` keep the grouping
queryable; the correlated alert shares the correlation's `dedup_key`
so the detail view can find the reasoning from either side.

## Alert status transitions live in ONE map, and history captures status_from explicitly

`ALERT_TRANSITIONS` in `app/routers/alerts.py` is the only definition
of what may move to what; every endpoint validates through it and the
unit tests pin the whole map. The endpoints capture the previous
status BEFORE mutating the row and pass it to the history writer --
reading `alert.status` after mutation would record status_from ==
status_to everywhere and silently make the timeline useless. Every
change writes one `alert_history` row (the per-alert story) plus one
`audit_logs` row (the platform-level record) in the same transaction.

## Correlation groups by USER, with the source IP only as a fallback

The built-in brute-force rule matches its three detection alerts on
the username they share (resolved per alert from the supporting
events' normalized view). An attacker's failed logins, the eventual
success and the privileged group change can come from different
source IPs (a distributed brute force, a VPN hop after takeover) --
keying the correlation on IP would miss exactly the attacks worth
correlating, while the account is the constant. The IP is still
resolved and stored on every alert (and only becomes the grouping
key for alerts whose events named no user). Assets correlate only
through the user acting on them. Also: a rule's
`dedup_window_seconds` column exists and the worker honors it, but
there is deliberately no API to change it yet -- tuning arrives with
per-organization custom rules (P24), so owners cannot silently widen
the dedup window of a built-in detection.

## Managed organizations: owner + security_manager keep READ oversight, writes stay platform-side

A managed org's alerts are worked by platform SOC staff -- that is
what "managed" means -- but the owner and security manager are
accountable for their organization's security posture, so they keep
read access to the queue and details (the security_manager's soc read
is not soc-mode-gated in access.py; the owner's oversight rule already
drops soc to read in managed mode). Writes return 403
`alert_write_not_allowed`: letting a managed org's own accounts
dismiss alerts would create two authorities over one queue. In-house
mode flips the table: the org's own soc_analyst (and owner/security
manager via the module matrix) work their own queue.

## SOC KPIs are computed client-side from the alert page (no summary endpoint)

The SOC workspace's KPI row (open, unacknowledged, median age, by
severity) and the platform queue's per-organization counts are
computed in the browser from the loaded `GET /alerts` page (limit 200)
instead of adding a `GET /alerts/summary` aggregate. Why: the queue
itself is the source of truth an analyst acts on, so the numbers can
drift at most by what pagination already caps; the endpoints stay
exactly as tested in P10; and median age is presentation, not a
domain fact. The cost is stated in the UI ("counts cover the most
recent 200 alerts in the selected window") so nobody mistakes the
cap for the whole queue. Revisit with a real aggregate endpoint only
if a queue outgrows one page in practice.

## One shared SOC component set, two placements

The in-house analyst's `/soc` pages and the platform analyst's
`/admin/soc-queue` render the SAME AlertTable/AlertFilters/AlertDrawer/
TriageQueue components rather than parallel copies. Scope differences
are data, not components: the backend's visibility matrix already
returns the right rows, the platform page passes an `orgName` resolver
(and so gets the Organization column), and `canWrite` follows soc_mode
-- a managed org's owner/security_manager get the drawer with no
action buttons at all, mirroring the backend's 403s instead of
offering actions that fail. Dependent work (incidents, AI, device
agents) appears only as clearly-labelled disabled placeholders, never
as silent absence.

## The incident lifecycle table and its naming quirks

- **State names.** The milestone brief says CONTAINED and
  PENDING_VERIFICATION; the pre-existing `IncidentStatus` enum (and the
  stored Postgres enum, uppercase via `values_callable`) says
  CONTAINMENT and VERIFICATION. The enum wins -- the lifecycle maps
  onto the members that already exist rather than widening a shared
  enum for cosmetics. The API contract documents the mapping.
- **Escalation starts at TRIAGED.** NEW cannot jump to ESCALATED:
  an incident must at least be triaged before it is escalated -- the
  request-for-escalation is a deliberate act on something understood,
  not a reflex on a fresh queue item.
- **One-step back everywhere.** INVESTIGATING -> TRIAGED,
  CONTAINMENT -> INVESTIGATING, REMEDIATION -> CONTAINMENT,
  VERIFICATION -> REMEDIATION are legal: real investigations step
  back a stage when a hypothesis fails, and forcing them through
  REOPENED would pollute the reopen metric.
- **FALSE_POSITIVE / DUPLICATE from every active state.** Anything
  before RESOLVED (including VERIFICATION, which can fail) may be
  closed out as FP/DUPLICATE; RESOLVED/CLOSED close via REOPENED
  instead. Both are terminal; REOPENED exists for RESOLVED/CLOSED.

## Alert status follows the incident -- including dismissal

Creation from an alert (or later linking) marks a NEW alert TRIAGED;
the incident reaching RESOLVED/CLOSED marks its linked alerts
CONVERTED; the incident closing as FALSE_POSITIVE/DUPLICATE DISMISSES
its linked alerts with the incident's closure reason (one
`alert_history` row each, `detail.via="incident_transition"`). Why:
an incident's verdict IS the verdict on its evidence -- leaving the
alerts open would rot the queue with rows nobody will ever work.

## IT developers get a shared-only window, not a wall

The brief says IT developers "only ever see shared entries." Rather
than a bare 403 on everything (which forces SOC to relay remediation
context by hand) or module-level access (which would expose internal
SOC notes), IT developers get read-only list/detail for their OWN
organization with internal timeline entries filtered out SERVER-SIDE
-- shared comments only, every write endpoint refused. The filter
lives in the detail endpoint, so the data never reaches an
unauthorized caller regardless of what a client renders.
