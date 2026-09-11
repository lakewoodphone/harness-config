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
import { spawn } from 'node:child_process';
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
// Rows per request: small enough that one session never has to finish inside a single HTTP deadline.
const BATCH_ROWS = Number(process.env.DSH_ARCHIVE_BATCH_ROWS || 300);
// A transport must never be able to hang a scheduled job forever (see postBatch).
const SSH_TIMEOUT_MS = Number(process.env.DSH_ARCHIVE_SSH_TIMEOUT_MS || 240000);
// Pause between requests, so a backfill cannot stampede a database the company writes to continuously.
const PACE_MS = Number(process.env.DSH_ARCHIVE_PACE_MS || 250);
// Retry patience, measured rather than guessed (2026-09-11 21:45): the authority answered
// `500 {"error":"internal_error"}` for this machine for **two and a half hours** — 20:05, 21:05 and
// 21:45 runs — while the app's journal held the actual cause, `sqlite3.OperationalError: database is
// locked` on the ingest's first INSERT. The old policy was 2 attempts 3 s apart, ~63 s of patience;
// the ingesting connection itself waits 30 s for the lock, so a writer that held it for a minute
// outlived the whole retry budget and the run aborted. The cursor stayed correct (it only advances on
// an accepted batch, so nothing was lost), but this machine's archive silently stopped at 19:19.
// Patience is the fix: back off far enough to outlast a checkpoint or a long transaction.
const RETRY_DELAYS_MS = (process.env.DSH_ARCHIVE_RETRY_MS
  ? [Number(process.env.DSH_ARCHIVE_RETRY_MS), Number(process.env.DSH_ARCHIVE_RETRY_MS) * 3,
     Number(process.env.DSH_ARCHIVE_RETRY_MS) * 9]
  : [5000, 15000, 45000]);
// A hung request must not idle an hourly task forever: fetch() has no timeout of its own.
const POST_TIMEOUT_MS = Number(process.env.DSH_ARCHIVE_POST_TIMEOUT_MS || 120000);
const transportNotes = {};

// ── transports, one payload ─────────────────────────────────────────────────────────────────────
//
//   http   (default) — POST to the company's own ingest endpoint. This is the intended home: the rows
//                      land in the authoritative `secretary.db`, written by the app that owns that
//                      database, so there is no second writer and no separate store to keep in step.
//                      Live since 2026-09-11 19:16 (the route is additive on the production checkout).
//   scp              — the interim path: copy the batch to the authority and import it there. Kept as a
//                      fallback for when the API is down, and it is what fills the standalone archive.
//   local            — for the archive host itself.
//   ssh / stdin      — legacy, for hosts without scp.
const TRANSPORT = opt('--transport', process.env.DSH_ARCHIVE_TRANSPORT || 'http').toLowerCase();
const SSH_HOST = process.env.DSH_ARCHIVE_SSH_HOST || 'secretary-ts';
const IMPORTER = process.env.DSH_ARCHIVE_IMPORTER || '/home/zabz/harness-config/scripts/dsh-archive-import.py';
const REMOTE_INCOMING = process.env.DSH_ARCHIVE_INCOMING || '/home/zabz/dsh-archive/incoming';
const ENDPOINT = process.env.DSH_ARCHIVE_ENDPOINT
  || 'https://api.abletelsolutions.com/api/v1/owner/dsh-sessions/ingest';

/** The ingest token: environment first, then the repo `.env` the fleet already keeps secrets in.
 *
 * Secrets belong in files, not in scheduled-task arguments -- a token on a command line is visible to
 * every process on the machine, which is the same mistake as putting one in a log line (LESSONS L44).
 * This mirrors how `push_vscode_chats.py` already finds its own ingest token.
 */
