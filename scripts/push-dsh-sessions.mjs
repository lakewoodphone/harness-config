#!/usr/bin/env node
/**
 * push-dsh-sessions.mjs — ship every DSH session from this machine to the secretary, so no
 * conversation is ever only on one laptop.
 *
 * The equivalent for VS Code Copilot chats is `scripts/push_vscode_chats.py` + the hourly
 * `PersonalSecretary-PushVSCodeChats` task. This is the same idea for this harness, and it mirrors that
 * pipeline's contract deliberately: plain JSON over HTTPS, a bearer-style token header, batched, and
 * idempotent server-side.
 *
 * ── What it ships, and what it deliberately does not do ──────────────────────────────────────────
 *
 * It ships **durable rows verbatim**. A session file is one zstd frame per append batch, and each frame
 * decompresses to newline-delimited JSON: a header line then one row per durable event. Rows are copied
 * out as they are, with the sequence number lifted out for the index, and nothing is interpreted.
 *
 * That is a deliberate limit, not laziness. The format has interpretable structure — `*-chunks` rows
 * pack many events, surfaces fold into a conversation — and the official code that understands it is not
 * exported by the installed packages (only the Cordis plugin is). Re-implementing the projection would
 * be exactly the confident-wrongness this journal keeps paying for (PAIN P22, LESSONS L51). Shipping
 * rows verbatim is **lossless**: any reader that needs the projection can run the official fold over
 * the rows later, from one place, on the authority. Guessing at it here would not be recoverable.
 *
 * Three traps it does handle, because they are about *reading bytes* rather than about meaning:
 *   1. a session file is MANY zstd frames — a one-shot decompress returns only the first one;
 *   2. a torn final frame is a normal crash boundary, not corruption — it is skipped and reported;
 *   3. an uncompressed `.jsonl` (the headless profile writes those) is read as-is.
 *
 * ── Cursor ───────────────────────────────────────────────────────────────────────────────────────
 *
 * `~/.dsh/dsh-archive-state.json` holds, per session, `{ rowsShipped, bytes, lastRow }`. The cursor is a
 * **row count plus a byte mark**, never a wall-clock timestamp: this file is appended to, and a clock
 * cursor silently loses anything written while the clock moves backwards or the file is rewritten
 * (docs/dsh-mobile/00-RESEARCH.md §9). Re-sending is free because the server upserts on
 * (machine, session, seq) — at-least-once delivery is the contract.
 *
 * Usage:
 *   node push-dsh-sessions.mjs --dry-run            # what would be sent, and why nothing else is
 *   node push-dsh-sessions.mjs                      # ship
 *   node push-dsh-sessions.mjs --all --dry-run      # ignore the cursor, re-examine everything
 *   node push-dsh-sessions.mjs --verbose
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';

const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

const args = process.argv.slice(2);
const has = (f) => args.includes(f);
const opt = (f, d) => { const i = args.indexOf(f); return i === -1 ? d : args[i + 1]; };

const DRY = has('--dry-run');
const ALL = has('--all');
const VERBOSE = has('--verbose');

const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
const SESSIONS_ROOT = path.join(DSH_HOME, 'sessions');
const STATE_PATH = path.join(DSH_HOME, 'dsh-archive-state.json');
const MACHINE = (process.env.DSH_ARCHIVE_MACHINE || os.hostname()).toLowerCase();
const BATCH_SESSIONS = 100;
const BATCH_BYTES = 4 * 1024 * 1024;
// A transport must never be able to hang a scheduled job forever (see postBatch).
const SSH_TIMEOUT_MS = Number(process.env.DSH_ARCHIVE_SSH_TIMEOUT_MS || 240000);
const transportNotes = {};

// Two transports, same payload:
//   ssh  (default) — pipe the batch into the importer on the authority. Works today.
//   http            — POST to the in-app endpoint. Staged but NOT deployed: the
//                     authority's company checkout is 51 commits behind with
//                     hand-edited app/main.py, so the endpoint is not live yet.
const TRANSPORT = opt('--transport', process.env.DSH_ARCHIVE_TRANSPORT || 'ssh').toLowerCase();
const SSH_HOST = process.env.DSH_ARCHIVE_SSH_HOST || 'secretary-ts';
const IMPORTER = process.env.DSH_ARCHIVE_IMPORTER || '/home/zabz/harness-config/scripts/dsh-archive-import.py';
const ENDPOINT = process.env.DSH_ARCHIVE_ENDPOINT
  || 'https://api.abletelsolutions.com/api/v1/owner/dsh-sessions/ingest';
const TOKEN = process.env.DSH_ARCHIVE_TOKEN || '';

// ── reading bytes ───────────────────────────────────────────────────────────────────────────────

/** Split a session artifact into its concatenated zstd frames and decode each one in order. */
function decodeFrames(buffer) {
  const offsets = [];
  let i = 0;
  while ((i = buffer.indexOf(ZSTD_MAGIC, i)) !== -1) { offsets.push(i); i += 4; }
  offsets.push(buffer.length);

  const parts = [];
  let decoded = 0;
  let tornStart = null;
  for (let k = 0; k < offsets.length - 1; k++) {
    let ok = false;
    for (let j = k + 1; j < Math.min(k + 6, offsets.length); j++) {
      try {
        parts.push(zlib.zstdDecompressSync(buffer.subarray(offsets[k], offsets[j])));
        k = j - 1; decoded++; ok = true; break;
      } catch { /* widen the window: a magic sequence can occur inside compressed data */ }
    }
    if (!ok) { tornStart = offsets[k]; break; }   // an incomplete final frame
  }
  return { text: Buffer.concat(parts).toString('utf8'), frames: offsets.length - 1, decoded, tornStart };
}

