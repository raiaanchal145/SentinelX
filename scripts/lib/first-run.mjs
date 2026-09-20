// First-time-setup / repair steps: Node deps, Python venv, backend/.env,
// and Alembic migrations. Every step is decided independently (per the
// launcher spec) so a half-set-up laptop gets only the missing pieces
// repaired, not a full reinstall.

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import * as log from './log.mjs';
import {
  ROOT,
  IS_WIN,
  sha256File,
  readState,
  writeState,
  findPython,
  venvDir,
  venvPythonPath,
  venvExists,
  isVenvHealthy,
  parseDatabaseUrl,
} from './checks.mjs';

const PACKAGE_LOCK = path.join(ROOT, 'package-lock.json');
const NODE_MODULES = path.join(ROOT, 'node_modules');
const REQUIREMENTS = path.join(ROOT, 'backend', 'requirements.txt');
const BACKEND_ENV = path.join(ROOT, 'backend', '.env');
const BACKEND_ENV_EXAMPLE = path.join(ROOT, 'backend', '.env.example');

function run(command, args, opts = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    cwd: ROOT,
    ...opts,
  });
  if (result.error) {
    // The process never even started (e.g. ENOENT) -- there is no "output
    // above" to point to, so say that plainly instead of the generic message.
    log.error(`Could not run "${command}": ${result.error.message}`);
  }
  return result;
}

// npm is a .cmd shim on Windows. Node won't exec .cmd/.bat files directly
// without shell:true (this is Node's own recommended fix for CVE-2024-27980,
// not a workaround) -- naming "npm.cmd" explicitly instead throws EINVAL on
// some Node/Windows combinations, so shell:true is the one that's actually
// reliable. On POSIX this is a no-op (plain "npm" runs fine either way).
function runNpm(args) {
  return run('npm', args, { shell: IS_WIN });
}

// ---------------------------------------------------------------------------
// 1. Node dependencies
// ---------------------------------------------------------------------------

export function nodeDepsNeedWork() {
  const lockHash = sha256File(PACKAGE_LOCK);
  const state = readState();
  if (!fs.existsSync(NODE_MODULES)) return { needed: true, reason: 'node_modules is missing' };
  if (lockHash && lockHash !== state.nodeModulesHash) {
    return { needed: true, reason: 'package-lock.json changed since the last install' };
  }
  return { needed: false, reason: null };
}

export function ensureNodeDeps() {
  const { needed, reason } = nodeDepsNeedWork();
  if (!needed) {
    log.success('Node dependencies up to date (node_modules present, lockfile unchanged).');
    return;
  }

  log.step(`Installing Node dependencies (${reason})...`);
  const hasLockfile = fs.existsSync(PACKAGE_LOCK);
  // `npm ci` is preferred whenever a lockfile exists: it installs exactly
  // what's committed (fast, reproducible across all three teammates'
  // laptops) instead of letting npm re-resolve ranges. Only fall back to
  // `npm install` when there is no lockfile to trust yet.
  const result = hasLockfile ? runNpm(['ci']) : runNpm(['install']);

  if (result.status !== 0) {
    throw new LauncherError(
      result.error
        ? `npm could not be started (${result.error.code || result.error.message}).`
        : 'npm install failed -- see the npm output above for the real error.',
      result.error
        ? 'Make sure Node.js/npm is installed and on PATH (open a new terminal after installing, ' +
          'since PATH changes need a fresh shell), then re-run `npm run dev`.'
        : 'Delete node_modules and re-run `npm run dev`. If it keeps failing, check your ' +
          'internet connection / npm registry access, or run `npm install` by hand to see the full log.'
    );
  }

  writeState({ nodeModulesHash: sha256File(PACKAGE_LOCK) });
  log.success('Node dependencies installed.');
}

// ---------------------------------------------------------------------------
// 2. Python virtualenv
// ---------------------------------------------------------------------------

export class LauncherError extends Error {
  constructor(message, fix) {
    super(message);
    this.fix = fix;
  }
}

export function ensurePythonVenv() {
  const python = findPython();
  if (!python) {
    throw new LauncherError(
      'No Python 3.10+ interpreter found on PATH (tried `py -3`, `python`, `python3`).',
      'Install Python 3.10 or newer from https://www.python.org/downloads/ and make sure ' +
        '"Add python.exe to PATH" is checked during setup, then re-run `npm run dev`.'
    );
  }

  const state = readState();
  const venvPython = venvPythonPath();
  let mustInstallDeps = false;

  if (!venvExists()) {
    log.step(`Creating Python virtual environment at .venv (using ${python.command.join(' ')})...`);
    const [exe, ...baseArgs] = python.command;
    const result = run(exe, [...baseArgs, '-m', 'venv', venvDir()]);
    if (result.status !== 0 || !fs.existsSync(venvPython)) {
      throw new LauncherError(
        'Failed to create the .venv virtual environment.',
        'Make sure the venv module is available (it ships with Python by default) and that ' +
          'you have write access to the project folder, then re-run `npm run dev`.'
      );
    }
    mustInstallDeps = true;
  } else if (!isVenvHealthy()) {
    log.warn('.venv exists but is broken (missing python.exe, or missing fastapi/alembic/asyncpg). Rebuilding it...');
    fs.rmSync(venvDir(), { recursive: true, force: true });
    const [exe, ...baseArgs] = python.command;
    const result = run(exe, [...baseArgs, '-m', 'venv', venvDir()]);
    if (result.status !== 0 || !fs.existsSync(venvPython)) {
      throw new LauncherError(
        'Failed to rebuild the .venv virtual environment.',
        'Delete the .venv folder by hand and re-run `npm run dev`.'
      );
    }
    mustInstallDeps = true;
  }

  const reqHash = sha256File(REQUIREMENTS);
  if (mustInstallDeps || (reqHash && reqHash !== state.venvHash)) {
    log.step(
      mustInstallDeps
        ? 'Installing backend Python packages into the new .venv...'
        : 'backend/requirements.txt changed -- updating Python packages...'
    );
    const result = run(venvPython, ['-m', 'pip', 'install', '-q', '-r', REQUIREMENTS]);
    if (result.status !== 0) {
      throw new LauncherError(
        'pip install -r backend/requirements.txt failed -- see the output above.',
        'Check your internet connection, then re-run `npm run dev`. If one package keeps ' +
          'failing to build, tell your teammates -- it may need a newer/older Python version.'
      );
    }
    writeState({ venvHash: reqHash });
    log.success('Python dependencies installed.');
  } else {
    log.success('Python dependencies up to date (.venv present, requirements.txt unchanged).');
  }

  return venvPython;
}

