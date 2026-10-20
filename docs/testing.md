# Testing

## Backend (pytest)

One-time setup, per developer machine:

```
createdb sentinelx_test
```

(or set `TEST_DATABASE_URL` to any Postgres database you're fine with
having every table created and dropped in -- never point this at your
real dev database).

Run the suite from `backend/`:

```
cd backend
pytest
```

### How the fixtures work (`backend/tests/conftest.py`)

- `db_session` — creates every table (via `Base.metadata.create_all`,
  driven straight off `app/models.py`, the same source of truth the real
  app uses) at the start of each test, yields an `AsyncSession`, then
  drops everything at the end. Each test gets a clean schema; there's no
  shared state between tests.
- `client` — an `httpx.AsyncClient` wired directly to the FastAPI app in
  memory (`ASGITransport`, no real server/port), with `get_db` overridden
  to hand out the `db_session` above instead of the real database
  connection. Use this for anything that should go through actual
  endpoints (status codes, auth checks, response shapes).

### Adding a new test file

Follow `backend/tests/test_auth.py`'s pattern: `async def test_...(client)`
(or `(client, db_session)` if you need to inspect/seed rows directly —
e.g. reading a verification code that would otherwise only go out by
email). `pytest.ini` sets `asyncio_mode = auto`, so `async def` test
functions run without needing an explicit `@pytest.mark.asyncio` on each
one.

When you add a new router (see `docs/architecture.md`), add a
`test_<resource>.py` alongside it, and at minimum a test that an
endpoint requiring auth actually rejects an unauthenticated request —
that's what caught (and now guards) `/organizations` and
`/stats/overview` previously being open.

If the new endpoint reads or writes organization-scoped data, it must
depend on `org_scope`/`require_admin`/`require_roles` from
`app/scope.py` and filter its query with `scoped_to_org(...)` — then add
its tenant-isolation case to `backend/tests/test_scope.py` (seed two
organizations, assert org A's token never sees org B's rows, assert a
super_admin sees both). That file also has the pattern for unit-testing
a role guard directly (call `require_admin`/`require_roles(...)` with a
hand-built `Scope`, no HTTP or database needed) — reuse it instead of
inventing a new way to test guards.

### Detection engine tests (`test_detection_*.py`)

The rule engine is covered at two levels, and both matter when you
touch it:

- `test_detection_evaluators.py` — the pure evaluator functions with
  no DB and no Redis (invented event dicts, explicit window
  boundaries). Every built-in rule needs at least one positive and one
  negative case here, plus the window edge cases: an event exactly at
  the boundary counts (left edge is inclusive), out-of-order arrival
  still counts, and two users' interleaved events stay separate
  groups.
- `test_detection_engine.py` — end-to-end through the real
  `process_events` job with the API and an in-memory window store:
  seeding idempotence, the simulator scenarios (brute force hits,
  benign noise zero hits), disabled rules never firing, and
  organization isolation. The seeding test must pass the TEST session
  factory (`tests.conftest.TestSessionLocal`) — passing `None` would
  make it fall back to the real app database.
-  `test_alerts.py` — the P10 pipeline over the same harness: dedup
  (one batch = three alerts, replay folds nothing, a later batch in a
  fresh bucket creates new alerts), the done-when correlation (the
  brute-force scenario yields EXACTLY ONE correlated alert alongside
  the three detection ones, idempotent on rerun, zero on benign noise),
  every status transition (valid moves, 409s, dismiss-requires-reason,
  reopen only from dismissed), the full routing matrix (managed vs
  in-house × owner/security_manager/soc_analyst/auditor + assigned and
  unassigned platform SOC + super_admin), cross-organization isolation
  (404, never a leak), the list filters (status, severity, rule_id,
  asset_id, assigned_to_me, cursor pagination), assignment scope
  rules, and the history+audit rows written on every change.

## Frontend

No automated test runner is configured yet. The current gates are:

```
npx tsc -b        # type-check
npm run build     # type-check + production bundle
npm run lint      # oxlint
```

All three should be run and pass before merging a frontend change of any
size. If you're working from a Linux sandbox bridged to a Windows
checkout, `tsc -b` runs fine there, but `npm run build`'s bundler step
and `npm run lint` need native bindings that won't match across
platforms -- verify those two on the actual development machine.

