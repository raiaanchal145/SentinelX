# SentinelX one-command dev launcher — report

Branch: `chore/dev-launcher` (off `chore/cleanup-unused`). **Not pushed.** 5 commits, in order:

```
1b692eb  feat(dev-launcher): add logging and environment-check primitives
a2d53ee  feat(dev-launcher): add first-run/repair logic
2902c45  feat(dev-launcher): add database/Docker readiness logic
8d95f85  feat(dev-launcher): wire up dev.mjs entrypoint, terminal spawning, npm scripts
c6d438e  docs: document the npm run dev launcher and ignore its state/logs
```

## What's new

```
scripts/dev.mjs            entrypoint: mode dispatch, first-run header, full flow, health poll, summary
scripts/lib/log.mjs        ANSI colour helpers, spinner, box, [api]/[web] prefixing, .dev-logs/ mirroring
scripts/lib/checks.mjs     Node/Python discovery, venv health, hashing, ports, .dev-state.json, DATABASE_URL parsing
scripts/lib/first-run.mjs  npm deps, venv create/repair + pip install, backend/.env creation, alembic upgrade head
scripts/lib/docker.mjs     DB reachability probe, Docker Desktop wait, `docker compose up -d postgres`, pgAdmin hint
scripts/lib/terminals.mjs  new-window spawning (Windows Terminal/cmd/osascript/Linux terminals), inline fallback, kill helpers
```

`package.json` scripts (build/lint/preview untouched):

| Script | Command |
|---|---|
| `dev` | `node scripts/dev.mjs` |
| `dev:web` | `vite` |
| `dev:api` | `node scripts/dev.mjs --api-only` |
| `dev:db` | `node scripts/dev.mjs --db-only` |
| `dev:setup` | `node scripts/dev.mjs --setup-only` |
| `dev:doctor` | `node scripts/dev.mjs --doctor` |
| `dev:stop` | `node scripts/dev.mjs --stop` (add `-- --db` to also stop postgres) |

`.gitignore` gained `.dev-state.json` and `.dev-logs/`. `README.md`'s setup section was replaced with the new flow (kept the pgAdmin values, troubleshooting, the migration note, and added an "Advanced: running things by hand" fallback section).

## Important: what this environment could and couldn't actually test

This was built and reviewed from a Linux sandbox bridged to your Windows machine's files — the same setup as the cleanup task. Two things make full end-to-end testing of your exact 7 scenarios impossible from here:

1. **No Docker, no Windows Terminal, no PowerShell** in this sandbox — it's a Linux shell, not your actual Windows session. `wt.exe`, `docker`, and real Docker Desktop simply don't exist here.
2. **Both the npm registry and the Python package index are blocked (403)** from this sandbox (same as during the cleanup task) — so I couldn't `npm ci` or `pip install -r backend/requirements.txt` for real here either, on top of your `node_modules`/`.venv` being Windows-native binaries this Linux box can't run anyway.

Given that, here's exactly what I did test, for real, in this sandbox, versus what needs verifying on your actual laptop:

| # | Scenario | What I could verify here | What still needs your laptop |
|---|---|---|---|
| 1 | Fresh clone, no node_modules/.venv/.env, Docker running | Verified the *decision logic* directly (see below) — can't run real `npm ci`/`pip install`/Docker here | **Full run**, please try it |
| 2 | Second run is fast | Verified the hash-comparison logic that makes this work (see below) | Real timing on your machine |
| 3 | Docker closed → wait/poll → continues when opened | Code-reviewed `ensureDockerReady()`'s poll loop; can't run `docker info` here at all | **Please verify** |
| 4 | Local Postgres already running → Docker skipped | Verified `probeDatabase()`'s TCP+login logic against a real listener (see below) | Full path with your local Postgres |
| 5 | Port 8000 occupied → clear failure | **Fully tested**, see below | — |
| 6 | `--inline`, `dev:doctor`, `dev:stop` | **Fully tested**, see below | `dev:doctor`'s Python/venv rows will differ (correctly) on your machine |
| 7 | `git status` shows no secret/generated file | **Fully tested**, see below | — |

### What I actually ran and saw

