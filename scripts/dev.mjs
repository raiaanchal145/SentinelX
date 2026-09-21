#!/usr/bin/env node
// SentinelX one-command developer launcher.
//
//   npm run dev          -- full flow: setup whatever is missing, ensure the
//                            database is up and migrated, start the backend
//                            in a new terminal window, start Vite here.
//   npm run dev:setup    -- force the first-time setup steps again, then exit.
//   npm run dev:doctor   -- run every check, print a PASS/FAIL table, start nothing.
//   npm run dev:db       -- only ensure Postgres is up and migrated.
//   npm run dev:api      -- backend only, in the current terminal.
//   npm run dev:stop     -- stop the backend this launcher started (add --db to also stop postgres).
//   --inline / SENTINELX_INLINE=1  -- run the backend as a child process here instead of a new window.
//
// Plain Node.js, ES module, built-ins only (child_process/fs/path/net/os/url/http)
// so this works even before `npm install` has ever been run.

import http from 'node:http';
import path from 'node:path';
import readline from 'node:readline/promises';
import { spawn, spawnSync } from 'node:child_process';
import * as log from './lib/log.mjs';
import {
  ROOT,
  IS_WIN,
  readState,
  writeState,
  checkNodeVersion,
  checkStrayVenv1,
  checkLineEndingConfig,
  isPortFree,
  findPython,
  venvExists,
  isVenvHealthy,
  venvPythonPath,
  findPidsOnPort,
} from './lib/checks.mjs';
import {
  LauncherError,
  nodeDepsNeedWork,
  ensureNodeDeps,
  ensurePythonVenv,
  ensureBackendEnv,
  readDatabaseUrl,
  runMigrations,
} from './lib/first-run.mjs';
import {
  probeDatabase,
  ensureDockerReady,
  startPostgresContainer,
  portOwnedByOurContainer,
  explainPortConflict,
  printPgAdminHintOnce,
} from './lib/docker.mjs';
import {
  openWindow,
  killPidTree,
  killByPort,
  spawnInline,
  killInlineChild,
} from './lib/terminals.mjs';

const BACKEND_PORT = 8000;
const FRONTEND_PORT = 5173;
const HEALTH_URL = `http://localhost:${BACKEND_PORT}/api/v1/health`;

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const INLINE = flag('--inline') || process.env.SENTINELX_INLINE === '1';

// ---------------------------------------------------------------------------
// Shared: pick "first-time" vs "quick start" framing.
// ---------------------------------------------------------------------------

function describeWhatsMissing(databaseUrlPresent) {
  const missing = [];
  if (nodeDepsNeedWork().needed) missing.push('install Node dependencies (npm ci)');
  if (!venvExists() || !isVenvHealthy()) missing.push('create/repair the Python virtual environment (.venv) and install backend packages');
  if (!databaseUrlPresent) missing.push('create backend/.env from backend/.env.example');
  missing.push('make sure PostgreSQL is running and migrations are applied');
  return missing;
}

function printRunHeader(databaseUrlPresent) {
  const missing = describeWhatsMissing(databaseUrlPresent);
  const firstTime = missing.length > 1; // more than just "run migrations"
  log.heading(firstTime ? 'First-time setup detected on this laptop' : 'Existing setup detected -- quick start');
  if (firstTime) {
    for (const step of missing) log.raw(`   - ${step}`);
  }
  console.log('');
}

function runWarnOnlyChecks() {
  const node = checkNodeVersion();
  if (!node.ok) log.warn(node.message);

  const lineEndings = checkLineEndingConfig();
  if (!lineEndings.ok) log.warn(lineEndings.message);

  if (checkStrayVenv1()) {
    log.warn('.venv-1 exists in the repo root -- looks like a stray duplicate virtualenv left over from a previous cleanup. Safe to delete by hand if `.venv` works.');
  }
}

// ---------------------------------------------------------------------------
// Database readiness (shared by full dev flow and dev:db).
// ---------------------------------------------------------------------------

