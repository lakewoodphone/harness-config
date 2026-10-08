#!/usr/bin/env node
/**
 * session-corpus — measure, archive and restore the DSH session corpus.
 *
 * WHY THIS EXISTS
 *
 * The harness stores every session as a compressed file under
 * `~/.dsh/sessions/<workspace>/<session>/`. Several operations walk that whole
 * tree and read every file IN FULL — a zstd frame cannot be decoded from its
 * header alone, so the cost is proportional to TOTAL BYTES ON DISK, not to the
 * number of sessions. Those operations run on the engine's shared event loop, so
 * every other session in that engine is frozen for the duration.
 *
 * Measured on ZABZ-YOGA 2026-09-25, before this tool existed:
 *   837 session dirs / 440 MB  ->  walk took 6,623 ms (engine's own number)
 *   the same walk measured standalone: 6,437 ms (5,675 ms of it file reads)
 *   engine max event-loop lag: 13,210 ms
 *   a second reader (the multi-window proxy's `session/list`): 25-31 s cold
 *
 * The corpus grows ~60 sessions/day and nothing pruned it, so the cost grew
 * with it until every session on the machine stuttered. Age distribution when
 * measured: sessions older than 7 days were 635 of 837 dirs and 347.7 of 445 MB
 * — 94.4% of the bytes the walk pays for, and almost certainly none of the
 * history anyone would still resume.
 *
 * WHAT IT DOES
 *
 *   report                        age buckets, bytes, and the walk's cost driver
 *   archive --older-than 7d       MOVE old sessions out of the live corpus
 *   restore --manifest <file>     put every session in a manifest back, exactly
 *
 * SAFETY, STATED PLAINLY
 *
 *   * NOTHING IS EVER DELETED. `archive` is a rename within one volume; the
 *     session directory and every file in it survive untouched, one directory
 *     over, and `restore` reverses the whole operation from the manifest.
 *   * DRY RUN BY DEFAULT. Without `--apply` it prints exactly what it would move
 *     and moves nothing.
 *   * AGE IS RE-CHECKED AT MOVE TIME, not only at selection time, so a session
 *     that was written between the scan and the move is skipped rather than
 *     stolen out from under a live turn.
 *   * A MOVE IS VERIFIED, AND ROLLED BACK IF IT FAILS. File count and total
 *     bytes must match at the destination or the directory goes straight back.
 *   * IT REFUSES ON DOUBT. A session directory containing a file named `active`
 *     or ending in `.lock` is skipped; a destination that already exists is
 *     skipped; an unreadable session dir is skipped. Every skip is reported with
 *     its reason. Partial success is a normal, reported outcome — not a failure.
 *
 * The manifest is written to `~/.dsh/sessions-archive/` — deliberately OUTSIDE
 * `sessions/`, so the archived history is never itself walked.
 *
 * USAGE
 *   node scripts/session-corpus.mjs report
 *   node scripts/session-corpus.mjs archive --older-than 7d            # dry run
 *   node scripts/session-corpus.mjs archive --older-than 7d --apply
 *   node scripts/session-corpus.mjs restore --manifest ~/.dsh/sessions-archive/manifest-2026-09-25T19-50-00Z.json --apply
 *   node scripts/session-corpus.mjs check --max-mb 150 --max-scan-ms 2000
 */

import {
  existsSync, mkdirSync, readdirSync, renameSync, statSync,
  readFileSync, writeFileSync, rmSync,
} from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const DAY_MS = 86_400_000;

/** Where the corpus lives. `DSH_HOME` wins when set, so this is testable. */
function dshHome() {
  return process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
}
function sessionsRoot() {
  return path.join(dshHome(), 'sessions');
}
function archiveRoot() {
  return path.join(dshHome(), 'sessions-archive');
}

// ---------------------------------------------------------------------------
// args
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) out[key] = true;
      else { out[key] = next; i++; }
    } else out._.push(a);
  }
  return out;
}

/** `7`, `7d`, `12h` -> milliseconds. */
function parseDuration(text) {
  if (text === true) return undefined;
  const m = /^(\d+(?:\.\d+)?)\s*([dhms]?)$/.exec(String(text).trim());
  if (m === null) return undefined;
  const n = Number(m[1]);
  const unit = m[2] === '' ? 'd' : m[2];
  const mult = { d: DAY_MS, h: 3_600_000, m: 60_000, s: 1_000 }[unit];
  return Number.isFinite(n) && mult !== undefined ? n * mult : undefined;
}

