// Cross-platform "open a new terminal window running a command" plus the
// inline fallback and process-tree kill helpers. Windows 11 is the primary
// target; macOS/Linux are best-effort per the launcher spec.

import { spawn, spawnSync } from 'node:child_process';
import * as log from './log.mjs';
import { IS_WIN, IS_MAC, findPidsOnPort, looksLikeOurBackend } from './checks.mjs';

function commandExists(cmd) {
  const probe = IS_WIN ? spawnSync('where', [cmd]) : spawnSync('which', [cmd]);
  return probe.status === 0;
}

// Quote a single argument for cmd.exe's /k string (best-effort -- our own
// commands never contain characters that need heavier escaping).
function quoteWin(arg) {
  return /\s/.test(arg) ? `"${arg}"` : arg;
}

// Opens a new terminal window running `command args...` in `cwd`, titled
// `title`. Returns the best-effort PID of the window's own shell process
// (used by dev:stop's tree-kill) -- may be null if we truly cannot obtain
// one, in which case dev:stop falls back to killing whatever is listening
// on the backend port instead.
export function openWindow({ cwd, command, args, title }) {
  const fullCommand = [command, ...args].map(quoteWin).join(' ');

  if (IS_WIN) {
    // PowerShell's Start-Process -PassThru is the one Windows-native way to
    // reliably get back the PID of a *detached* process -- `cmd /c start`
    // launched directly from Node only gives us the short-lived launcher
    // process's PID, not the window's. We still only ever run one inline
    // -Command string (never a .ps1 file), so this does not hit the
    // execution-policy restrictions that apply to script files.
    const useWt = commandExists('wt');
    const innerCmd = `cmd.exe /k "${fullCommand}"`;
    const psCommand = useWt
      ? `$p = Start-Process wt.exe -ArgumentList 'new-tab','--title','${title}','-d','${cwd}',${innerCmdArgsForWt(fullCommand)} -PassThru; $p.Id`
      : `$p = Start-Process cmd.exe -ArgumentList '/k','${fullCommand.replace(/'/g, "''")}' -WorkingDirectory '${cwd}' -PassThru; $p.Id`;

    const result = spawnSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', psCommand], {
      encoding: 'utf8',
    });
    const pid = Number((result.stdout || '').trim());

    if (!Number.isFinite(pid)) {
      // Last-resort fallback: plain `start`, no PID capture at all.
      log.warn('Could not capture the backend window PID via PowerShell -- falling back to `start` (dev:stop will use the port instead).');
      spawn('cmd.exe', ['/c', 'start', `"${title}"`, 'cmd', '/k', fullCommand], {
        cwd,
        detached: true,
        stdio: 'ignore',
      }).unref();
      return null;
    }
    return pid;
  }

  if (IS_MAC) {
    const script = `tell application "Terminal" to do script "cd ${shEscape(cwd)} && ${fullCommand.replace(/"/g, '\\"')}"`;
    const child = spawn('osascript', ['-e', script], { detached: true, stdio: 'ignore' });
    child.unref();
    // osascript's own PID isn't the shell's PID either -- rely on the port
    // fallback for dev:stop on macOS too.
    return null;
  }

  // Linux: try a few common terminal emulators in order.
  const linuxTerminals = [
    { cmd: 'gnome-terminal', args: ['--title', title, '--', 'bash', '-lc', `cd '${cwd}' && ${fullCommand}; exec bash`] },
    { cmd: 'konsole', args: ['--title', title, '-e', 'bash', '-lc', `cd '${cwd}' && ${fullCommand}; exec bash`] },
    { cmd: 'x-terminal-emulator', args: ['-e', `bash -lc "cd '${cwd}' && ${fullCommand}; exec bash"`] },
    { cmd: 'xterm', args: ['-T', title, '-e', `bash -lc "cd '${cwd}' && ${fullCommand}; exec bash"`] },
  ];
  for (const t of linuxTerminals) {
    if (!commandExists(t.cmd)) continue;
    const child = spawn(t.cmd, t.args, { detached: true, stdio: 'ignore' });
    child.unref();
    return child.pid || null;
  }
  return null;
}

function innerCmdArgsForWt(fullCommand) {
  // wt.exe's -ArgumentList needs each token as its own PowerShell array
  // element; simplest reliable form is to hand it cmd /k "<command>" as one
  // quoted token via cmd.exe itself.
  return `'cmd.exe','/k','${fullCommand.replace(/'/g, "''")}'`;
}

function shEscape(s) {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

// ---------------------------------------------------------------------------
// Killing what we started.
// ---------------------------------------------------------------------------

export function killPidTree(pid) {
  if (!pid) return false;
  try {
    if (IS_WIN) {
      const result = spawnSync('taskkill', ['/PID', String(pid), '/T', '/F']);
      return result.status === 0;
    }
    // POSIX: negative pid signals the whole process group (only works if the
    // child was spawned with detached: true, which establishes a new group).
    try {
      process.kill(-pid, 'SIGTERM');
    } catch {
      process.kill(pid, 'SIGTERM');
    }
    return true;
  } catch {
    return false;
  }
}

// Only kills processes on `port` that actually look like our backend
// (python/uvicorn) -- a safety net against nuking an unrelated program that
// happens to be using the same port, since this is our last-resort fallback
// when we don't have (or can't trust) a recorded PID.
export function killByPort(port) {
  const pids = findPidsOnPort(port);
  let killedAny = false;
  for (const pid of pids) {
    if (!looksLikeOurBackend(pid)) continue;
    if (killPidTree(pid)) killedAny = true;
  }
  return killedAny;
}

// ---------------------------------------------------------------------------
// Inline fallback: run backend + frontend as this process's own children.
// ---------------------------------------------------------------------------

export function spawnInline({ cwd, command, args, label, color }) {
  const child = spawn(command, args, {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: !IS_WIN,
  });
  child.stdout.on('data', (chunk) => log.prefixLines(chunk, label, color));
  child.stderr.on('data', (chunk) => log.prefixLines(chunk, label, color));
  return child;
}

export function killInlineChild(child) {
  if (!child || child.killed) return;
  if (IS_WIN) {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F']);
  } else {
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  }
}
