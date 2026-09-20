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