function ingestToken() {
  if (process.env.DSH_ARCHIVE_TOKEN) return process.env.DSH_ARCHIVE_TOKEN.trim();
  // The workstations keep the repo under ~/code (or ~/Code); the always-on Linux host keeps it directly
  // in the home directory. Hard-coding only the Windows shape is how the authority's first backfill
  // failed with 'no token' while the workstations worked.
  const candidates = [
    path.join(os.homedir(), 'code', 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'Code', 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'personal-secretary-mvp', '.env'),
  ];
  for (const file of candidates) {
    try {
      const line = fs.readFileSync(file, 'utf8').split('\n').find((l) => l.startsWith('DSH_SESSION_INGEST_TOKEN='));
      if (line) return line.slice('DSH_SESSION_INGEST_TOKEN='.length).trim().replace(/^["']|["']$/g, '');
    } catch { /* try the next */ }
  }
  return '';
}
const TOKEN = ingestToken();

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

/** Run a command whose reply is small and may be followed by an ssh that never exits.
 *
 * The child is killed the moment the requested reply parses, because:
 *  - ssh does not reliably exit after the remote command completes (seen on both workstations);
 *  - the importer prints its summary only after `conn.commit()`, so a parsed reply means durable.
 * Waiting for exit costs the full timeout per call; killing early costs nothing.
 */
function runForReply(cmd, cmdArgs, { parse = true, input = undefined, timeoutMs = SSH_TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, cmdArgs);
    let out = '';
    let err = '';
    let settled = false;
    const finish = (fn, arg) => { if (!settled) { settled = true; clearTimeout(timer); fn(arg); } };
    const timer = setTimeout(() => { child.kill(); finish(reject, new Error(`${cmd} exceeded ${timeoutMs} ms`)); }, timeoutMs);

    const lastLine = () => String(out).trim().split('\n').filter(Boolean).pop() || '';
    const reply = () => { try { return JSON.parse(lastLine()); } catch { return null; } };

    child.stdout.on('data', (chunk) => {
      out += chunk;
      if (!parse) return;
      const parsed = reply();
      if (parsed) {
        child.kill();
        transportNotes.killedAfterReply = (transportNotes.killedAfterReply || 0) + 1;
        finish(resolve, parsed);
      }
    });
    child.stderr.on('data', (chunk) => { err += chunk; });
    child.on('error', (e) => finish(reject, new Error(`${cmd} spawn failed: ${e.message}`)));
    child.on('close', (code) => {
      if (settled) return;
      if (parse) {
        const parsed = reply();
        if (parsed) return finish(resolve, parsed);
        return finish(reject, new Error(`${cmd} exit ${code}: ${String(err).slice(0, 300) || lastLine().slice(0, 200) || 'no reply'}`));
      }
      if (code === 0) return finish(resolve, out);
      finish(reject, new Error(`${cmd} exit ${code}: ${String(err).slice(0, 300)}`));
    });
    if (input !== undefined) child.stdin.end(input); else child.stdin.end();
  });
}