## AI triage + incident agent (evaluation harness)

Run from `backend/` with the project venv (the settings file is
resolved from the working directory, so `backend/` is where it starts;
see docs/DECISIONS.md's provider note):

```
cd backend
PYTHONPATH=.. .venv/Scripts/python -m tools.ai_eval.runner --provider fake            # metrics: 8 labelled cases, deterministic
PYTHONPATH=.. .venv/Scripts/python -m tools.ai_eval.runner --provider fake --demo     # DONE-WHEN walkthrough against the dev DB
PYTHONPATH=.. .venv/Scripts/python -m tools.ai_eval.runner --provider real            # needs OPENAI_API_KEY; calls WILL hit the network
```

Latest run (2026-10-20, provider = FakeProvider, seed 7, 8 cases):

```
cases: 8
true_positives: 7
false_positives: 0
true_negatives: 1
false_negatives: 0
precision: 1.0
recall: 1.0
false_positive_rate: 0.0
avg_estimated_cost_usd: 0.000232
failures: none
```

The fake provider is deterministic and injection-deaf (see
`docs/DECISIONS.md`), so these numbers are stable across machines and
runs -- the reproducibility gate the AI SOC Analyst brief asks for.
(The avg cost estimate moved 0.000153 -> 0.000232 on 2026-10-20 when
the fake provider started billing the WHOLE prompt -- system + user --
instead of only the user text; production billing counts every token.)

### The DONE-WHEN walkthrough (`--demo`)

`--demo` walks the whole acceptance path through the REAL HTTP surface
(the app served via ASGI transport, same shape as the pytest client)
against a throwaway organization in the DEV database:

1. a simulated brute-force alert (+2 supporting events) is triaged by
   the real service entry point the worker uses;
2. the analysis is cited (grounded event ids), `source="ai"`;
3. the analyst accepts via `POST /ai-analyses/{id}/decision`;
4. an incident is created FROM THE ALERT (`POST /incidents/from-alerts`) --
   the alert becomes TRIAGED;
5. the incident agent drafts title/summary/timeline/ticket;
6. the analyst reviews the draft and creates the ticket through the
   normal ticket API (draft-only rule: the agent itself never creates);
7. `GET /ai/metrics` shows 2 AI analyses, 1 decision, 1 accepted,
   acceptance_rate 1.0, average_confidence 0.8, spend > $0.

The throwaway org is deleted afterwards (cleanup runs in a `finally`,
so a failed step leaves nothing behind). The same flow is pinned as a
pytest: `backend/tests/test_ai_done_flow.py`.

Latest walkthrough (2026-10-20, provider = FakeProvider): every step
passed; metrics as above; total demo spend $0.000515 (est.), ticket
TICK-1/P2 attached to the incident.

### Real-provider evaluation: INCOMPLETE (no key available)

The brief asks for ONE real-provider (OpenAI) harness run. **Not yet
run**: no `OPENAI_API_KEY` was available when this milestone closed.
The harness command above is ready; when a key is configured, run
`--provider real`, replace the metrics table in this section with the
real run's output, and note the provider + date. Expectations stay the
same bands on the fake provider in the meantime.

### Incident-agent safety properties (pinned tests)

`backend/tests/test_ai_incident_agent.py` pins, on fake/scripted
providers only:

- injection strings inside event content stay inert inside the
  untrusted data block (one delimiter, every line `DATA |-prefixed);
- a payload whose structure was changed by data-content instructions
  fails the parser (nothing executes, nothing is created);
- invented evidence citations -> grounding failure -> the stored
  analysis is the deterministic rules draft, never the model's
  hallucinated ids;
- runs are organization-isolated (org A's run never touches org B's
  rows, and B's incident is untouched);
- the daily/monthly cost cap stops runs before any provider call;
- the model path NEVER creates incidents, tickets or timeline rows
  (draft-only, confirmed by row counts before/after);
- decisions persist (accepted/edited/rejected + reason) and feed
  `GET /ai/metrics`; a cross-org caller gets a 404, never an
  unauthorized-view that reveals existence.