async function ensureDatabaseReady(venvPython, databaseUrl) {
  const probe = await probeDatabase(databaseUrl, venvPython);
  const port = probe.parsed?.port ?? 5432;

  if (probe.reachable && probe.loginOk) {
    log.success(`Using the PostgreSQL already running on ${probe.parsed.host}:${probe.parsed.port} -- Docker not needed.`);
    printPgAdminHintOnce(probe.parsed);
    return 'local';
  }

  if (probe.reachable && !probe.loginOk && !portOwnedByOurContainer()) {
    explainPortConflict(port);
    throw new LauncherError('Cannot reach the sentinelx database.', 'See the two fixes printed above.');
  }

  // Either nothing is listening yet, or it's our own (not-yet-healthy)
  // container -- either way, bring it up via Docker.
  await ensureDockerReady();
  await startPostgresContainer();

  const reprobe = await probeDatabase(databaseUrl, venvPython);
  if (!reprobe.loginOk) {
    throw new LauncherError(
      'The postgres container is healthy, but logging in as sentinelx still failed.',
      'Run `docker compose logs postgres` and check backend/.env matches docker-compose.yml\'s POSTGRES_USER/PASSWORD/DB.'
    );
  }
  printPgAdminHintOnce(reprobe.parsed);
  return 'docker';
}

// ---------------------------------------------------------------------------
// Backend health poll.
// ---------------------------------------------------------------------------

function pollHealth(timeoutMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const attempt = () => {
      const req = http.get(HEALTH_URL, { timeout: 2000 }, (res) => {
        let body = '';
        res.on('data', (c) => (body += c));
        res.on('end', () => {
          if (res.statusCode === 200) {
            resolve({ ok: true, body });
          } else if (Date.now() - start > timeoutMs) {
            resolve({ ok: false, body });
          } else {
            setTimeout(attempt, 1000);
          }
        });
      });
      req.on('error', () => {
        if (Date.now() - start > timeoutMs) resolve({ ok: false, body: null });
        else setTimeout(attempt, 1000);
      });
      req.on('timeout', () => req.destroy());
    };
    attempt();
  });
}

// ---------------------------------------------------------------------------
// First super_admin bootstrap (invite-only platform, docs/DECISIONS.md).
// The platform's first account is created by the one-time server-side
// command `python -m app.create_super_admin` -- never through a public
// page or endpoint. On a first run (database has no active super_admin)
// the launcher offers to run it right here; once one exists, regular
// runs stay completely silent.
// ---------------------------------------------------------------------------

const SUPER_ADMIN_CHECK = `
import asyncio
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import Admin, AdminLevel

async def main():
    async with AsyncSessionLocal() as db:
        n = (await db.execute(
            select(func.count(Admin.id)).where(
                Admin.admin_level == AdminLevel.super_admin,
                Admin.is_active.is_(True),
            )
        )).scalar() or 0
        print("HAS_SUPER_ADMIN" if n > 0 else "NO_SUPER_ADMIN")

asyncio.run(main())
`;

function hasSuperAdmin(venvPython) {
  const res = spawnSync(venvPython, ['-c', SUPER_ADMIN_CHECK], {
    cwd: path.join(ROOT, 'backend'),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  // A broken check never blocks the normal dev flow -- it only means we
  // skip the first-run offer, which the developer can run manually.
  if (res.status !== 0) {
    log.warn('Could not check for an existing super_admin (continuing without the first-run offer).');
    return true;
  }
  return (res.stdout || '').includes('HAS_SUPER_ADMIN');
}

async function askYesNo(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await rl.question(question)).trim().toLowerCase();
    return answer === '' || answer === 'y' || answer === 'yes';
  } finally {
    rl.close();
  }
}

