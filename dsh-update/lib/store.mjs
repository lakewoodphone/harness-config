// store.mjs — paths, atomic writes, pinned state, append-only history.
//
// This module owns WHERE state lives and HOW it is written. It owns no analysis and no CLI
// behaviour. It contains no shell-outs of any kind: hashing and hostname are done in Node, so a
// read of this file can never start, stop or kill anything.
//
// Safety invariants implemented here (SPEC.md §Safety invariants):
//   1. nothing here deletes anything — there is no unlink/rm/rmdir call in this file at all;
//   4. every write outside dsh-update/ goes through backupAndWrite(), which copies the existing
//      file to a timestamped .bak- before an atomic replacement;
//   6. the history ledger is append-only (fs.appendFileSync only);
//   8. a failed read returns a structured failure, never an empty success.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

// ── locations ───────────────────────────────────────────────────────────────

const HERE = path.dirname(fileURLToPath(import.meta.url));      // <repo>/dsh-update/lib
export const ROOT = path.resolve(HERE, '..');                    // <repo>/dsh-update
export const REPO_ROOT = path.resolve(ROOT, '..');               // harness-config

function envPath(name) {
  const v = process.env[name];
  return v && String(v).trim() ? path.resolve(String(v).trim()) : null;
}

function localAppData() {
  return process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
}

/** The launcher knob we promote/roll back. Overridable so tests never touch the live file. */
export function windowsJsonPath() {
  return envPath('DSH_UPDATE_WINDOWS_JSON') || path.join(REPO_ROOT, 'multi-window', 'windows.json');
}

function dshHome() {
  return envPath('DSH_HOME') || path.join(os.homedir(), '.dsh');
}

export const PATHS = Object.freeze({
  root: ROOT,
  repoRoot: REPO_ROOT,
  spec: path.join(ROOT, 'SPEC.md'),
  readme: path.join(ROOT, 'README.md'),
  binDir: path.join(ROOT, 'bin'),
  libDir: path.join(ROOT, 'lib'),
  binstub: path.join(ROOT, 'bin', 'dsh-update.ps1'),
  stateDir: path.join(ROOT, 'state'),
  pin: path.join(ROOT, 'state', 'pin.json'),
  baselineDir: path.join(ROOT, 'state', 'baseline'),
  baselineContract: path.join(ROOT, 'state', 'baseline', 'contract.json'),
  baselineTree: path.join(ROOT, 'state', 'baseline', 'tree.json'),
  candidatesDir: path.join(ROOT, 'state', 'candidates'),
  historyDir: path.join(ROOT, 'state', 'history'),
  historyFile: path.join(ROOT, 'state', 'history', 'events.tsv'),
  logsDir: path.join(ROOT, 'state', 'logs'),
  vendorDir: path.join(ROOT, 'vendor'),
  prefixRoot: path.join(ROOT, 'vendor', 'prefix'),
  overlayDir: path.join(ROOT, 'vendor', 'overlay'),
  windowsJson: windowsJsonPath(),
  dshHome: dshHome(),
  // the well-known npx install of this deployment (a fast path, never the only path)
  npxInstallRoot: path.join(localAppData(), 'npm-cache', '_npx', '1e7f6d9597241db0'),
});

/** Per-candidate artifact paths. `version` is validated by assertSafeVersion below. */
export function candidateDir(version) {
  return path.join(PATHS.candidatesDir, assertSafeVersion(version));
}

export function candidatePaths(version) {
  const dir = candidateDir(version);
  return {
    dir,
    contract: path.join(dir, 'contract.json'),
    tree: path.join(dir, 'tree.json'),
    diff: path.join(dir, 'diff.json'),
    report: path.join(dir, 'report.md'),
    verify: path.join(dir, 'verify.json'),
  };
}

export function vendorPrefixPath(version) {
  return path.join(PATHS.prefixRoot, assertSafeVersion(version));
}

/** A version string is used as a directory name; refuse anything that could escape a prefix. */
export function assertSafeVersion(version) {
  const v = String(version ?? '').trim();
  if (!v || v === '.' || v === '..' || /[\\/]/.test(v) || v.includes('..') || !/^[0-9A-Za-z][0-9A-Za-z.+_-]*$/.test(v)) {
    throw new Error(`unsafe version string ${JSON.stringify(version)}: expected something like 0.1.5-rc.3`);
  }
  return v;
}

export function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

// ── hashes ──────────────────────────────────────────────────────────────────

export function sha256Text(text) {
  return crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');
}