function readSession(file) {
  const buffer = fs.readFileSync(file);
  const compressed = file.endsWith('.zstd');
  const { text, frames, decoded, tornStart } = compressed
    ? decodeFrames(buffer)
    : { text: buffer.toString('utf8'), frames: 1, decoded: 1, tornStart: null };

  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  let header = null;
  const rows = [];
  for (const line of lines) {
    let obj;
    try { obj = JSON.parse(line); } catch { continue; }   // never guess at a malformed line
    if (!header && (obj.type === 'session' || obj.sessionId)) { header = obj; continue; }
    rows.push({ seq: typeof obj.seq === 'number' ? obj.seq : null, type: String(obj.type || 'unknown'), raw: line });
  }
  return { header, rows, frames, decoded, tornStart, bytes: buffer.length };
}

// ── discovery ───────────────────────────────────────────────────────────────────────────────────

function discover() {
  const out = [];
  if (!fs.existsSync(SESSIONS_ROOT)) return out;
  for (const project of fs.readdirSync(SESSIONS_ROOT)) {
    const projectDir = path.join(SESSIONS_ROOT, project);
    if (!fs.statSync(projectDir).isDirectory()) continue;
    for (const session of fs.readdirSync(projectDir)) {
      const dir = path.join(projectDir, session);
      if (!fs.statSync(dir).isDirectory()) continue;
      // the newest generation wins; a session may have older generations beside it
      const logs = fs.readdirSync(dir).filter((f) => /^session\.v\d+\.jsonl(\.zstd)?$/.test(f))
        .sort((a, b) => Number(b.match(/v(\d+)/)[1]) - Number(a.match(/v(\d+)/)[1]));
      if (!logs.length) continue;
      const file = path.join(dir, logs[0]);
      out.push({ project, session: session.replace(/^session-/, ''), file, mtime: fs.statSync(file).mtimeMs });
    }
  }
  return out.sort((a, b) => a.mtime - b.mtime);
}

// ── state ───────────────────────────────────────────────────────────────────────────────────────

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); } catch { return { version: 1, machine: MACHINE, sessions: {} }; }
}
function saveState(state) {
  state.machine = MACHINE;
  state.savedAt = new Date().toISOString();
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}
const key = (s) => `${s.project}/${s.session}`;

// ── shipping ────────────────────────────────────────────────────────────────────────────────────

async function postBatch(payload) {
  const body = JSON.stringify(payload);

  if (TRANSPORT === 'http') {
    if (!TOKEN) throw new Error('no token: set DSH_ARCHIVE_TOKEN (or use --dry-run)');
    const res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-ps-dsh-session-ingest-token': TOKEN },
      body,
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`ingest ${res.status}: ${text.slice(0, 300)}`);
    return text;
  }

  // ssh: the importer reads the batch on stdin and prints one JSON summary line.
  //
  // Two hard-won details, both measured on ZABZ-TECH on 2026-09-11:
  //
  //  1. **A timeout is mandatory.** Node-spawned ssh on that machine returns the remote command's
  //     output and then never exits — the first real run there hung for 10 minutes producing nothing.
  //     The same call from the Yoga exits in ~1 s, same ssh binary and version, so it is not the
  //     config, not the binary, and not the network. Without a bound, a scheduled job stalls forever.
  //
  //  2. **A timed-out transport whose reply already parsed is a SUCCESS, not a failure.** The importer
  //     prints its summary only after `conn.commit()`, so a valid `{"ok":true,…}` on stdout means the
  //     rows are durable. Treating it as failure would re-send the same megabytes every hour and the
  //     desktop's sessions would never be archived at all. spawnSync kills the child on timeout, so
  //     nothing is orphaned; the quirk is noted in the run output rather than hidden.
  const r = spawnSync('ssh', ['-T', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', SSH_HOST, 'python3', IMPORTER], {
    input: body,
    encoding: 'utf8',
    maxBuffer: 128 * 1024 * 1024,
    timeout: SSH_TIMEOUT_MS,
  });

  const line = String(r.stdout || '').trim().split('\n').filter(Boolean).pop() || '';
  let parsed = null;
  try { parsed = JSON.parse(line); } catch { /* reported below */ }

  const timedOut = Boolean(r.error && (r.error.code === 'ETIMEDOUT' || r.signal === 'SIGTERM'));
  if (timedOut) {
    if (parsed && parsed.ok) {
      transportNotes.timedOutButCommitted = (transportNotes.timedOutButCommitted || 0) + 1;
      return JSON.stringify(parsed);
    }
    throw new Error(`ssh timed out after ${SSH_TIMEOUT_MS} ms with no valid importer reply`);
  }
  if (r.error) throw new Error('ssh spawn failed: ' + r.error.message);
  if (r.status !== 0) throw new Error(`importer exit ${r.status}: ${String(r.stderr || '').slice(0, 300)}`);
  if (!parsed) throw new Error('unparseable importer reply: ' + line.slice(0, 200));
  if (!parsed.ok) throw new Error('importer refused: ' + JSON.stringify(parsed).slice(0, 200));
  return JSON.stringify(parsed);
}