async function ensureFirstSuperAdmin(venvPython) {
  if (hasSuperAdmin(venvPython)) return; // regular runs: nothing at all

  log.heading('No super_admin exists yet');
  log.raw("   SentinelX is invite-only: the platform's first account is created");
  log.raw('   by a one-time, server-side command -- never through a public page.');
  log.raw('');

  if (process.stdin.isTTY && (await askYesNo('   Create the first super_admin now? [Y/n] '))) {
    log.step('Running: python -m app.create_super_admin  (password input is hidden)');
    // stdio inherit so the interactive getpass prompts work in this
    // terminal; the command itself never prints the password.
    spawnSync(venvPython, ['-m', 'app.create_super_admin'], {
      cwd: path.join(ROOT, 'backend'),
      stdio: 'inherit',
    });
    return;
  }

  log.raw('   Run this when you are ready (from the repo root):');
  log.raw('     Windows:  cd backend && .venv\\Scripts\\python -m app.create_super_admin');
  log.raw('     Unix:     cd backend && .venv/bin/python -m app.create_super_admin');
  log.raw('');
}

async function isBackendAlreadyHealthy() {
  const result = await pollHealth(1500);
  return result.ok;
}

// ---------------------------------------------------------------------------
// Port checks with the "reuse an already-healthy backend" carve-out.
// ---------------------------------------------------------------------------

async function ensurePortsAvailable() {
  const state = readState();

  const backendFree = await isPortFree(BACKEND_PORT);
  if (!backendFree) {
    if (state.backend?.port === BACKEND_PORT && (await isBackendAlreadyHealthy())) {
      log.success(`Port ${BACKEND_PORT} is already serving a healthy SentinelX backend started by this launcher -- reusing it.`);
      return { reuseBackend: true };
    }
    throw new LauncherError(
      `Port ${BACKEND_PORT} is already in use by something else (not a backend this launcher started).`,
      `Find out what: netstat -ano | findstr :${BACKEND_PORT}  (Windows) or lsof -i :${BACKEND_PORT} (mac/Linux), then stop it or free the port and re-run \`npm run dev\`.`
    );
  }

  const frontendFree = await isPortFree(FRONTEND_PORT);
  if (!frontendFree) {
    throw new LauncherError(
      `Port ${FRONTEND_PORT} is already in use by something else.`,
      `Find out what: netstat -ano | findstr :${FRONTEND_PORT}  (Windows) or lsof -i :${FRONTEND_PORT} (mac/Linux), then stop it or free the port and re-run \`npm run dev\`.`
    );
  }

  return { reuseBackend: false };
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function cmdDoctor() {
  log.heading('SentinelX dev:doctor');
  const rows = [];
  const add = (name, ok, detail = '') => rows.push({ name, ok, detail });

  const node = checkNodeVersion();
  add('Node version', node.ok, node.current);

  const python = findPython();
  add('Python 3.10+ found', Boolean(python), python ? `${python.command.join(' ')} (${python.version.major}.${python.version.minor}.${python.version.patch})` : 'not found');

  add('.venv exists', venvExists());
  add('.venv healthy (fastapi/alembic/asyncpg importable)', venvExists() && isVenvHealthy());

  const nodeWork = nodeDepsNeedWork();
  add('node_modules up to date', !nodeWork.needed, nodeWork.reason || '');

  let databaseUrl = null;
  try {
    databaseUrl = readDatabaseUrl();
    add('backend/.env has DATABASE_URL', Boolean(databaseUrl));
  } catch {
    add('backend/.env has DATABASE_URL', false, 'backend/.env missing');
  }

  if (databaseUrl) {
    const venvPython = venvExists() ? venvPythonPath() : null;
    if (venvExists() && isVenvHealthy()) {
      const probe = await probeDatabase(databaseUrl, venvPython);
      add('Database reachable', probe.reachable, probe.parsed ? `${probe.parsed.host}:${probe.parsed.port}` : '');
      add('Database login OK', probe.loginOk);
    } else {
      add('Database reachable', false, 'skipped -- .venv not ready');
      add('Database login OK', false, 'skipped -- .venv not ready');
    }
  }

  add('Port 8000 free', await isPortFree(BACKEND_PORT));
  add('Port 5173 free', await isPortFree(FRONTEND_PORT));
  add('.venv-1 stray folder', !checkStrayVenv1(), checkStrayVenv1() ? 'found -- delete it' : 'none');

  console.log('');
  const nameWidth = Math.max(...rows.map((r) => r.name.length)) + 2;
  for (const r of rows) {
    const label = r.ok ? '\x1b[32m  OK  \x1b[0m' : '\x1b[31m FAIL \x1b[0m';
    console.log(`${label} ${r.name.padEnd(nameWidth)} ${r.detail || ''}`);
  }
  console.log('');
}

async function cmdStop() {
  const state = readState();
  const wantsDbStop = flag('--db');
  let stopped = false;

  if (state.backend?.pid) {
    log.step(`Stopping backend process tree (PID ${state.backend.pid})...`);
    stopped = killPidTree(state.backend.pid);
  }
  if (!stopped) {
    log.step(`Looking for a SentinelX backend listening on port ${BACKEND_PORT}...`);
    stopped = killByPort(BACKEND_PORT);
  }
  if (stopped) {
    log.success('Backend stopped.');
  } else if (findPidsOnPort(BACKEND_PORT).length > 0) {
    log.warn(`Something is listening on port ${BACKEND_PORT}, but it doesn't look like a SentinelX backend (python/uvicorn) -- left it running. Check with netstat -ano | findstr :${BACKEND_PORT} if you want to stop it yourself.`);
  } else {
    log.warn('No running backend found to stop.');
  }

  writeState({ backend: null });

  if (wantsDbStop) {
    log.step('Stopping the postgres container (docker compose stop postgres)...');
    const result = spawnSync('docker', ['compose', 'stop', 'postgres'], { cwd: ROOT, stdio: 'inherit' });
    if (result.status === 0) log.success('postgres container stopped (data volume untouched).');
    else log.warn('Could not stop the postgres container -- is Docker Desktop running?');
  }
}

async function cmdDbOnly() {
  runWarnOnlyChecks();
  const venvPython = ensurePythonVenv();
  ensureBackendEnv();
  const databaseUrl = readDatabaseUrl();
  await ensureDatabaseReady(venvPython, databaseUrl);
  runMigrations(venvPython);
  log.success('Database is up and migrated.');
}

async function cmdApiOnly() {
  const venvPython = ensurePythonVenv();
  ensureBackendEnv();
  log.step(`Starting the backend (uvicorn) in this terminal -- Ctrl+C to stop.`);
  spawnSync(venvPython, ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', String(BACKEND_PORT)], {
    cwd: path.join(ROOT, 'backend'),
    stdio: 'inherit',
  });
}