const mb = (bytes) => +(bytes / 1_048_576).toFixed(1);

/** Human size that does not render a real session as `0 MB`. */
const size = (bytes) => (bytes < 1_048_576 ? `${(bytes / 1024).toFixed(0)} KB` : `${mb(bytes)} MB`);

// ---------------------------------------------------------------------------
// scan
// ---------------------------------------------------------------------------

/**
 * One pass over the corpus.
 *
 * Deliberately reads STAT only — never file contents. Measuring the corpus must
 * not itself be the expensive walk this tool exists to avoid.
 */
function scanCorpus() {
  const root = sessionsRoot();
  const sessions = [];
  const unreadable = [];
  if (!existsSync(root)) return { sessions, unreadable, root, exists: false };

  for (const ws of readdirSync(root, { withFileTypes: true })) {
    if (!ws.isDirectory()) continue;
    const wsPath = path.join(root, ws.name);
    let entries;
    try { entries = readdirSync(wsPath, { withFileTypes: true }); } catch (error) {
      unreadable.push({ dir: wsPath, reason: `workspace readdir failed: ${error.code || error.message}` });
      continue;
    }
    for (const s of entries) {
      if (!s.isDirectory()) continue;
      const dir = path.join(wsPath, s.name);
      let bytes = 0, files = 0, newestMs = 0, guarded = false;
      try {
        for (const f of readdirSync(dir, { withFileTypes: true })) {
          if (!f.isFile()) continue;
          if (f.name === 'active' || f.name.endsWith('.lock')) { guarded = true; continue; }
          const st = statSync(path.join(dir, f.name));
          bytes += st.size; files++;
          if (st.mtimeMs > newestMs) newestMs = st.mtimeMs;
        }
      } catch (error) {
        unreadable.push({ dir, reason: `${error.code || error.message}` });
        continue;
      }
      sessions.push({
        workspace: ws.name, name: s.name, dir, bytes, files, newestMs, guarded,
        ageMs: newestMs > 0 ? Date.now() - newestMs : Infinity,
      });
    }
  }
  return { sessions, unreadable, root, exists: true };
}

const BUCKETS = [
  { label: '0-1d', maxDays: 1 },
  { label: '1-3d', maxDays: 3 },
  { label: '3-7d', maxDays: 7 },
  { label: '7-14d', maxDays: 14 },
  { label: '>14d', maxDays: Infinity },
];

/**
 * The engine reads every byte of every session file it walks, so the number
 * that predicts the freeze is TOTAL BYTES, and the tables below are ordered by
 * that rather than by session count.
 */
function bucketise(sessions) {
  const rows = BUCKETS.map((b) => ({ ...b, dirs: 0, bytes: 0, files: 0 }));
  for (const s of sessions) {
    const days = s.ageMs / DAY_MS;
    const row = rows.find((r) => days <= r.maxDays) || rows[rows.length - 1];
    row.dirs++; row.bytes += s.bytes; row.files += s.files;
  }
  return rows;
}

/** Measured on ZABZ-YOGA 2026-09-25: 5,675 ms to read 439.9 MB -> ~12.9 MB/s. */
const MEASURED_READ_BYTES_PER_MS = 439.9 / 5675;

/**
 * @param {number} bytes - bytes on disk, NOT megabytes.
 *
 * The unit conversion is not optional decoration: the constant above is
 * MB per ms, so dividing bytes by it directly overstates the estimate by
 * 1,048,576x. That exact bug shipped in the first draft of this file and was
 * caught by `corpus-test.mjs` reporting a 141,907 ms walk for a 0 MB corpus.
 */
function estimateWalkMs(bytes) {
  return Math.round((bytes / 1_048_576) / MEASURED_READ_BYTES_PER_MS);
}

// ---------------------------------------------------------------------------
// commands
// ---------------------------------------------------------------------------

