// Database availability: prefer an already-running PostgreSQL (local install
// path from the old README), fall back to `docker compose up -d postgres`
// only when nothing is already listening. Never touches the `app`
// devcontainer service, never runs `down -v` or anything destructive.

import { spawnSync } from 'node:child_process';
import net from 'node:net';
import * as log from './log.mjs';
import { ROOT, readState, writeState, parseDatabaseUrl } from './checks.mjs';
import { LauncherError } from './first-run.mjs';

const CONTAINER_NAME = 'sentinelx-postgres';
const REDIS_CONTAINER_NAME = 'sentinelx-redis';
const REDIS_PORT = 6379;

function tcpProbe(host, port, timeoutMs = 2000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
    socket.connect(port, host);
  });
}

// Real login check, not just "is the port open" -- a stray unrelated service
// (or someone else's Postgres) could be listening on 5432 too.
function loginProbe(venvPython, databaseUrl) {
  const snippet = `
import asyncio, os, sys
import asyncpg

async def main():
    dsn = os.environ["SENTINELX_PROBE_DSN"].replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncio.wait_for(asyncpg.connect(dsn=dsn), timeout=4)
    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()

try:
    asyncio.run(main())
except Exception as exc:
    print(f"PROBE_FAIL: {exc}", file=sys.stderr)
    sys.exit(1)
`;
  const result = spawnSync(venvPython, ['-c', snippet], {
    encoding: 'utf8',
    env: { ...process.env, SENTINELX_PROBE_DSN: databaseUrl },
  });
  return result.status === 0;
}

// Returns { reachable, loginOk, parsed }.
export async function probeDatabase(databaseUrl, venvPython) {
  const parsed = parseDatabaseUrl(databaseUrl);
  if (!parsed) return { reachable: false, loginOk: false, parsed: null };
  const reachable = await tcpProbe(parsed.host, parsed.port);
  if (!reachable) return { reachable: false, loginOk: false, parsed };
  const loginOk = loginProbe(venvPython, databaseUrl);
  return { reachable: true, loginOk, parsed };
}

// ---------------------------------------------------------------------------
// Docker
// ---------------------------------------------------------------------------

function dockerCliMissing() {
  const result = spawnSync('docker', ['--version']);
  return Boolean(result.error);
}

function dockerEngineUp() {
  const result = spawnSync('docker', ['info'], { encoding: 'utf8' });
  return result.status === 0;
}

export async function ensureDockerReady({ timeoutMs = 120000 } = {}) {
  if (dockerCliMissing()) {
    throw new LauncherError(
      'The `docker` command was not found.',
      'Install Docker Desktop from https://www.docker.com/products/docker-desktop/, open it once, ' +
        'then re-run `npm run dev`. (Or install PostgreSQL locally instead -- see README.md.)'
    );
  }

  if (dockerEngineUp()) return true;

  log.warn('Docker Desktop is not running yet.');
  log.raw('   Open Docker Desktop and wait until it says "Engine running" -- this window will continue automatically.');
  const spin = log.spinner('Waiting for Docker Desktop');
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 2000));
    if (dockerEngineUp()) {
      spin.stop('Docker Desktop is up.');
      return true;
    }
  }
  spin.stop(null);
  throw new LauncherError(
    'Timed out waiting for Docker Desktop to start (waited 2 minutes).',
    'Open Docker Desktop, wait for "Engine running" in its window, then re-run `npm run dev`.'
  );
}

function containerHealth() {
  const result = spawnSync(
    'docker',
    ['inspect', '--format', '{{.State.Health.Status}}', CONTAINER_NAME],
    { encoding: 'utf8' }
  );
  if (result.status !== 0) return 'missing';
  return (result.stdout || '').trim();
}