export function sha256File(file) {
  try {
    return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  } catch {
    return null;
  }
}

/** sha256 of a file, or null when it does not exist. Never throws. */
export function fileInfo(file) {
  try {
    const st = fs.statSync(file);
    return { path: file, exists: true, bytes: st.size, mtime: st.mtime.toISOString(), sha256: sha256File(file) };
  } catch {
    return { path: file, exists: false, bytes: null, mtime: null, sha256: null };
  }
}

// ── atomic IO ───────────────────────────────────────────────────────────────

function tempSibling(target) {
  const stamp = `${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${target}.tmp-${stamp}`;
}

/** Write bytes to `target` via temp file + fsync + rename. Never leaves a half-written artifact. */
function atomicWrite(target, bytes) {
  ensureDir(path.dirname(target));
  const tmp = tempSibling(target);
  let fd = null;
  try {
    fd = fs.openSync(tmp, 'wx');
    fs.writeFileSync(fd, bytes);
    fs.fsyncSync(fd);
  } finally {
    if (fd !== null) fs.closeSync(fd);
  }
  fs.renameSync(tmp, target); // rename over the target is the atomic step
  return target;
}

export function readJson(file, fallback = null) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    return fallback;
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    return fallback;
  }
}

/**
 * Read a JSON file and say what happened — for the CLI, where "absent" and "corrupt" are different
 * facts and an empty read must never look like health (invariant 8).
 */
export function readJsonChecked(file, fallback = null) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    return { ok: false, exists: false, reason: `not present (${err.code || 'read error'})`, value: fallback, path: file };
  }
  try {
    return { ok: true, exists: true, reason: null, value: JSON.parse(raw), path: file, sha256: sha256Text(raw) };
  } catch (err) {
    return { ok: false, exists: true, reason: `present but does not parse as JSON: ${err.message}`, value: fallback, path: file };
  }
}

export function writeJsonAtomic(file, value, { indent = 2 } = {}) {
  return atomicWrite(file, `${JSON.stringify(value, null, indent)}\n`);
}

export function writeTextAtomic(file, text) {
  return atomicWrite(file, String(text));
}