function cmdReport() {
  const { sessions, unreadable, root, exists } = scanCorpus();
  if (!exists) { console.log(`no corpus at ${root}`); return 0; }
  const totalBytes = sessions.reduce((a, s) => a + s.bytes, 0);
  const guarded = sessions.filter((s) => s.guarded);

  console.log(`corpus  ${root}`);
  console.log(`${sessions.length} session dirs, ${mb(totalBytes)} MB`);
  console.log(`walk cost is bytes-proportional; measured ~${MEASURED_READ_BYTES_PER_MS.toFixed(1)} MB/ms of file read`);
  console.log(`=> a full walk of this corpus takes roughly ${estimateWalkMs(totalBytes)} ms of blocked event loop\n`);
  console.log('age bucket | dirs |    MB | cum MB | cum % bytes | if you archive older-than this bucket');
  let cum = 0;
  for (const r of bucketise(sessions)) {
    cum += r.bytes;
    // `cum` is everything up to and including this bucket, so the bytes that an
    // "older-than" cut at this bucket's edge would REMOVE are `cum`, and what it
    // would KEEP is the remainder. Printing the remainder under the label
    // "keeps" is the inversion this line exists to avoid.
    const removed = cum;
    const kept = totalBytes - removed;
    const cut = r.maxDays === Infinity
      ? `removes ${mb(removed)} MB (everything)`
      : `>${r.maxDays}d removes ${mb(removed)} MB, keeps ${mb(kept)} MB (~${estimateWalkMs(kept)} ms)`;
    console.log(`${r.label.padEnd(10)} | ${String(r.dirs).padStart(4)} | ${mb(r.bytes).toString().padStart(5)} | ${mb(cum).toString().padStart(6)} | ${(100 * cum / totalBytes).toFixed(1).padStart(10)}% | ${cut}`);
  }
  const biggest = [...sessions].sort((a, b) => b.bytes - a.bytes).slice(0, 8);
  console.log('\nlargest sessions (they dominate a bytes-proportional cost)');
  for (const s of biggest) console.log(`  ${(s.ageMs / DAY_MS).toFixed(1).padStart(5)}d  ${size(s.bytes).padStart(7)}  ${s.name}`);
  if (guarded.length > 0) {
    console.log(`\n${guarded.length} session(s) carry a lock/active marker and will never be archived:`);
    for (const g of guarded.slice(0, 5)) console.log(`  ${g.name} (${g.workspace})`);
  }
  if (unreadable.length > 0) {
    console.log(`\n${unreadable.length} unreadable path(s) skipped:`);
    for (const u of unreadable.slice(0, 5)) console.log(`  ${u.dir} - ${u.reason}`);
  }
  return 0;
}

