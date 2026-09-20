# SentinelX

AI-Assisted Security Operations & Incident Response Platform — MCA Sem 3 project (LJ University).

**Team:** Ansh Patel, Riteka Singh, Aanchal Rai

**Stack:** React + TypeScript (frontend) · FastAPI + SQLAlchemy (backend) · PostgreSQL (database)

---

## 1. Frontend setup

```
npm install
npm run dev
```
This starts the UI at `http://localhost:5173`.

---

## 2. Database setup (do this once per laptop)

You do **not** need Docker for this. We're installing PostgreSQL directly on your computer using its normal installer, the same way you'd install any other program.

### Step 1 — Install PostgreSQL

1. Go to **https://www.postgresql.org/download/windows/**
2. Click **Download the installer** — it opens a page on enterprisedb.com.
3. Download the latest version for Windows x86-64 (the top one on the list is fine).
4. Run the downloaded `.exe` file and click **Next** through the setup wizard, keeping everything on default settings, **except**:
   - When it asks for a **password** for the `postgres` superuser — type something you'll remember, e.g. `Postgres@123`, and **write it down somewhere**. You'll need it once in Step 2.
   - Keep the **port** as `5432` (default).
5. Keep clicking **Next** until it installs. This also installs **pgAdmin** — a visual tool for managing the database — you don't need to install anything separately for that.
6. When it finishes, untick "Stack Builder" if it asks (you don't need it) and click **Finish**.

### Step 2 — Create the project's database user and database (using pgAdmin)

1. Open **pgAdmin 4** from your Start Menu (it was installed in Step 1).
2. The first time it opens, it may ask you to set a **master password** for pgAdmin itself — this is separate from the postgres password, set anything you like and remember it.
3. In the left sidebar, expand **Servers → PostgreSQL 17** (or whatever version you installed). It will ask for the password you set in Step 1 — enter it and tick "Save Password".
4. Right-click **Login/Group Roles** → **Create** → **Login/Group Role...**
   - **General tab** → Name: `sentinelx`
   - **Definition tab** → Password: `sentinelx_dev_pw`
   - **Privileges tab** → turn ON "Can login?"
   - Click **Save**.
5. Right-click **Databases** → **Create** → **Database...**
   - Database: `sentinelx`
   - Owner: `sentinelx` (select it from the dropdown)
   - Click **Save**.

That's it — you now have a database called `sentinelx` on your own laptop, with a user called `sentinelx` that can access it. Nobody else can see this database; it only exists on your machine.

### Step 3 — Set up the backend to connect to it

1. Open the project folder in VS Code, then open a terminal (`` Ctrl+` ``).
2. Go into the backend folder:
   ```
   cd backend
   ```
3. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```
4. Create a new file inside the `backend` folder named exactly **`.env`** (right-click `backend` in VS Code's Explorer → New File → type `.env`). Paste this single line into it and save:
   ```
   DATABASE_URL=postgresql+asyncpg://sentinelx:sentinelx_dev_pw@localhost:5432/sentinelx
   ```
   (This is the address, username, and password your Python code uses to reach the database you just created in pgAdmin.)

### Step 4 — Create the tables

Still inside the `backend` folder in your terminal, run:
```
alembic upgrade head
```
This reads the schema that's already defined in the project (in `backend/migrations/versions/`) and creates all the tables in your new `sentinelx` database. You should **not** run `alembic revision --autogenerate` — that step was already done once and its result is already saved in the project; you're just applying it.

### Step 5 — Check it worked

Go back to pgAdmin → expand **Databases → sentinelx → Schemas → public → Tables**. As of the admins/users-split migration, you should see over 40 tables listed -- `organizations`, `admins`, `users`, `assets`, the full alert/incident/ticket pipeline (`security_events`, `alerts`, `incidents`, `tickets`, ...), and `alembic_version`. Right-click any table → **View/Edit Data → All Rows** to see it (they'll be empty for now — that's expected).

---

## 3. Running the backend API (optional, once database setup is done)

From inside `backend`:
```
uvicorn app.main:app --reload --port 8000
```
Then open `http://localhost:8000/api/v1/health` in a browser. If it shows `{"status":"ok","db":true}`, your backend is successfully talking to your database.

---

## 4. Troubleshooting

**"Could not open requirements file"** — you're in the wrong folder. Run `cd backend` first, then try again.

**"getaddrinfo failed" when running alembic** — your `.env` file is missing, misspelled (check it's not `.env.example`), or has the wrong text. Re-check Step 3.4 above.

**"psql is not recognized"** — that's fine, you don't have the PostgreSQL command-line tool on your PATH and you don't need it; use pgAdmin instead (Step 5) to look at your data.

**pgAdmin asks for a password you don't remember** — that's the `postgres` superuser password you set during installation in Step 1, not the `sentinelx` one you created in Step 2.

**Nothing shows up under "Databases" in pgAdmin** — make sure you're looking under the right server (there's usually only one, named "PostgreSQL 17" or similar) and that Step 2 actually completed (check for an error message when you clicked Save).

If you get stuck, take a screenshot of the exact error and send it — don't guess or skip steps.

---

## 5. Notes

- Each teammate has their **own separate local database** — this is intentional. Nobody's test data is shared, and nothing about the database ever gets committed to GitHub (`.env` and any local data are excluded via `.gitignore`).
- If you later add or change a table (a SQLAlchemy model in `backend/app/models.py`), only the person making that change runs `alembic revision --autogenerate -m "..."` and commits the resulting file in `backend/migrations/versions/`. Everyone else just runs `alembic upgrade head` after pulling to catch up — never `--autogenerate` on someone else's change.
- **Pulling the admins/users split migration** (`f2a3b4c5d6e7_admins_users_split_and_pipeline_tables.py`): just run `alembic upgrade head` like any other migration, from `backend`. It splits the old single `users` table into `admins` (super_admin/organization_admin) and a narrower `users` (soc_analyst/security_manager/it_developer/auditor), and adds the full event → alert → incident → ticket → remediation → verification pipeline schema. If you already had test accounts in your local `users` table, any super_admin/organization_admin rows are moved into `admins` automatically as part of the upgrade -- you don't need to re-register. As always, this migration was written by hand, not with `--autogenerate` -- don't run `alembic revision --autogenerate` against it or any other migration in this project.