// ---------------------------------------------------------------------------
// 3. backend/.env
// ---------------------------------------------------------------------------

export function ensureBackendEnv() {
  if (!fs.existsSync(BACKEND_ENV)) {
    if (!fs.existsSync(BACKEND_ENV_EXAMPLE)) {
      throw new LauncherError(
        'backend/.env.example is missing, so backend/.env cannot be created automatically.',
        'Ask a teammate for backend/.env.example (it should be committed to the repo) and try again.'
      );
    }
    log.step('backend/.env not found -- creating it from backend/.env.example...');
    let contents = fs.readFileSync(BACKEND_ENV_EXAMPLE, 'utf8');
    const dockerDefault =
      'postgresql+asyncpg://sentinelx:sentinelx_dev_pw@localhost:5432/sentinelx';
    if (/^DATABASE_URL=/m.test(contents)) {
      contents = contents.replace(/^DATABASE_URL=.*$/m, `DATABASE_URL=${dockerDefault}`);
    } else {
      contents += `\nDATABASE_URL=${dockerDefault}\n`;
    }
    fs.writeFileSync(BACKEND_ENV, contents, 'utf8');
    log.success('Created backend/.env with the docker-compose database credentials.');
    log.info(
      'SMTP_USER/SMTP_PASSWORD were left blank -- registration emails will print their ' +
        'verification code in the backend terminal instead of being sent for real.'
    );
    return { created: true };
  }

  // Never modify an existing .env -- only validate it has what the app needs.
  const contents = fs.readFileSync(BACKEND_ENV, 'utf8');
  const match = /^DATABASE_URL=(.+)$/m.exec(contents);
  if (!match || !match[1].trim()) {
    throw new LauncherError(
      'backend/.env exists but has no DATABASE_URL set.',
      'Add a line like DATABASE_URL=postgresql+asyncpg://sentinelx:sentinelx_dev_pw@localhost:5432/sentinelx ' +
        'to backend/.env, or delete the file and re-run `npm run dev` to regenerate it.'
    );
  }
  const parsed = parseDatabaseUrl(match[1].trim());
  if (!parsed) {
    throw new LauncherError(
      'backend/.env has a DATABASE_URL that could not be parsed.',
      'Check the DATABASE_URL line in backend/.env matches the postgresql+asyncpg://user:pass@host:port/db format.'
    );
  }
  return { created: false, databaseUrl: match[1].trim(), parsed };
}

export function readDatabaseUrl() {
  const contents = fs.readFileSync(BACKEND_ENV, 'utf8');
  const match = /^DATABASE_URL=(.+)$/m.exec(contents);
  return match ? match[1].trim() : null;
}

// ---------------------------------------------------------------------------
// 4. Migrations -- always run, cheap and idempotent.
// ---------------------------------------------------------------------------

const LIKELY_CAUSES = [
  { pattern: /connection refused|could not connect|timeout expired/i, hint: 'PostgreSQL is not reachable on that host/port yet.' },
  { pattern: /password authentication failed/i, hint: 'the DATABASE_URL password does not match the database user.' },
  { pattern: /database "?\w+"? does not exist/i, hint: 'the "sentinelx" database has not been created yet.' },
  { pattern: /multiple heads/i, hint: 'there are two migration heads -- someone needs to merge them with `alembic merge`.' },
  { pattern: /can't locate revision/i, hint: 'a migration file is missing or was renamed/deleted locally.' },
];

export function runMigrations(venvPython) {
  log.step('Applying database migrations (alembic upgrade head)...');
  const result = spawnSync(venvPython, ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: path.join(ROOT, 'backend'),
    encoding: 'utf8',
  });

  if (result.status !== 0) {
    const output = `${result.stdout || ''}${result.stderr || ''}`;
    const lastLines = output.trim().split(/\r?\n/).slice(-15).join('\n');
    const cause = LIKELY_CAUSES.find((c) => c.pattern.test(output));
    log.error('alembic upgrade head failed. Last lines of output:');
    log.raw(lastLines);
    throw new LauncherError(
      'Migrations did not apply -- stopping before starting any servers.',
      cause
        ? `Likely cause: ${cause.hint}`
        : 'Check the output above for the real error, fix it, then re-run `npm run dev`.'
    );
  }

  process.stdout.write(result.stdout || '');
  writeState({ lastMigrationAt: new Date().toISOString() });
  log.success('Migrations applied (or already up to date).');
}