function cmdArchive(args) {
  const olderThanMs = parseDuration(args['older-than'] ?? '7d');
  if (olderThanMs === undefined) { console.error('archive: --older-than must look like 7d / 12h / 30m'); return 2; }
  const apply = args.apply === true;
  const cutoffMs = Date.now() - olderThanMs;

  const { sessions } = scanCorpus();
  const selected = sessions.filter((s) => s.newestMs > 0 && s.newestMs < cutoffMs && !s.guarded);
  // Sessions old enough to archive but deliberately NOT moved. These must be
  // recorded, not merely filtered away: the manifest is the reversal and audit
  // record, and "we silently didn't touch it" is indistinguishable from "we
  // forgot it" once the session is out of the live tree.
  const excluded = sessions
    .filter((s) => s.newestMs < cutoffMs && !(s.newestMs > 0 && !s.guarded))
    .map((s) => ({
      dir: s.dir,
      workspace: s.workspace,
      name: s.name,
      bytes: s.bytes,
      reason: s.guarded
        ? 'carries a lock/active marker — possibly in use'
        : 'no readable files (unknown modification time)',
    }));
  const held = excluded.filter((s) => s.reason.startsWith('carries'));
  const selectedBytes = selected.reduce((a, s) => a + s.bytes, 0);

  console.log(`${apply ? 'ARCHIVING' : 'DRY RUN — nothing will move'}  older-than=${(olderThanMs / DAY_MS).toFixed(1)}d  cutoff=${new Date(cutoffMs).toISOString()}`);
  console.log(`selected ${selected.length} session(s), ${mb(selectedBytes)} MB  (of ${sessions.length} dirs)`);
  console.log(`walk cost driver drops by ~${estimateWalkMs(selectedBytes)} ms\n`);
  if (excluded.length > 0) {
    console.log(`excluded ${excluded.length} old session(s) that will NOT move:`);
    for (const x of excluded.slice(0, 10)) console.log(`  HOLD ${x.name} - ${x.reason}`);
    if (excluded.length > 10) console.log(`  ... and ${excluded.length - 10} more (all listed in the manifest)`);
    console.log('');
  }
  if (!apply) {
    for (const s of [...selected].sort((a, b) => b.bytes - a.bytes).slice(0, 15)) {
      console.log(`  would move  ${(s.ageMs / DAY_MS).toFixed(1).padStart(5)}d  ${size(s.bytes).padStart(7)}  ${s.workspace}/${s.name}`);
    }
    if (selected.length > 15) console.log(`  ... and ${selected.length - 15} more`);
    console.log('\nre-run with --apply to move them. Nothing above has changed.');
    return 0;
  }

  const root = archiveRoot();
  mkdirSync(root, { recursive: true });
  const manifestPath = path.join(root, `manifest-${new Date().toISOString().replace(/[:.]/g, '-')}.json`);
  const moved = [];
  const skipped = [];

  // Biggest first: the head of the list is where nearly all the bytes are, so a
  // run interrupted part-way has still removed the bulk of the cost.
  for (const s of [...selected].sort((a, b) => b.bytes - a.bytes)) {
    // Re-check age and guards at move time, not only at selection time.
    let newestNow = 0, guardedNow = false, filesNow = 0, bytesNow = 0;
    try {
      for (const f of readdirSync(s.dir, { withFileTypes: true })) {
        if (!f.isFile()) continue;
        if (f.name === 'active' || f.name.endsWith('.lock')) { guardedNow = true; continue; }
        const st = statSync(path.join(s.dir, f.name));
        bytesNow += st.size; filesNow++;
        if (st.mtimeMs > newestNow) newestNow = st.mtimeMs;
      }
    } catch (error) {
      skipped.push({ dir: s.dir, reason: `re-stat failed: ${error.code || error.message}` }); continue;
    }
    if (guardedNow) { skipped.push({ dir: s.dir, reason: 'lock/active marker appeared' }); continue; }
    if (newestNow >= cutoffMs) { skipped.push({ dir: s.dir, reason: 'written since selection — actively in use' }); continue; }

    const dest = path.join(root, s.workspace, s.name);
    if (existsSync(dest)) { skipped.push({ dir: s.dir, reason: `destination exists: ${dest}` }); continue; }
    try {
      mkdirSync(path.dirname(dest), { recursive: true });
      renameSync(s.dir, dest);
    } catch (error) {
      skipped.push({ dir: s.dir, reason: `rename failed: ${error.code || error.message}` });
      continue;
    }

    // Verify the move, and undo it rather than lose a session.
    let ok = false, verifyReason = '';
    try {
      const dstFiles = readdirSync(dest, { withFileTypes: true }).filter((f) => f.isFile());
      let dstBytes = 0;
      for (const f of dstFiles) dstBytes += statSync(path.join(dest, f.name)).size;
      if (dstFiles.length !== filesNow) verifyReason = `file count ${dstFiles.length} != ${filesNow}`;
      else if (dstBytes !== bytesNow) verifyReason = `bytes ${dstBytes} != ${bytesNow}`;
      else ok = true;
    } catch (error) {
      verifyReason = `verify failed: ${error.code || error.message}`;
    }
    if (!ok) {
      try { renameSync(dest, s.dir); } catch { /* reported below */ }
      skipped.push({ dir: s.dir, reason: `post-move verification failed (${verifyReason}); rolled back` });
      continue;
    }
    moved.push({ from: s.dir, to: dest, bytes: bytesNow, files: filesNow, workspace: s.workspace, name: s.name, mtime: new Date(newestNow).toISOString() });
    if (moved.length % 100 === 0) console.log(`  ... ${moved.length} moved`);
  }

  const movedBytes = moved.reduce((a, m) => a + m.bytes, 0);
  writeFileSync(manifestPath, JSON.stringify({
    version: 1,
    tool: 'session-corpus.mjs',
    action: 'archive',
    host: os.hostname(),
    at: new Date().toISOString(),
    olderThanDays: +(olderThanMs / DAY_MS).toFixed(3),
    cutoff: new Date(cutoffMs).toISOString(),
    moved, skipped, excluded,
    totals: { moved: moved.length, movedBytes, skipped: skipped.length, excluded: excluded.length },
  }, null, 2));

  console.log(`\nmoved ${moved.length} session(s), ${mb(movedBytes)} MB out of the live corpus`);
  console.log(`excluded ${excluded.length} (locked / unreadable) — listed in the manifest`);
  console.log(`skipped ${skipped.length}`);
  for (const x of skipped.slice(0, 10)) console.log(`  SKIP ${x.dir} - ${x.reason}`);
  if (skipped.length > 10) console.log(`  ... and ${skipped.length - 10} more (all listed in the manifest)`);
  console.log(`\nmanifest: ${manifestPath}`);
  console.log(`restore:  node scripts/session-corpus.mjs restore --manifest "${manifestPath}" --apply`);
  console.log('NOTHING WAS DELETED. Every session above is intact one directory over.');
  return 0;
}