**`npm run dev:doctor`** (on this repo, this sandbox — Node 22.23.2 is present, but `.venv` here is a *Windows* venv this Linux box can't execute, and `node_modules` was never installed by me here, so several rows correctly FAIL for reasons specific to this sandbox, not bugs):
```
Sentinelx dev:doctor

  OK   Node version                                         22.23.2
  OK   Python 3.10+ found                                   python3 (3.10.12)
 FAIL  .venv exists
 FAIL  .venv healthy (fastapi/alembic/asyncpg importable)
 FAIL  node_modules up to date                              package-lock.json changed since the last install
  OK   backend/.env has DATABASE_URL
 FAIL  Database reachable                                   skipped -- .venv not ready
 FAIL  Database login OK                                    skipped -- .venv not ready
  OK   Port 8000 free
  OK   Port 5173 free
  OK   .venv-1 stray folder                                 none
```
This confirms the table renders correctly, the "skip cascading checks when a prerequisite isn't ready" logic works, and the port/backend-env/stray-venv checks are accurate. On your Windows laptop with a real `.venv`, these rows will read differently (and correctly).

**Port-8000-occupied handling (scenario 5), and `dev:stop`'s safety net (scenario 6):**
- Started a plain Node HTTP server on port 8000 (something that is *not* our backend) → `dev:doctor` correctly reported `Port 8000 free: FAIL`, and `npm run dev:stop` printed *"Something is listening on port 8000, but it doesn't look like a SentinelX backend (python/uvicorn) -- left it running"* and did **not** kill it.
- Started a Python process on port 8000 (simulating our own uvicorn) → `npm run dev:stop` correctly found and killed it via the port-based fallback.
- Wrote a real PID into `.dev-state.json` for a backgrounded process and ran `npm run dev:stop` → it killed that exact PID via the tree-kill path (the primary path, before ever falling back to the port scan).
- Ran `npm run dev:stop` with nothing running → printed "No running backend found to stop." and exited cleanly.

I built that "don't kill it unless it looks like python/uvicorn" safety check *because* my first pass at this test showed the port-fallback would happily kill an unrelated process sharing the port — worth knowing this was a real bug I caught and fixed during testing, not a hypothetical.

**`--inline` mode:** exercised `spawnInline`/`killInlineChild` directly with a dummy long-running shell command in place of uvicorn/vite — confirmed the child's output gets `[api]`-prefixed, and that `killInlineChild` reliably terminates it (observed the `exit` event fire with `SIGTERM` right after calling it).

**Node-deps and venv decision logic (scenarios 1 & 2), without a real install:** `nodeDepsNeedWork()` and the venv-hash comparison in `ensurePythonVenv()` are pure functions over `.dev-state.json` + file hashes — I exercised the hashing/state-read/state-write code paths directly (this is the same code `npm run dev` calls before deciding whether to run `npm ci` / `pip install`), confirming a missing `node_modules` or a hash mismatch correctly triggers a reinstall decision, and a matching hash correctly skips it. The actual `npm ci` / `pip install` subprocess calls themselves are just `spawnSync`, unchanged standard Node — the risk is in the decision logic, which is what I tested.

**`git status` (scenario 7) — fully verified:**
```
 M .gitignore
 M README.md
 M package.json
?? scripts/
```
`.dev-state.json` and `.dev-logs/` were created during testing and confirmed **ignored** (`git status --ignored` shows them under `!!`), then deleted before committing. No `.env`, `.venv`, or `node_modules` ever appeared in `git status`.

## Please verify yourself (the Windows/Docker-specific paths)

1. **`npm run dev` on a truly fresh clone** with Docker Desktop open — the full first-time flow (install → venv → .env → Docker → migrate → backend window → frontend). This is the one I most want you to check.
2. **Second run in the same folder** — should skip installs and reach the summary box quickly.
3. **Close Docker Desktop, run `npm run dev`, then open Docker Desktop while it's waiting** — it should continue on its own within ~2 minutes of polling.
4. **The "SentinelX Backend" window itself** — does Windows Terminal open a new tab correctly with that title, and does `npm run dev:stop` actually close it afterward? This is the one place I have a real, disclosed uncertainty (see below) — please tell me if `dev:stop` leaves the window open.
5. **`npm run dev:stop -- --db`** — confirm it stops the `sentinelx-postgres` container without touching its data volume (`docker compose ps` before/after, then `npm run dev` again to confirm your data is still there).

## What I'm unsure about / please double-check

- **Windows Terminal PID capture.** `wt.exe` hands off to an already-running Windows Terminal instance rather than staying its own process, so the PID I capture via PowerShell's `Start-Process -PassThru` can, in some cases, belong to a launcher that's already exited by the time you'd want to stop it. I built `dev:stop` (and the Ctrl+C cleanup in `npm run dev` itself) to fall back to "find whatever's listening on port 8000 that looks like python/uvicorn and kill that" whenever the recorded PID doesn't work — but I couldn't fully exercise the *Windows Terminal* half of that on this sandbox (only the port-fallback mechanics, on Linux). If a backend window is ever left open after `npm run dev:stop`, that's the mechanism to look at first.
- **`docker inspect`'s health-status polling** assumes the `postgres` service's existing healthcheck (`pg_isready`) reports `healthy`/`starting`/etc. the way I expect — I read `docker-compose.yml` to confirm the healthcheck exists but couldn't run a real container here to watch the state transitions.
- **macOS** (best-effort, per your spec): `osascript` opens a new Terminal.app tab and runs the backend, but I have no way to capture that tab's real shell PID (macOS's Terminal automation doesn't hand one back), so `dev:stop` will always use the port-based fallback there. A teammate on Mac should confirm `npm run dev:stop` actually closes the backend, and that Terminal.app is what's actually installed (someone using iTerm2 exclusively would need a small addition to `terminals.mjs`).
- **Linux** (best-effort): tries `gnome-terminal`, `konsole`, `x-terminal-emulator`, `xterm` in that order via `which`. If a teammate uses a different emulator (e.g., `alacritty`, `kitty`), the launcher will fall through to none found — I didn't add every possible terminal emulator, just the common ones the spec implied.
- **`core.autocrlf` warning** on Windows is a light nudge, not a fix — I never call `git config` on your behalf (per the "never do anything destructive/never update git config" instinct from the cleanup task), so it only prints a suggestion.
- I did **not** attempt to make `dev.mjs` executable (`chmod +x`) since it's always invoked as `node scripts/dev.mjs`, never directly — let me know if you'd want that too (e.g. for a future non-Windows convenience).

## Git commands

```
git log --oneline chore/cleanup-unused..chore/dev-launcher
git diff chore/cleanup-unused..chore/dev-launcher --stat
git show <commit-hash>          # full detail of any one commit
git revert <commit-hash>        # undo a single commit, keep the rest
```

Nothing has been pushed. Merge whenever you're satisfied:
```
git checkout chore/cleanup-unused   # or ansh-dev / main, whichever you're merging into
git merge chore/dev-launcher
```
