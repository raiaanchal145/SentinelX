# SentinelX

AI-Assisted Security Operations & Incident Response Platform — MCA Sem 3 project (LJ University).

**Team:** Ansh Patel, Riteka Singh, Aanchal Rai

**Stack:** React + TypeScript (frontend) · FastAPI + SQLAlchemy (backend) · PostgreSQL (database)

---

## 1. First-time setup (once per laptop)

1. Install **Node.js 20.19+ or 22.12+** and **Python 3.10+** (make sure "Add python.exe to PATH" is checked during the Python installer on Windows).
2. Install **Docker Desktop** — <https://www.docker.com/products/docker-desktop/> — and open it once so it finishes its own setup. (If you'd rather install PostgreSQL directly instead of using Docker, that still works too — see "Using a local PostgreSQL install instead of Docker" below.)
3. Optionally install **pgAdmin 4** if you want a visual tool for browsing the database (Docker Desktop's Postgres works fine without it).
4. Clone the repo, open it in VS Code, then in a terminal at the project root run:
   ```
   npm run dev
   ```

That's it — the rest of this section explains what that command does; you don't need to type anything else by hand.

---

## 2. Everyday use: `npm run dev`

With Docker Desktop open, running this in the project root:
```
npm run dev
```
does everything automatically:

- installs Node dependencies if `node_modules` is missing or `package-lock.json` changed,
- creates/repairs the Python virtual environment at `.venv` and installs `backend/requirements.txt` if needed,
- creates `backend/.env` from `backend/.env.example` the first time (never touches it again after that),
- makes sure PostgreSQL is reachable — using an already-running local install if it finds one, otherwise starting just the `postgres` service via Docker Compose,
- applies any pending Alembic migrations,
- starts the FastAPI backend (`uvicorn app.main:app --reload --port 8000`) in a **new terminal window** titled "SentinelX Backend",
- starts the Vite frontend in the terminal you're already in.

The first run on a laptop takes a little while (installs + Docker image pull); every run after that is quick, since each step is skipped once it's already done. You never need to type `uvicorn`, `alembic`, `pip`, `docker compose`, or venv-activation commands by hand.

When it's ready, you'll see a summary with the frontend URL, the API URL, the API docs URL, and whether the database came from Docker or a local install.

Press **Ctrl+C** in that terminal to stop the frontend and the backend window this command started. It does **not** stop the Postgres container (so the next `npm run dev` is fast) — see `npm run dev:stop` below if you want to stop that too.

### Other commands

| Command | What it does |
|---|---|
| `npm run dev` | Everything above — the one command everybody uses day to day. |
| `npm run dev:web` | Frontend only (plain `vite`, what `npm run dev` used to do). |
| `npm run dev:api` | Backend only, in the current terminal (assumes the database is already up). |
| `npm run dev:db` | Only make sure PostgreSQL is running and migrated — starts no servers. |
| `npm run dev:setup` | Force the first-time setup steps again (reinstalls Node/Python packages even if nothing looks changed), then exits. |
| `npm run dev:doctor` | Runs every check and prints a PASS/FAIL table — starts nothing. Good first step when something's not working. |
| `npm run dev:stop` | Stops the backend `npm run dev` started. Add `-- --db` to also stop the Postgres container (`npm run dev:stop -- --db`). |

Add `--inline` (or set `SENTINELX_INLINE=1`) to `npm run dev` to run the backend as a plain child process printing `[api]`-prefixed lines in the same terminal, instead of opening a new window — useful if opening new terminal windows doesn't work in your setup.

### Registering the database in pgAdmin (one-time, manual)

pgAdmin can't be scripted, so `npm run dev` prints these values the first time it sets up the database — you only need to do this once:

- Host: `localhost`
- Port: `5432`
- Database: `sentinelx`
- Username: `sentinelx`
- Password: `sentinelx_dev_pw`

In pgAdmin: right-click **Servers → Register → Server...**, put any name on the **General** tab, then paste the values above into the **Connection** tab and **Save**.

### Using a local PostgreSQL install instead of Docker

If you'd rather install PostgreSQL directly on your machine (the original approach this project used before the launcher existed) instead of using Docker, that's still supported — `npm run dev` checks whether something is already listening on `localhost:5432` and answering as the `sentinelx` user *before* it touches Docker at all, and just uses it if so.

To set that up: install PostgreSQL from <https://www.postgresql.org/download/windows/>, then in pgAdmin create a login role named `sentinelx` with password `sentinelx_dev_pw` and a database named `sentinelx` owned by it (General/Definition/Privileges tabs → Create → Login/Group Role..., then Databases → Create → Database...). Once that exists, `npm run dev` will detect and use it automatically and skip starting any Docker container.

---

## 3. Troubleshooting

**Start here:** run `npm run dev:doctor` — it checks Node/Python versions, the virtual environment, installed packages, `backend/.env`, database reachability, and whether ports 8000/5173 are free, and prints a PASS/FAIL table without starting anything.

**Docker Desktop isn't open** — `npm run dev` will tell you to open it and wait, polling automatically for up to about two minutes; you don't need to restart the command once you open it.

**Port 8000 or 5173 is already in use by something else** — the launcher tells you which port and how to find the process (`netstat -ano | findstr :8000` on Windows, `lsof -i :8000` on macOS/Linux). If it's an old SentinelX backend from a previous `npm run dev` that didn't shut down cleanly, run `npm run dev:stop` first.

**Port 5432 is occupied by a local PostgreSQL that isn't set up for this project** — either stop that local PostgreSQL Windows service (Services app → the `postgresql-x64-...` service → Stop) so Docker can use the port, or set up the `sentinelx` user/database in it as described above.

**Migrations fail** — `npm run dev` prints the last lines of the real Alembic error and its best guess at the cause (unreachable database, wrong password, missing database, or multiple migration heads). Fix that specific thing and re-run `npm run dev`; migrations are idempotent, so re-running is always safe.

**"psql is not recognized"** — that's fine, you don't need the PostgreSQL command-line tool on your PATH; use pgAdmin instead, or just let `npm run dev`/`npm run dev:doctor` do the checking for you.

**Nothing shows up under "Databases" in pgAdmin** — make sure you registered the server with the values in the pgAdmin section above, and that `npm run dev` reported the database as ready.

If you get stuck, take a screenshot of the exact error and send it — don't guess or skip steps.

### Advanced: running things by hand

You shouldn't normally need any of this — `npm run dev` is meant to replace it — but if you want to run a step yourself:
```
docker compose up -d postgres        # start only the database container
cd backend
.venv\Scripts\python.exe -m alembic upgrade head      # apply migrations (Windows)
.venv/bin/python -m alembic upgrade head               # apply migrations (macOS/Linux)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000   # run the backend (Windows)
```
Never run `docker compose down -v`, `alembic revision --autogenerate` against someone else's migration, or `backend/reset_db.py` unless you specifically mean to wipe local data — none of these are things `npm run dev` will ever do for you.

---

## 4. Notes

- Each teammate has their **own separate local database** — this is intentional. Nobody's test data is shared, and nothing about the database ever gets committed to GitHub (`.env`, `.dev-state.json`, `.dev-logs/`, and any local data are excluded via `.gitignore`).
- If you later add or change a table (a SQLAlchemy model in `backend/app/models.py`), only the person making that change runs `alembic revision --autogenerate -m "..."` and commits the resulting file in `backend/migrations/versions/`. Everyone else just runs `npm run dev` (or `npm run dev:db`) after pulling to catch up — never `--autogenerate` on someone else's change.
- **Pulling the admins/users split migration** (`f2a3b4c5d6e7_admins_users_split_and_pipeline_tables.py`): just run `npm run dev` (or `npm run dev:db`) like any other migration. It splits the old single `users` table into `admins` (super_admin/organization_admin) and a narrower `users` (soc_analyst/security_manager/it_developer/auditor), and adds the full event → alert → incident → ticket → remediation → verification pipeline schema. If you already had test accounts in your local `users` table, any super_admin/organization_admin rows are moved into `admins` automatically as part of the upgrade -- you don't need to re-register. As always, this migration was written by hand, not with `--autogenerate` -- don't run `alembic revision --autogenerate` against it or any other migration in this project.