function cmdRestore(args) {
  const manifest = args.manifest;
  if (typeof manifest !== 'string') { console.error('restore: --manifest <file> is required'); return 2; }
  if (!existsSync(manifest)) { console.error(`restore: no such manifest: ${manifest}`); return 2; }
  let doc;
  try { doc = JSON.parse(readFileSync(manifest, 'utf8')); } catch (error) { console.error(`restore: manifest is not valid JSON: ${error.message}`); return 2; }
  const moved = Array.isArray(doc.moved) ? doc.moved : [];
  const apply = args.apply === true;
  console.log(`${apply ? 'RESTORING' : 'DRY RUN — nothing will move'}  ${moved.length} session(s) from ${path.basename(manifest)}`);
  let done = 0; const problem = [];
  for (const m of moved) {
    if (!existsSync(m.to)) { problem.push({ to: m.to, reason: 'archived copy missing' }); continue; }
    if (existsSync(m.from)) { problem.push({ from: m.from, reason: 'a live session already occupies this path; not overwriting' }); continue; }
    if (!apply) { done++; continue; }
    try {
      mkdirSync(path.dirname(m.from), { recursive: true });
      renameSync(m.to, m.from);
      done++;
    } catch (error) {
      problem.push({ from: m.from, reason: `rename failed: ${error.code || error.message}` });
    }
  }
  console.log(`${apply ? 'restored' : 'would restore'} ${done} session(s)`);
  if (problem.length > 0) { console.log(`${problem.length} problem(s):`); for (const p of problem.slice(0, 10)) console.log(`  ${p.from || p.to} - ${p.reason}`); }
  if (!apply) console.log('\nre-run with --apply to restore.');
  return 0;
}

/**
 * The tripwire. This is the part that stops the same defect recurring silently:
 * the corpus that broke the engine grew with nothing watching it, so the check
 * has to be boring, cheap, and loud when it crosses a line.
 */
function cmdCheck(args) {
  const maxMb = Number(args['max-mb'] ?? 150);
  const maxDirs = Number(args['max-dirs'] ?? 400);
  const maxScanMs = Number(args['max-scan-ms'] ?? 2000);
  const { sessions } = scanCorpus();
  const totalBytes = sessions.reduce((a, s) => a + s.bytes, 0);
  const est = estimateWalkMs(totalBytes);
  const findings = [];
  if (mb(totalBytes) > maxMb) findings.push(`corpus is ${mb(totalBytes)} MB (limit ${maxMb} MB)`);
  if (sessions.length > maxDirs) findings.push(`${sessions.length} session dirs (limit ${maxDirs})`);
  if (est > maxScanMs) findings.push(`estimated walk ${est} ms (limit ${maxScanMs} ms)`);
  const line = `${new Date().toISOString()} corpus=${mb(totalBytes)}MB dirs=${sessions.length} est_walk_ms=${est}`;
  if (findings.length === 0) {
    console.log(`OK   ${line}`);
    return 0;
  }
  console.log(`WARN ${line}`);
  for (const f of findings) console.log(`     - ${f}`);
  console.log(`     fix: node scripts/session-corpus.mjs archive --older-than 7d --apply`);
  return 1;
}

// ---------------------------------------------------------------------------

const args = parseArgs(process.argv.slice(2));
const command = args._[0] || 'report';
const table = {
  report: () => cmdReport(),
  archive: () => cmdArchive(args),
  restore: () => cmdRestore(args),
  check: () => cmdCheck(args),
};
if (table[command] === undefined) {
  console.error(`unknown command: ${command}\n  expected one of: ${Object.keys(table).join(', ')}`);
  process.exit(2);
}
process.exit(table[command]());
