// Environment probes: Node/Python discovery, venv health, hashing, ports,
// and the .dev-state.json cache. Plain Node built-ins only.

import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(__dirname, '..', '..');
export const STATE_PATH = path.join(ROOT, '.dev-state.json');
export const IS_WIN = process.platform === 'win32';
export const IS_MAC = process.platform === 'darwin';

// ---------------------------------------------------------------------------
// .dev-state.json -- small cache of "have we already done this" facts.
// Never throws: a missing/corrupt state file just means "start fresh".
// ---------------------------------------------------------------------------

export function readState() {
  try {
    const raw = fs.readFileSync(STATE_PATH, 'utf8');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export function writeState(patch) {
  const current = readState();
  const next = { ...current, ...patch, updatedAt: new Date().toISOString() };
  try {
    fs.writeFileSync(STATE_PATH, JSON.stringify(next, null, 2) + '\n', 'utf8');
  } catch (err) {
    // Non-fatal -- worst case we redo a step next run.
    console.error(`(warning) could not write ${STATE_PATH}: ${err.message}`);
  }
  return next;
}

// ---------------------------------------------------------------------------
// Hashing -- used to decide "did package-lock.json / requirements.txt change
// since the last successful install".
// ---------------------------------------------------------------------------

export function sha256File(absPath) {
  try {
    const buf = fs.readFileSync(absPath);
    return createHash('sha256').update(buf).digest('hex');
  } catch {
    return null; // file missing
  }
}

// ---------------------------------------------------------------------------
// Node version -- warn only, never block (spec says warn, don't block).
// ---------------------------------------------------------------------------

export function checkNodeVersion() {
  const [major, minor] = process.versions.node.split('.').map(Number);
  const okModern = major > 22 || (major === 22 && minor >= 12);
  const okLts = major === 20 && minor >= 19;
  const ok = okModern || okLts;
  return {
    ok,
    current: process.versions.node,
    message: ok
      ? null
      : `Node ${process.versions.node} detected -- SentinelX expects Node 20.19+ or 22.12+. ` +
        'Things will likely still work, but if npm/vite behave oddly, upgrade Node first.',
  };
}

// ---------------------------------------------------------------------------
// Python interpreter discovery.
// ---------------------------------------------------------------------------

const PYTHON_CANDIDATES = IS_WIN
  ? [['py', '-3'], ['python'], ['python3']]
  : [['python3'], ['python']];

function parsePythonVersion(output) {
  const m = /Python (\d+)\.(\d+)\.(\d+)/.exec(output);
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}

// Returns { command: [exe, ...args] , version } for the first interpreter
// found that is >= 3.10, or null if none qualify.
export function findPython() {
  for (const command of PYTHON_CANDIDATES) {
    const [exe, ...args] = command;
    const result = spawnSync(exe, [...args, '--version'], { encoding: 'utf8' });
    if (result.error || result.status !== 0) continue;
    // Some Python builds print the version to stderr instead of stdout.
    const output = `${result.stdout || ''}${result.stderr || ''}`;
    const version = parsePythonVersion(output);
    if (!version) continue;
    if (version.major === 3 && version.minor >= 10) {
      return { command, version };
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Virtualenv helpers. Always call the venv's python binary directly --
// never rely on "activating" it (activation is shell-specific and fragile
// from a spawned child process anyway).
// ---------------------------------------------------------------------------

export function venvDir() {
  return path.join(ROOT, '.venv');
}

export function venvPythonPath() {
  return IS_WIN
    ? path.join(venvDir(), 'Scripts', 'python.exe')
    : path.join(venvDir(), 'bin', 'python');
}

export function venvExists() {
  return fs.existsSync(venvPythonPath());
}

// Runs a real import check inside the venv -- catches a venv that exists as
// a directory but is missing packages (interrupted install) or missing its
// own python.exe (corrupted venv).
export function isVenvHealthy() {
  const py = venvPythonPath();
  if (!fs.existsSync(py)) return false;
  const result = spawnSync(py, ['-c', 'import fastapi, alembic, asyncpg'], {
    encoding: 'utf8',
  });
  return result.status === 0;
}

// ---------------------------------------------------------------------------
// Ports.
// ---------------------------------------------------------------------------

export function isPortFree(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const tester = net.createServer();
    tester.once('error', () => resolve(false));
    tester.once('listening', () => {
      tester.close(() => resolve(true));
    });
    tester.listen(port, host);
  });
}

// Best-effort: find the PID(s) currently listening on a TCP port, so we can
// tell the user what to look at (or kill it ourselves in dev:stop).
export function findPidsOnPort(port) {
  try {
    if (IS_WIN) {
      const result = spawnSync('cmd', ['/c', `netstat -ano | findstr :${port}`], {
        encoding: 'utf8',
      });
      if (result.status !== 0 || !result.stdout) return [];
      const pids = new Set();
      for (const line of result.stdout.split(/\r?\n/)) {
        const parts = line.trim().split(/\s+/);
        const pid = parts[parts.length - 1];
        if (/^\d+$/.test(pid) && line.includes('LISTENING')) pids.add(Number(pid));
      }
      return [...pids];
    }
    const result = spawnSync('lsof', ['-t', `-i:${port}`, '-sTCP:LISTEN'], {
      encoding: 'utf8',
    });
    if (result.status !== 0 || !result.stdout) return [];
    return result.stdout
      .split(/\r?\n/)
      .filter(Boolean)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Misc warn-only checks.
// ---------------------------------------------------------------------------

export function checkStrayVenv1() {
  return fs.existsSync(path.join(ROOT, '.venv-1'));
}

export function checkLineEndingConfig() {
  // Best-effort only: on Windows, a missing/false core.autocrlf combined
  // with the repo's LF-normalized files can cause noisy "whole file changed"
  // diffs in some editors. We just nudge, never fix it for the user.
  const result = spawnSync('git', ['config', '--get', 'core.autocrlf'], {
    cwd: ROOT,
    encoding: 'utf8',
  });
  const value = (result.stdout || '').trim().toLowerCase();
  if (IS_WIN && value !== 'true' && value !== 'input') {
    return {
      ok: false,
      message:
        'git config core.autocrlf is not set to "true" on this Windows checkout. ' +
        'Run: git config --global core.autocrlf true  (prevents noisy line-ending diffs).',
    };
  }
  return { ok: true, message: null };
}

export function homeDir() {
  return os.homedir();
}

// ---------------------------------------------------------------------------
// DATABASE_URL parsing -- shared by first-run.mjs (validation) and
// docker.mjs (reachability probing). Expects the SQLAlchemy-style
// "postgresql+asyncpg://user:pass@host:port/dbname" form used throughout
// this repo.
// ---------------------------------------------------------------------------

export function parseDatabaseUrl(databaseUrl) {
  try {
    // URL() chokes on the "+asyncpg" driver suffix, so normalize first.
    const normalized = databaseUrl.replace(/^postgresql\+[^:]+:/, 'postgresql:');
    const url = new URL(normalized);
    return {
      user: decodeURIComponent(url.username || ''),
      password: decodeURIComponent(url.password || ''),
      host: url.hostname || 'localhost',
      port: url.port ? Number(url.port) : 5432,
      database: url.pathname.replace(/^\//, '') || 'sentinelx',
    };
  } catch {
    return null;
  }
}

// Best-effort process-name lookup, used before killing-by-port so dev:stop
// doesn't nuke an unrelated program that happens to be on the same port.
export function processNameForPid(pid) {
  try {
    if (IS_WIN) {
      const result = spawnSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], {
        encoding: 'utf8',
      });
      if (result.status !== 0 || !result.stdout) return null;
      const first = result.stdout.split(/\r?\n/)[0];
      const match = /^"([^"]+)"/.exec(first);
      return match ? match[1] : null;
    }
    const result = spawnSync('ps', ['-p', String(pid), '-o', 'comm='], { encoding: 'utf8' });
    if (result.status !== 0) return null;
    return (result.stdout || '').trim() || null;
  } catch {
    return null;
  }
}

export function looksLikeOurBackend(pid) {
  const name = processNameForPid(pid);
  if (!name) return false;
  const lower = name.toLowerCase();
  return lower.includes('python') || lower.includes('uvicorn') || lower.includes('cmd.exe');
}
