// Dev sharing (`npm run dev:share`) -- opt-in exposure of the local dev
// stack to other devices:
//
//   LAN mode    detect the machine's private IPv4 addresses and print
//               http://<lan-ip>:5173 (any device on the same Wi-Fi).
//   Tunnel mode run a throwaway `cloudflared` quick tunnel (no account,
//               no signup) in front of Vite, so a phone on mobile data
//               can open the app too.
//
// The chosen origin is returned to dev.mjs, which sets -- for that one
// session only -- FRONTEND_URL (backend: email links point at the shared
// URL) and DEV_SHARE_ORIGINS (backend: session-scoped CORS allow-list).
// Plain `npm run dev` never calls any of this.
//
// cloudflared is an EXTERNAL CLI, deliberately not an npm dependency, and
// this module never installs it -- it only points at the install command.

import readline from 'node:readline/promises';
import { spawn, spawnSync } from 'node:child_process';
import os from 'node:os';
import * as log from './log.mjs';
import { LauncherError } from './first-run.mjs';
import { IS_WIN } from './checks.mjs';

export const CLOUDFLARED_INSTALL_HINT =
  IS_WIN
    ? 'winget install --id Cloudflare.cloudflared   (or download cloudflared-windows-amd64.msi from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)'
    : process.platform === 'darwin'
      ? 'brew install cloudflared'
      : 'See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ for the Linux package (.deb/.rpm) or direct binary.';

// ---------------------------------------------------------------------------
// LAN mode: private IPv4 detection.
// ---------------------------------------------------------------------------

// Only IPv4 private ranges are useful for LAN sharing -- loopback is the
// machine itself, link-local (169.254.x) is unroutable, CGNAT (100.64/10)
// and public IPs are not "same Wi-Fi" addresses.
function isPrivateIPv4(address) {
  const m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(address);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  if (a === 10) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  return false;
}

export function detectLanIps() {
  const found = [];
  for (const [name, addrs] of Object.entries(os.networkInterfaces())) {
    for (const addr of addrs ?? []) {
      if (addr.family !== 'IPv4' || addr.internal) continue;
      if (!isPrivateIPv4(addr.address)) continue;
      found.push({ iface: name, address: addr.address });
    }
  }
  // Stable order so the "recommended" pick doesn't jump between runs.
  found.sort((x, y) => x.address.localeCompare(y.address, undefined, { numeric: true }));
  return found;
}

export function lanShareUrl(port) {
  const ips = detectLanIps();
  if (ips.length === 0) {
    throw new LauncherError(
      'No private IPv4 address found -- LAN sharing is not possible on this network right now.',
      'Connect to a Wi-Fi/network that assigns this machine a normal LAN address, or use tunnel mode instead (--tunnel).'
    );
  }
  return {
    urls: ips.map((i) => `http://${i.address}:${port}`),
    recommended: `http://${ips[0].address}:${port}`,
    interfaces: ips,
  };
}

// ---------------------------------------------------------------------------
// Mode selection: --lan / --tunnel flags, or an interactive prompt.
// ---------------------------------------------------------------------------

async function askChoice(question, options) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    for (let i = 0; i < options.length; i += 1) {
      log.raw(`   ${i + 1}) ${options[i].label}`);
    }
    const answer = (await rl.question(question)).trim();
    const n = Number(answer);
    if (Number.isInteger(n) && n >= 1 && n <= options.length) return options[n - 1];
    return options[0]; // Enter picks the default (first) option
  } finally {
    rl.close();
  }
}