async function main() {
  const state = loadState();
  const found = discover();
  if (found.length === 0) { console.log('no sessions found under ' + SESSIONS_ROOT); return 0; }

  console.log(`machine : ${MACHINE}`);
  console.log(`sessions: ${found.length} on disk`);
  console.log(`endpoint: ${DRY ? '(dry run — nothing sent)' : ENDPOINT}`);
  console.log('');

  let sessionsSent = 0, rowsSent = 0, skipped = 0, torn = 0, bytesSent = 0;
  let batch = { sessions: [] };
  let batchBytes = 0;
  // Cursor updates wait until the batch containing them has been ACCEPTED. Advancing a cursor before
  // the server holds the rows is how a shipper silently loses data it believes it already sent.
  let pendingCursor = [];

  const flush = async () => {
    if (batch.sessions.length === 0) { return; }
    if (!DRY) {
      const body = { source_machine: MACHINE, exported_at: new Date().toISOString(), schema_version: 1, sessions: batch.sessions };
      const reply = await postBatch(body);
      if (VERBOSE) console.log('   reply:', reply.slice(0, 160));
      for (const u of pendingCursor) state.sessions[u.k] = u.v;
    }
    batch = { sessions: [] }; batchBytes = 0; pendingCursor = [];
  };

  for (const s of found) {
    const decoded = readSession(s.file);
    const k = key(s);
    const prev = state.sessions[k] || { rowsShipped: 0, bytes: 0 };
    const startRow = ALL ? 0 : prev.rowsShipped;

    if (!ALL && decoded.rows.length <= startRow && prev.bytes === decoded.bytes) { skipped++; continue; }

    const newRows = decoded.rows.slice(startRow);
    if (decoded.tornStart !== null) torn++;

    const payload = {
      session_id: s.session,
      project: s.project,
      header: decoded.header,
      file: path.basename(s.file),
      file_bytes: decoded.bytes,
      frames: decoded.frames,
      torn_tail: decoded.tornStart !== null,
      total_rows: decoded.rows.length,
      start_row: startRow,
      rows: newRows,
    };
    const size = JSON.stringify(payload).length;

    if (VERBOSE || DRY) {
      console.log(`  ${DRY ? 'would send' : 'sending'} ${s.project}/${s.session.slice(0, 8)}  ` +
        `rows ${startRow}..${decoded.rows.length} (${newRows.length} new), ${decoded.frames} frames` +
        `${decoded.tornStart !== null ? ', TORN TAIL' : ''}, ${Math.round(size / 1024)} KB`);
    }
    batch.sessions.push(payload);
    batchBytes += size;
    sessionsSent++;
    rowsSent += newRows.length;
    bytesSent += size;

    // queued, not applied: flush() commits these only once the server has accepted the batch
    pendingCursor.push({
      k,
      v: {
        rowsShipped: decoded.rows.length,
        bytes: decoded.bytes,
        lastRow: newRows.length ? newRows[newRows.length - 1].seq : (prev.lastRow ?? null),
        at: new Date().toISOString(),
      },
    });

    if (batch.sessions.length >= BATCH_SESSIONS || batchBytes >= BATCH_BYTES) await flush();
  }
  await flush();

  if (!DRY) saveState(state);

  console.log('');
  console.log(`${DRY ? 'would ship' : 'shipped'}: ${sessionsSent} session(s), ${rowsSent} new row(s), ${Math.round(bytesSent / 1024)} KB`);
  if (skipped) console.log(`unchanged  : ${skipped} session(s) already complete (cursor)`);
  if (torn) console.log(`torn tail  : ${torn} session(s) ended mid-frame — skipped, which is normal`);
  if (transportNotes.timedOutButCommitted) {
    console.log(`transport  : ${transportNotes.timedOutButCommitted} batch(es) committed by the importer although ssh did not exit on this machine — see postBatch`);
  }
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => { console.error('error: ' + e.message); process.exit(1); });