export async function startPostgresContainer({ timeoutMs = 90000 } = {}) {
  log.step('Starting the postgres service (docker compose up -d postgres)...');
  // Only ever the named service -- never the placeholder `app` devcontainer
  // service, and never `up -d` with no service name.
  const result = spawnSync('docker', ['compose', 'up', '-d', 'postgres'], {
    cwd: ROOT,
    stdio: 'inherit',
  });
  if (result.status !== 0) {
    throw new LauncherError(
      'docker compose up -d postgres failed -- see the output above.',
      'Check Docker Desktop is fully started and that nothing else in docker-compose.yml is misconfigured.'
    );
  }

  const spin = log.spinner('Waiting for the postgres container to become healthy');
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const health = containerHealth();
    if (health === 'healthy') {
      spin.stop('postgres container is healthy.');
      return;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  spin.stop(null);
  throw new LauncherError(
    `The ${CONTAINER_NAME} container did not become healthy within 90 seconds.`,
    `Run \`docker compose logs postgres\` to see what's wrong.`
  );
}

// Is whatever is listening on 5432 actually our container?
export function portOwnedByOurContainer() {
  const result = spawnSync('docker', ['ps', '--filter', `name=${CONTAINER_NAME}`, '--format', '{{.Names}}'], {
    encoding: 'utf8',
  });
  return result.status === 0 && (result.stdout || '').includes(CONTAINER_NAME);
}

// ---------------------------------------------------------------------------
// Redis (background-work queue -- docs/DECISIONS.md). Same pattern as
// postgres: use whatever already answers on 6379, else docker compose.
// ---------------------------------------------------------------------------

export async function probeRedis(port = REDIS_PORT) {
  return tcpProbe('localhost', port);
}

export async function ensureRedisReady() {
  if (await probeRedis()) return;

  await ensureDockerReady();
  log.step('Starting the redis service (docker compose up -d redis)...');
  const result = spawnSync('docker', ['compose', 'up', '-d', 'redis'], { cwd: ROOT, stdio: 'inherit' });
  if (result.status !== 0) {
    throw new LauncherError(
      'docker compose up -d redis failed -- see the output above.',
      'Check Docker Desktop is fully started, then re-run `npm run dev`.'
    );
  }

  const spin = log.spinner('Waiting for the redis container to become healthy');
  const start = Date.now();
  while (Date.now() - start < 60000) {
    if (await probeRedis()) {
      spin.stop('redis is up.');
      return;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  spin.stop(null);
  throw new LauncherError(
    `The ${REDIS_CONTAINER_NAME} container did not become reachable within 60 seconds.`,
    'Run `docker compose logs redis` to see what is wrong.'
  );
}

export function stopRedis() {
  const result = spawnSync('docker', ['compose', 'stop', 'redis'], { cwd: ROOT, encoding: 'utf8' });
  return result.status === 0;
}

export function explainPortConflict(port) {
  log.error(
    `Port ${port} is in use, but it's not the ${CONTAINER_NAME} container, and logging in as the sentinelx user failed.`
  );
  log.raw('   This usually means a locally-installed PostgreSQL is already using this port. Two ways to fix it:');
  log.raw('     1) Stop the local PostgreSQL Windows service (Services app -> "postgresql-x64-..." -> Stop),');
  log.raw('        then re-run `npm run dev` so Docker can take over port 5432.');
  log.raw('     2) Keep your local PostgreSQL running, and instead create the sentinelx user/database in it');
  log.raw('        (see README.md, "Database setup", Step 2) so the launcher can use it directly.');
}

// ---------------------------------------------------------------------------
// pgAdmin (cannot be automated -- just print what to type in, once).
// ---------------------------------------------------------------------------

export function printPgAdminHintOnce(parsed) {
  const state = readState();
  if (state.pgAdminHintShown) return;
  log.heading('Register this database in pgAdmin 4 (one-time, manual):');
  log.raw(`   Host:     ${parsed?.host || 'localhost'}`);
  log.raw(`   Port:     ${parsed?.port || 5432}`);
  log.raw(`   Database: ${parsed?.database || 'sentinelx'}`);
  log.raw(`   Username: ${parsed?.user || 'sentinelx'}`);
  log.raw(`   Password: ${parsed?.password || 'sentinelx_dev_pw'}`);
  log.raw('   In pgAdmin: right-click "Servers" -> Register -> Server..., put any name on the');
  log.raw('   General tab, then paste the values above into the Connection tab and Save.');
  writeState({ pgAdminHintShown: true });
}