export async function pickShareMode(flags) {
  if (flags.lan) return 'lan';
  if (flags.tunnel) return 'tunnel';

  log.heading('Share the dev environment');
  log.raw('   Plain localhost stays available either way. Sharing is opt-in');
  log.raw('   and only for this run -- it exposes DEV seed data, so stop it');
  log.raw('   (Ctrl+C) as soon as the demo is over.');
  log.raw('');

  if (!process.stdin.isTTY) {
    log.warn('Not a TTY -- defaulting to LAN mode (pass --lan or --tunnel to skip this).');
    return 'lan';
  }

  const choice = await askChoice('   Share via? [1] ', [
    { label: 'LAN -- any device on the same Wi-Fi (no extra tools)', value: 'lan' },
    { label: 'Tunnel -- a temporary public URL, works from any network (needs cloudflared)', value: 'tunnel' },
  ]);
  return choice.value;
}

// ---------------------------------------------------------------------------
// Tunnel mode: cloudflared quick tunnel lifecycle.
// ---------------------------------------------------------------------------

function cloudflaredOnPath() {
  const probe = IS_WIN ? spawnSync('where', ['cloudflared']) : spawnSync('which', ['cloudflared']);
  return probe.status === 0;
}

export function ensureCloudflared() {
  if (cloudflaredOnPath()) return;
  throw new LauncherError(
    'Tunnel mode needs the `cloudflared` CLI, which is not installed (or not on PATH).',
    `Install it with:  ${CLOUDFLARED_INSTALL_HINT}\n` +
      '   It is an external tool, not an npm dependency -- the launcher never installs it for you.\n' +
      '   (No account or signup is needed for quick tunnels. Or re-run with --lan for same-Wi-Fi sharing without any extra tool.)'
  );
}

const TUNNEL_URL_PATTERN = /https:\/\/[a-z0-9][a-z0-9-]*\.trycloudflare\.com/i;
const TUNNEL_TIMEOUT_MS = 60_000;

// Starts `cloudflared tunnel --url http://localhost:<port>` and resolves
// with { child, url, pid } once the quick-tunnel URL appears in its output,
// or rejects if it fails/exits/times out.
export function startQuickTunnel(port) {
  return new Promise((resolve, reject) => {
    const child = spawn('cloudflared', ['tunnel', '--url', `http://localhost:${port}`], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    let url = null;
    let outputTail = '';
    let settled = false;
    const collect = (chunk) => {
      const text = chunk.toString();
      outputTail = (outputTail + text).slice(-2000);
      if (settled || url) return;
      const match = TUNNEL_URL_PATTERN.exec(text);
      if (match) {
        url = match[0];
        settled = true;
        clearTimeout(timer);
        resolve({ child, url, pid: child.pid });
      }
    };
    child.stdout.on('data', collect);
    child.stderr.on('data', collect); // cloudflared logs most progress to stderr

    child.on('exit', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new LauncherError(
        `cloudflared exited (code ${code ?? 'signal'}) before a quick-tunnel URL was printed.`,
        'Run `cloudflared tunnel --url http://localhost:5173` by hand to see the full error, or use --lan instead.'
      ));
    });
    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new LauncherError(
        `cloudflared could not be started: ${err.message}`,
        `Is cloudflared on PATH? Install it with:  ${CLOUDFLARED_INSTALL_HINT}`
      ));
    });

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill(); } catch { /* already gone */ }
      reject(new LauncherError(
        `cloudflared did not report a quick-tunnel URL within ${Math.round(TUNNEL_TIMEOUT_MS / 1000)}s.`,
        'Check your internet connection, or run it by hand to see the full output:\n' +
          '     cloudflared tunnel --url http://localhost:5173\n' +
          '   Or use --lan for same-Wi-Fi sharing without a tunnel.'
      ));
    }, TUNNEL_TIMEOUT_MS);

    if (process.env.SENTINELX_DEBUG) {
      log.raw(`   [cloudflared tail] (last output kept for debugging)`);
      const debugTimer = setInterval(() => {
        const last = outputTail.trim().split(/\r?\n/).pop();
        if (last) log.raw(`   [cloudflared] ${last}`);
      }, 5000);
      child.on('exit', () => clearInterval(debugTimer));
    }
  });
}
