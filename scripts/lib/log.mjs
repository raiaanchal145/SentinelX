// Small ANSI logging/formatting helper used by every other launcher module.
// No dependencies -- plain Node built-ins only, so this runs before `npm install`.

const COLOR = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

// Respect NO_COLOR / dumb terminals; Windows Terminal and cmd.exe (Win10 1511+)
// both understand ANSI, so we don't special-case win32 here.
const supportsColor =
  !process.env.NO_COLOR && process.stdout.isTTY !== false;

function paint(color, text) {
  if (!supportsColor) return text;
  return `${COLOR[color]}${text}${COLOR.reset}`;
}

export function info(msg) {
  console.log(`${paint('blue', 'i')}  ${msg}`);
}

export function step(msg) {
  console.log(`${paint('cyan', '->')} ${msg}`);
}

export function success(msg) {
  console.log(`${paint('green', 'OK')} ${msg}`);
}

export function warn(msg) {
  console.log(`${paint('yellow', '!!')} ${msg}`);
}

// Every failure must say what's wrong AND the exact fix, so `fix` is required
// (not optional) -- callers are nudged to always provide one.
export function error(msg, fix) {
  console.error(`${paint('red', 'XX')} ${paint('bold', msg)}`);
  if (fix) {
    console.error(`   ${paint('gray', 'Fix:')} ${fix}`);
  }
}

export function heading(msg) {
  console.log('');
  console.log(paint('bold', msg));
}

export function raw(msg) {
  console.log(msg);
}

// Prefix each line of a chunk of output, used for [api]/[web] inline mode.
export function prefixLines(chunk, label, color = 'magenta') {
  const text = chunk.toString();
  const lines = text.split(/\r?\n/);
  // Drop the trailing empty element produced by a trailing newline.
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  for (const line of lines) {
    console.log(`${paint(color, `[${label}]`)} ${line}`);
  }
}

// Simple single-line spinner for "waiting for X" polls. Call .stop(finalMsg)
// when done; safe to call in non-TTY contexts (falls back to periodic lines).
export function spinner(label) {
  const frames = ['|', '/', '-', '\\'];
  let i = 0;
  let stopped = false;
  let timer = null;

  if (process.stdout.isTTY) {
    timer = setInterval(() => {
      process.stdout.write(`\r${paint('cyan', frames[i % frames.length])} ${label}   `);
      i += 1;
    }, 120);
  } else {
    console.log(`${label} ...`);
  }

  return {
    stop(finalMsg) {
      if (stopped) return;
      stopped = true;
      if (timer) {
        clearInterval(timer);
        process.stdout.write(`\r${' '.repeat(label.length + 6)}\r`);
      }
      if (finalMsg) console.log(finalMsg);
    },
  };
}

export function box(lines) {
  const width = Math.max(...lines.map((l) => l.length)) + 2;
  const top = `+${'-'.repeat(width)}+`;
  const bottom = top;
  console.log(paint('cyan', top));
  for (const line of lines) {
    const padded = line + ' '.repeat(width - line.length - 1);
    console.log(`${paint('cyan', '|')} ${padded}${paint('cyan', '|')}`);
  }
  console.log(paint('cyan', bottom));
}

// ---------------------------------------------------------------------------
// Optional run logging: mirrors console output (ANSI stripped) into
// .dev-logs/, keeping only the most recent 5 runs.
// ---------------------------------------------------------------------------

import fs from 'node:fs';
import path from 'node:path';

const ANSI_PATTERN = /\x1b\[[0-9;]*m/g;

export function initLogFile(root, label) {
  const dir = path.join(root, '.dev-logs');
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch {
    return; // best-effort only -- never block the launcher on a logging failure
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filePath = path.join(dir, `${stamp}-${label}.log`);
  let stream;
  try {
    stream = fs.createWriteStream(filePath, { flags: 'a' });
  } catch {
    return;
  }

  const wrap = (original) => (...args) => {
    original(...args);
    try {
      stream.write(args.map(String).join(' ').replace(ANSI_PATTERN, '') + '\n');
    } catch {
      /* best-effort */
    }
  };
  console.log = wrap(console.log.bind(console));
  console.error = wrap(console.error.bind(console));

  // Prune to the 5 most recent log files.
  try {
    const files = fs
      .readdirSync(dir)
      .filter((f) => f.endsWith('.log'))
      .map((f) => ({ f, t: fs.statSync(path.join(dir, f)).mtimeMs }))
      .sort((a, b) => b.t - a.t);
    for (const { f } of files.slice(5)) {
      fs.unlinkSync(path.join(dir, f));
    }
  } catch {
    /* best-effort */
  }
}