async function cmdSetup() {
  // Force re-run: drop the cached hashes so the normal ensure* functions
  // treat everything as changed.
  writeState({ nodeModulesHash: null, venvHash: null });
  runWarnOnlyChecks();
  ensureNodeDeps();
  const venvPython = ensurePythonVenv();
  ensureBackendEnv();
  const databaseUrl = readDatabaseUrl();
  await ensureDatabaseReady(venvPython, databaseUrl);
  runMigrations(venvPython);
  await ensureFirstSuperAdmin(venvPython);
  log.success('Setup complete.');
}

async function cmdFullDev() {
  let envAlreadyPresent = false;
  try {
    envAlreadyPresent = Boolean(readDatabaseUrl());
  } catch {
    envAlreadyPresent = false;
  }
  printRunHeader(envAlreadyPresent);
  runWarnOnlyChecks();

  ensureNodeDeps();
  const venvPython = ensurePythonVenv();
  ensureBackendEnv();
  const databaseUrl = readDatabaseUrl();

  const { reuseBackend } = await ensurePortsAvailable();

  const dbSource = await ensureDatabaseReady(venvPython, databaseUrl);
  runMigrations(venvPython);
  // First-run only: silent once an active super_admin exists.
  await ensureFirstSuperAdmin(venvPython);

  let backendChild = null;
  if (!reuseBackend) {
    log.step(INLINE ? 'Starting backend inline (uvicorn)...' : 'Starting backend in a new terminal window ("SentinelX Backend")...');
    const backendArgs = ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', String(BACKEND_PORT)];
    const backendCwd = path.join(ROOT, 'backend');

    if (INLINE) {
      backendChild = spawnInline({ cwd: backendCwd, command: venvPython, args: backendArgs, label: 'api', color: 'magenta' });
      writeState({ backend: { pid: backendChild.pid, port: BACKEND_PORT, startedAt: new Date().toISOString(), mode: 'inline' } });
    } else {
      const pid = openWindow({ cwd: backendCwd, command: venvPython, args: backendArgs, title: 'SentinelX Backend' });
      writeState({ backend: { pid, port: BACKEND_PORT, startedAt: new Date().toISOString(), mode: 'window' } });
    }
  }

  log.step('Starting frontend (vite) in this terminal...');
  // shell:true is the reliable way to invoke the "npm" .cmd shim on Windows
  // (naming "npm.cmd" explicitly can throw EINVAL on some Node/Windows
  // combinations) -- see the matching comment in lib/first-run.mjs.
  const frontendChild = spawn('npm', ['run', 'dev:web'], { cwd: ROOT, stdio: 'inherit', shell: IS_WIN });

  let cleanedUp = false;
  const cleanup = () => {
    if (cleanedUp) return;
    cleanedUp = true;
    if (!reuseBackend) {
      if (INLINE && backendChild) {
        killInlineChild(backendChild);
      } else {
        // wt.exe's own PID can die the instant it hands off to an existing
        // Windows Terminal window, so the recorded PID is best-effort --
        // always fall back to killing whatever ended up on the backend port.
        const state = readState();
        const killed = state.backend?.pid ? killPidTree(state.backend.pid) : false;
        if (!killed) killByPort(BACKEND_PORT);
      }
    }
    // Never touch the postgres container here -- `npm run dev:stop -- --db` does that.
  };

  process.on('SIGINT', () => {
    cleanup();
    process.exit(0);
  });
  frontendChild.on('exit', (code) => {
    cleanup();
    process.exitCode = code ?? 0;
  });

  // Health check happens in parallel with Vite booting; doesn't block it.
  const health = await pollHealth(40000);
  console.log('');
  log.box([
    'SentinelX is starting up',
    '',
    `Frontend   http://localhost:${FRONTEND_PORT}`,
    `API        http://localhost:${BACKEND_PORT}`,
    `API docs   http://localhost:${BACKEND_PORT}/docs`,
    `Database   ${dbSource === 'docker' ? 'Docker (postgres container)' : 'local PostgreSQL install'}`,
    `API health ${health.ok ? 'OK' : 'NOT RESPONDING YET'}`,
  ]);
  if (!health.ok) {
    log.warn(`Backend did not answer ${HEALTH_URL} within 40s -- check the ${INLINE ? '[api] lines above' : '"SentinelX Backend" window'} for the real error. Vite is still running.`);
  }
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

async function main() {
  // Log file mirroring is only worth it for the runs that actually do work --
  // skip it for --doctor/--stop, which are quick utilities.
  if (!flag('--doctor') && !flag('--stop')) {
    const label = flag('--db-only') ? 'db' : flag('--api-only') ? 'api' : flag('--setup-only') ? 'setup' : 'dev';
    log.initLogFile(ROOT, label);
  }
  try {
    if (flag('--doctor')) return await cmdDoctor();
    if (flag('--stop')) return await cmdStop();
    if (flag('--db-only')) return await cmdDbOnly();
    if (flag('--api-only')) return await cmdApiOnly();
    if (flag('--setup-only')) return await cmdSetup();
    return await cmdFullDev();
  } catch (err) {
    if (err instanceof LauncherError) {
      log.error(err.message, err.fix);
      process.exit(1);
    }
    throw err;
  }
}

main();