export function utcStamp(date = new Date()) {
  const d = date instanceof Date ? date : new Date(date);
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}T${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}Z`;
}

/**
 * Back up an existing file next to itself, then atomically replace it.
 *
 * Outside dsh-update/ this is the ONLY permitted way to write (invariant 4). If the target does not
 * exist we say so in the returned record — we never claim a backup we did not make.
 */
export function backupAndWrite(target, value, { asText = false, indent = 2 } = {}) {
  const exists = fs.existsSync(target);
  let backup = null;
  if (exists) {
    const base = `${target}.bak-dsh-update-${utcStamp()}`;
    backup = base;
    let n = 1;
    while (fs.existsSync(backup)) backup = `${base}-${n++}`;
    ensureDir(path.dirname(target));
    fs.copyFileSync(target, backup);
  }
  const bytes = asText
    ? String(value)
    : `${JSON.stringify(value, null, indent)}\n`;
  atomicWrite(target, bytes);
  return {
    target,
    existed: exists,
    backup,
    backedUp: backup !== null,
    note: backup ? `previous contents copied to ${backup}` : 'target did not exist: no backup was made (nothing to back up)',
    bytes: Buffer.byteLength(bytes),
    sha256: sha256Text(bytes),
    writtenAt: new Date().toISOString(),
  };
}

// ── host ────────────────────────────────────────────────────────────────────

export function hostName() {
  if (process.platform === 'win32') return process.env.COMPUTERNAME || os.hostname();
  return os.hostname();
}

// ── the pin ─────────────────────────────────────────────────────────────────

export const PIN_KEYS = Object.freeze([
  'version', 'installRoot', 'enginePath', 'managed', 'pinnedAt', 'by',
  'contractSha256', 'treeSha256', 'predecessor',
]);

export function readPin() {
  return readJson(PATHS.pin, null);
}

export function validatePin(pin) {
  const problems = [];
  if (!pin || typeof pin !== 'object') return { ok: false, problems: ['pin.json is absent or not an object'] };
  for (const key of PIN_KEYS) {
    if (!(key in pin)) problems.push(`missing key '${key}'`);
  }
  if (typeof pin.version !== 'string' || !pin.version) problems.push("'version' must be a non-empty string");
  if (typeof pin.enginePath !== 'string' || !pin.enginePath) problems.push("'enginePath' must be a non-empty string");
  if (typeof pin.managed !== 'boolean') problems.push("'managed' must be a boolean");
  return { ok: problems.length === 0, problems };
}

export function writePin(pin) {
  const v = validatePin(pin);
  if (!v.ok) throw new Error(`refusing to write a pin that does not match the SPEC schema: ${v.problems.join('; ')}`);
  return writeJsonAtomic(PATHS.pin, pin);
}

// ── append-only history ─────────────────────────────────────────────────────

export const HISTORY_HEADER = ['timestamp', 'host', 'verb', 'version', 'fromVersion', 'result', 'detail'].join('\t');

function tsvField(value) {
  return String(value ?? '')
    .replace(/[\t\r\n]+/g, ' ')
    .trim();
}

/**
 * Append one audit row. Append only — this function can never rewrite or truncate the ledger
 * (invariant 6); it opens the file with 'a' and nothing else.
 */
export function appendHistory(event) {
  ensureDir(PATHS.historyDir);
  if (!fs.existsSync(PATHS.historyFile)) {
    fs.appendFileSync(PATHS.historyFile, `${HISTORY_HEADER}\n`, 'utf8');
  }
  const row = [
    tsvField(event.timestamp || new Date().toISOString()),
    tsvField(event.host || hostName()),
    tsvField(event.verb),
    tsvField(event.version),
    tsvField(event.fromVersion),
    tsvField(event.result),
    tsvField(event.detail),
  ].join('\t');
  fs.appendFileSync(PATHS.historyFile, `${row}\n`, 'utf8');
  return row;
}

export function readHistory({ limit = null } = {}) {
  const info = fileInfo(PATHS.historyFile);
  if (!info.exists) return { exists: false, header: HISTORY_HEADER, rows: [], lines: 0, first: null, last: null };
  const raw = fs.readFileSync(PATHS.historyFile, 'utf8');
  const lines = raw.split(/\r?\n/).filter((l) => l.length > 0);
  const header = lines[0] || HISTORY_HEADER;
  const rows = lines.slice(1).map((line) => {
    const f = line.split('\t');
    return {
      timestamp: f[0] ?? '', host: f[1] ?? '', verb: f[2] ?? '', version: f[3] ?? '',
      fromVersion: f[4] ?? '', result: f[5] ?? '', detail: f.slice(6).join(' '),
    };
  });
  return {
    exists: true, header, lines: lines.length, first: rows[0] ?? null, last: rows[rows.length - 1] ?? null,
    rows: limit ? rows.slice(-limit) : rows,
  };
}

// ── invocation logs ─────────────────────────────────────────────────────────

/**
 * Write a verbatim record of one invocation under state/logs/. Both streams are stored exactly as
 * they were produced: a reading is only reproducible if the raw bytes survive.
 */
export function logInvocation(name, { argv = [], stdout = '', stderr = '', exitCode = null, durationMs = null } = {}) {
  ensureDir(PATHS.logsDir);
  const stem = `${utcStamp()}-${String(name).replace(/[^0-9A-Za-z_-]+/g, '-')}-pid${process.pid}`;
  const stdoutPath = path.join(PATHS.logsDir, `${stem}.stdout.txt`);
  const stderrPath = path.join(PATHS.logsDir, `${stem}.stderr.txt`);
  if (stdout) writeTextAtomic(stdoutPath, stdout);
  if (stderr) writeTextAtomic(stderrPath, stderr);
  const record = {
    name,
    argv,
    command: ['node', 'lib/cli.mjs', ...argv].join(' '),
    host: hostName(),
    pid: process.pid,
    node: process.version,
    exitCode,
    durationMs,
    startedAt: new Date(Date.now() - (durationMs ?? 0)).toISOString(),
    wroteAt: new Date().toISOString(),
    stdoutPath: stdout ? stdoutPath : null,
    stderrPath: stderr ? stderrPath : null,
    stdoutBytes: Buffer.byteLength(stdout || ''),
    stderrBytes: Buffer.byteLength(stderr || ''),
  };
  writeJsonAtomic(path.join(PATHS.logsDir, `${stem}.json`), record);
  return record;
}

// ── recorded paths ──────────────────────────────────────────────────────────

/** A path as it should appear inside an artifact: relative to the repo when under it, else absolute. */
export function safeRelPath(p) {
  if (!p) return '';
  const abs = path.resolve(String(p));
  const rel = path.relative(REPO_ROOT, abs);
  const inside = rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
  return (inside ? rel : abs).split(path.sep).join('/');
}