async function postBatch(payload) {
  const body = JSON.stringify(payload);

  if (TRANSPORT === 'http') {
    if (!TOKEN) throw new Error('no token: set DSH_ARCHIVE_TOKEN (or use --dry-run)');
    // Retry with backoff. Not superstition: the 500s above are transient write-lock contention on the
    // authority, not a refusal, and a batch that throws is a batch the cursor refuses to skip -- so an
    // unlucky minute must not be allowed to abort a whole run (or, worse, a whole backfill).
    let lastError = '';
    for (let attempt = 0; ; attempt++) {
      let res = null, text = '';
      try {
        res = await fetch(ENDPOINT, {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-ps-dsh-session-ingest-token': TOKEN },
          body,
          signal: AbortSignal.timeout(POST_TIMEOUT_MS),
        });
        text = await res.text();
      } catch (e) {
        lastError = `ingest transport: ${String(e && e.message || e)}`;
      }
      if (res && res.ok) return text;
      if (res) lastError = `ingest ${res.status}: ${text.slice(0, 300)}`;
      // 5xx and 429 are the retryable answers; a 4xx is a refusal, and repeating it is noise.
      const retryable = !res || res.status >= 500 || res.status === 429;
      if (!retryable || attempt >= RETRY_DELAYS_MS.length) break;
      const wait = res && res.status === 429
        ? (Number(res.headers.get('retry-after') || 0) * 1000 || RETRY_DELAYS_MS[attempt])
        : RETRY_DELAYS_MS[attempt];
      console.log(`   retry ${attempt + 1}/${RETRY_DELAYS_MS.length} in ${Math.round(wait / 1000)}s — ${lastError.slice(0, 120)}`);
      await new Promise((r) => setTimeout(r, wait));
    }
    throw new Error(lastError);
  }

  // ── local (for the archive host itself) ──────────────────────────────────────────────────────
  // The always-on host runs the phone's engine, so IT also has sessions worth keeping. Sending them over
  // ssh to itself would be silly, and copying them would be worse: the file is written next to the
  // importer and imported in place. Same import, same idempotence, no transport.
  if (TRANSPORT === 'local') {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const local = path.join(os.tmpdir(), `dsh-batch-${MACHINE}-${stamp}-${process.pid}.json`);
    fs.writeFileSync(local, body);
    try {
      // same reply-parsing helper as the remote paths: it parses the importer's JSON line and kills the
      // child, so a slow exit can never stall a scheduled run
      const parsed = await runForReply('python3', [IMPORTER, '--file', local]);
      if (!parsed.ok) throw new Error('importer refused: ' + JSON.stringify(parsed).slice(0, 200));
      return JSON.stringify(parsed);
    } finally {
      try { fs.unlinkSync(local); } catch { /* already gone */ }
    }
  }

  // ── scp (default for workstations): write the batch to a file, copy it, import from the file ────
  //
  // Why not stream it over ssh on stdin: on ZABZ-TECH a 4 MB stdin payload into a remote process
  // **stalls indefinitely** (measured: 300 s timeout, three orphaned shippers piled up, nothing
  // shipped), while ZABZ-YOGA ships 73 MB the same way. The difference is the transport under load,
  // not the payload. scp moves the identical 4 MB file from the same machine in **0.3 s** with a
  // matching checksum, so the file path avoids the failure entirely instead of racing it.
  if (TRANSPORT === 'scp') {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const local = path.join(os.tmpdir(), `dsh-batch-${MACHINE}-${stamp}-${process.pid}.json`);
    const remote = `${REMOTE_INCOMING}/${path.basename(local)}`;
    fs.writeFileSync(local, body);
    try {
      await runForReply('scp', ['-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', local, `${SSH_HOST}:${remote}`],
        { parse: false, timeoutMs: SSH_TIMEOUT_MS });
      const parsed = await runForReply('ssh',
        ['-T', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', SSH_HOST, 'python3', IMPORTER, '--file', remote]);
      if (!parsed.ok) throw new Error('importer refused: ' + JSON.stringify(parsed).slice(0, 200));
      // best-effort cleanup; a leftover batch file is re-importable and harmless (the upsert is idempotent)
      runForReply('ssh', ['-T', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', SSH_HOST, 'rm', '-f', remote],
        { parse: false, timeoutMs: 30000 }).catch(() => {});
      return JSON.stringify(parsed);
    } finally {
      try { fs.unlinkSync(local); } catch { /* already gone */ }
    }
  }

  // ── ssh (legacy): stream the batch into the importer on stdin ────────────────────────────────
  // Kept for hosts where scp is unavailable. Equivalent semantics, worse failure mode under load.
  const parsed = await runForReply('ssh',
    ['-T', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', SSH_HOST, 'python3', IMPORTER], { input: body });
  if (!parsed.ok) throw new Error('importer refused: ' + JSON.stringify(parsed).slice(0, 200));
  return JSON.stringify(parsed);
}

async function main() {
  const state = loadState();
  const found = discover();
  if (found.length === 0) { console.log('no sessions found under ' + SESSIONS_ROOT); return 0; }

  console.log(`machine : ${MACHINE}`);
  console.log(`sessions: ${found.length} on disk`);
  console.log(`transport: ${DRY ? '(dry run — nothing sent)' : TRANSPORT}`);
  if (!DRY) {
    const target = TRANSPORT === 'http' ? ENDPOINT
      : TRANSPORT === 'local' ? IMPORTER
      : `${SSH_HOST}:${TRANSPORT === 'scp' ? REMOTE_INCOMING : 'stdin → ' + IMPORTER}`;
    console.log(`target   : ${target}`);
  }
  console.log('');

  let sessionsSent = 0, rowsSent = 0, skipped = 0, torn = 0, bytesSent = 0, totalBatches = 0;
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
      totalBatches++;
      // Pace the requests. The company writes to this database continuously, and a backfill firing a
      // hundred inserts back-to-back is what pushed it into 'database is locked' -- the WAL was sitting
      // at its 64 MiB limit, which is the signature of checkpoint starvation. Incremental hourly runs
      // (a handful of batches) are unaffected; a full backfill no longer stampedes.
      if (PACE_MS > 0 && batch.sessions.length > 0) {
        await new Promise((r) => setTimeout(r, PACE_MS));
      }
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

    // A big session is split into fragments, because the request that carries it has to finish inside
    // the proxy's timeout. Measured 2026-09-11: the Yoga's backfill died twice with a 500 from the
    // public endpoint, and the app's own error log had nothing for it — the failure was the *request*,
    // not the code. One session here is 2,384 rows and ~10 MB; sending it whole asks the server to
    // insert all of it inside one HTTP deadline while the company's autopilot is writing. The protocol
    // already supported fragments (each carries its own `start_row`, and the server's ordinal is
    // `start_row + index`), so the shipper now uses that.
    const fragments = [];
    for (let offset = 0; offset < newRows.length; offset += BATCH_ROWS) {
      fragments.push({ startIndex: startRow + offset, rows: newRows.slice(offset, offset + BATCH_ROWS) });
    }
    if (fragments.length === 0) fragments.push({ startIndex: startRow, rows: [] });

    for (let fi = 0; fi < fragments.length; fi++) {
      const frag = fragments[fi];
      const payload = {
        session_id: s.session,
        project: s.project,
        header: decoded.header,
        file: path.basename(s.file),
        file_bytes: decoded.bytes,
        frames: decoded.frames,
        torn_tail: decoded.tornStart !== null,
        total_rows: decoded.rows.length,
        start_row: frag.startIndex,
        rows: frag.rows,
      };
      const size = JSON.stringify(payload).length;

      if (VERBOSE || DRY) {
        console.log(`  ${DRY ? 'would send' : 'sending'} ${s.project}/${s.session.slice(0, 8)}  ` +
          `rows ${frag.startIndex}..${frag.startIndex + frag.rows.length} of ${decoded.rows.length}, ` +
          `${decoded.frames} frames${decoded.tornStart !== null ? ', TORN TAIL' : ''}, ${Math.round(size / 1024)} KB`);
      }
      batch.sessions.push(payload);
      batchBytes += size;
      rowsSent += frag.rows.length;
      bytesSent += size;

      // The cursor advances only with the session's LAST fragment, so a session interrupted between
      // fragments is re-sent whole next run rather than being marked done with a hole in it.
      if (fi === fragments.length - 1) {
        pendingCursor.push({
          k,
          v: {
            rowsShipped: decoded.rows.length,
            bytes: decoded.bytes,
            lastRow: newRows.length ? newRows[newRows.length - 1].seq : (prev.lastRow ?? null),
            at: new Date().toISOString(),
          },
        });
      }

      if (batch.sessions.length >= BATCH_SESSIONS || batchBytes >= BATCH_BYTES) await flush();
    }
    sessionsSent++;
  }
  await flush();

  if (!DRY) saveState(state);

  console.log('');
  console.log(`${DRY ? 'would ship' : 'shipped'}: ${sessionsSent} session(s), ${rowsSent} new row(s), ${Math.round(bytesSent / 1024)} KB`);
  if (skipped) console.log(`unchanged  : ${skipped} session(s) already complete (cursor)`);
  if (torn) console.log(`torn tail  : ${torn} session(s) ended mid-frame — skipped, which is normal`);
  if (transportNotes.killedAfterReply) {
    console.log(`transport  : ${transportNotes.killedAfterReply} batch(es) ended by killing the child once its reply parsed (this host's transport does not always exit on its own) — see postBatch`);
  }
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => { console.error('error: ' + e.message); process.exit(1); });
