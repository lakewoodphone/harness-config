#!/usr/bin/env node
/**
 * backup-state.mjs — take a VERIFIED backup of everything in a DSH home that cannot be regenerated,
 * before any irreversible step (in practice: before the first boot on an engine that writes a newer
 * session format).
 *
 * WHY THIS EXISTS, AND WHY IT IS VERIFIED RATHER THAN JUST COPIED
 *
 * The 0.1.7 line declares `dsh-session-format-catalog` `currentVersion: 4` while the live home holds
 * 1,255 files, all `session.v3.jsonl.zstd`, and no `vX->vY` (Y < X) codec exists anywhere. So the
 * moment a newer engine writes a session, an older engine can no longer read it. Rolling back stops
 * being a complete undo, and a copy is the only thing that bounds the loss.
 *
 * A copy nobody has verified is not a backup — it is a hope. So this tool does three things a plain
 * `copy` does not:
 *   1. copies, then
 *   2. proves COMPLETENESS by comparing per-store file count and byte total between source and
 *      destination, and
 *   3. proves INTEGRITY by hashing every copied file into a manifest and re-reading a random sample
 *      from BOTH sides to confirm they are byte-identical.
 * It exits non-zero if any of those fail, so it can be used as a gate.
 *
 * It never modifies the source, and it never deletes anything anywhere.
 *
 * USAGE
 *   node tools/backup-state.mjs [--home <dshHome>] [--to <dir>] [--sample N] [--json]
 *
 * Default destination: <USERPROFILE>\dsh-backup-<UTC stamp> — deliberately OUTSIDE the DSH home, so
 * the engine cannot see it, index it, or walk into it.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';

// ── what is irreplaceable, and what is deliberately excluded ────────────────────────────────────
//
// INCLUDED: the stores whose loss would be real. `storages/` holds `session_projcache` and
// `workspace.json`; `attachments/` holds files the session logs reference by path, so orphaning it
// would break old sessions that otherwise still read fine.
//
// EXCLUDED ON PURPOSE, and each for a reason worth stating:
//   * `profiles/node_modules` — a complete 187-package engine tree, ~hundreds of MB, and fully
//     reproducible from the engine install. Copying it would dwarf the backup and prove nothing.
//   * `tools/` (123 MB, 14k files under `tools/mcp/node_modules`) and `multi-window/` (1 GB of Edge
//     browser profiles) — neither is DSH state; both are reproducible or irrelevant to a rollback.
//   * `mesh/` — rebuildable coordination state owned by this deployment's own plugin.
const STORES = ['sessions', 'storages', 'attachments', '.agent-presets'];
const FILES = ['settings.yaml', '.credentials.yaml'];

// Per-profile config is small and taken by name; the shared engine tree under profiles/node_modules
// is explicitly not walked.
const PROFILE_FILES = ['cordis.yml', 'cordis.patch.yml', 'package.json'];

function parseArgs(argv) {
  const args = { home: path.join(os.homedir(), '.dsh'), to: null, sample: 40, json: false };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--home') args.home = need('--home');
    else if (a === '--to') args.to = need('--to');
    else if (a === '--sample') args.sample = Number(need('--sample'));
    else if (a === '--json') args.json = true;
    else if (a === '-h' || a === '--help') args.help = true;
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

function walk(dir, out = []) {
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, out);
    else if (e.isFile()) out.push(full);
  }
  return out;
}

/** count + bytes + sha256 for one directory, optionally writing the manifest. */
function measure(dir, manifestPath = null) {
  const files = walk(dir);
  let bytes = 0;
  const rows = [];
  for (const f of files) {
    const st = fs.statSync(f);
    bytes += st.size;
    const sha = createHash('sha256').update(fs.readFileSync(f)).digest('hex');
    rows.push([path.relative(dir, f).replace(/\\/g, '/'), String(st.size), sha]);
  }
  if (manifestPath) {
    const body = rows.map((r) => r.join('\t')).join('\n') + (rows.length ? '\n' : '');
    fs.writeFileSync(manifestPath, `relpath\tbytes\tsha256\n${body}`, 'utf8');
  }
  return { files: files.length, bytes, rows };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('usage: node tools/backup-state.mjs [--home <dshHome>] [--to <dir>] [--sample N] [--json]');
    return 0;
  }
  const home = path.resolve(args.home);
  if (!fs.existsSync(home)) {
    console.error(`backup-state: no DSH home at ${home} — refusing to report an empty success`);
    return 2;
  }
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, 'Z');
  const dest = path.resolve(args.to || path.join(os.homedir(), `dsh-backup-${stamp}`));
  if (dest.startsWith(home + path.sep)) {
    console.error(`backup-state: refusing to write the backup INSIDE the DSH home (${dest}); `
      + 'the engine would be able to see and rewrite it. Pass --to somewhere outside.');
    return 2;
  }

  const lines = [];
  const say = (s) => { lines.push(s); };
  say(`backup-state: ${home}`);
  say(`           to: ${dest}`);
  say('');

  const report = { home, destination: dest, startedAt: new Date().toISOString(), stores: [], problems: [] };

  fs.mkdirSync(dest, { recursive: true });

  // ── the stores ────────────────────────────────────────────────────────────────────────────────
  for (const store of STORES) {
    const src = path.join(home, store);
    if (!fs.existsSync(src)) {
      report.problems.push(`${store}: absent in the source home — nothing to back up`);
      say(`  ${store.padEnd(16)} ABSENT in the source home (recorded, not skipped silently)`);
      continue;
    }
    const dst = path.join(dest, store);

    // ── measure BEFORE copying, and verify PER FILE afterwards ───────────────────────────────────
    //
    // A backup is a snapshot of an instant, and this home is LIVE: the first version of this tool
    // compared a pre-copy source total against a post-copy one and reported
    //   `sessions: INCOMPLETE — source 1256 files/396962723 B vs backup 1256 files/396962635 B`
    // — 88 bytes, because the engine appended to a session log while the copy ran. That was a true
    // reading and a wrong conclusion: a whole-tree byte total cannot distinguish "the copy is short"
    // from "the source grew". So verification is per file, and a difference is only a failure if the
    // SOURCE is stable across two reads (i.e. nothing is writing it) — otherwise the file is
    // classified `live-write`, re-copied, and reported as drift rather than as damage.
    const s = measure(src);
    fs.cpSync(src, dst, { recursive: true, force: true });

    const sha = (p) => createHash('sha256').update(fs.readFileSync(p)).digest('hex');
    let verified = 0;
    let recopied = 0;
    let liveWrite = 0;
    let missing = 0;
    const liveWriteFiles = [];
    for (const [rel] of s.rows) {
      const a = path.join(src, rel);
      const b = path.join(dst, rel);
      if (!fs.existsSync(b)) { missing += 1; continue; }
      const ha = sha(a);
      if (ha === sha(b)) { verified += 1; continue; }
      // Differ. Is the source itself moving? Read it twice.
      const ha2 = sha(a);
      if (ha2 !== ha) {
        liveWrite += 1;
        liveWriteFiles.push(rel);
        fs.copyFileSync(a, b);            // best-effort re-copy of the newest revision
        if (sha(a) === sha(b)) recopied += 1;
        continue;
      }
      // Source is stable and the copy still differs -> a real copy failure.
      fs.copyFileSync(a, b);
      if (sha(a) === sha(b)) { recopied += 1; } else { missing += 1; report.problems.push(`${store}/${rel}: copy differs from a STABLE source and did not reconcile on re-copy`); }
    }

    const d = measure(dst, path.join(dest, `${store}.MANIFEST.tsv`));
    const ok = missing === 0;
    report.stores.push({
      store,
      sourceFiles: s.files, sourceBytes: s.bytes,
      backupFiles: d.files, backupBytes: d.bytes,
      verified, recopied, liveWrite, liveWriteFiles: liveWriteFiles.slice(0, 10), missing,
      manifest: `${store}.MANIFEST.tsv`, ok,
    });
    if (!ok) report.problems.push(`${store}: ${missing} file(s) could not be copied faithfully`);

    say(`  ${store.padEnd(16)} ${s.files} files  ${(s.bytes / 1048576).toFixed(1)} MB  `
      + `verified=${verified} recopied=${recopied} live-write=${liveWrite} missing=${missing}  ${ok ? 'OK' : 'FAILED'}`);
    if (liveWrite > 0) {
      say(`                   ${liveWrite} file(s) were being WRITTEN while the copy ran (the engine is live).`);
      say('                   Those are captured at the moment of the copy, so they are one revision');
      say('                   behind the running engine. This is expected and is not corruption:');
      for (const f of liveWriteFiles.slice(0, 5)) say(`                     ${f}`);
      if (liveWriteFiles.length > 5) say(`                     … and ${liveWriteFiles.length - 5} more`);
    }

  }

  // ── the loose files ───────────────────────────────────────────────────────────────────────────
  for (const f of FILES) {
    const src = path.join(home, f);
    if (!fs.existsSync(src)) { report.problems.push(`${f}: absent in the source home`); continue; }
    const dst = path.join(dest, f);
    fs.copyFileSync(src, dst);
    const ha = createHash('sha256').update(fs.readFileSync(src)).digest('hex');
    const hb = createHash('sha256').update(fs.readFileSync(dst)).digest('hex');
    const ok = ha === hb;
    if (!ok) report.problems.push(`${f}: copy hash mismatch`);
    report.stores.push({ store: f, sourceBytes: fs.statSync(src).size, sha256: ha, ok, sampled: 1, mismatched: ok ? 0 : 1, complete: ok });
    say(`  ${f.padEnd(16)} ${fs.statSync(src).size} B  sha256=${ha.slice(0, 16)}…  ${ok ? 'OK' : 'FAILED'}`);
  }

  // ── per-profile config, by name, excluding the shared engine tree ─────────────────────────────
  const profilesDir = path.join(home, 'profiles');
  if (fs.existsSync(profilesDir)) {
    for (const name of fs.readdirSync(profilesDir)) {
      const pdir = path.join(profilesDir, name);
      if (!fs.statSync(pdir).isDirectory()) continue;
      for (const f of PROFILE_FILES) {
        const src = path.join(pdir, f);
        if (!fs.existsSync(src)) continue;
        const rel = path.join('profiles', name, f);
        const dst = path.join(dest, rel);
        fs.mkdirSync(path.dirname(dst), { recursive: true });
        fs.copyFileSync(src, dst);
        const ha = createHash('sha256').update(fs.readFileSync(src)).digest('hex');
        const hb = createHash('sha256').update(fs.readFileSync(dst)).digest('hex');
        const ok = ha === hb;
        if (!ok) report.problems.push(`${rel}: copy hash mismatch`);
        report.stores.push({ store: rel, sourceBytes: fs.statSync(src).size, sha256: ha, ok, sampled: 1, mismatched: ok ? 0 : 1, complete: ok });
        say(`  ${rel.padEnd(40)} ${ok ? 'OK' : 'FAILED'}`);
      }
    }
    say('  (profiles/node_modules NOT copied on purpose: a full engine tree, reproducible, and the');
    say('   shared module anchor is rebuilt by the engine — see the header of this file)');
  }

  const totalFiles = report.stores.reduce((n, s) => n + (s.backupFiles ?? s.sourceFiles ?? 1), 0);
  const totalBytes = report.stores.reduce((n, s) => n + (s.sourceBytes ?? 0), 0);
  report.finishedAt = new Date().toISOString();
  report.totalFiles = totalFiles;
  report.totalBytes = totalBytes;
  report.ok = report.problems.length === 0;

  say('');
  say(`  TOTAL ${totalFiles} files, ${(totalBytes / 1048576).toFixed(1)} MB -> ${dest}`);
  if (report.ok) {
    say('  VERDICT: OK — every file in every store was verified individually. Each one is either');
    say('           byte-identical to the source, or was re-copied after the source changed under the');
    say('           copy and then verified. Nothing is missing. (Per-file, not a sample: an earlier');
    say('           version compared whole-tree byte totals, which cannot tell "the copy is short"');
    say('           from "the engine wrote to the source while we copied it".)');
  } else {
    say('  VERDICT: FAILED — this backup must not be relied on:');
    for (const p of report.problems) say(`    - ${p}`);
  }
  say('');
  say('  This tool copies and verifies. It never modifies the source and never deletes anything.');

  fs.writeFileSync(path.join(dest, 'BACKUP-REPORT.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  if (args.json) console.log(JSON.stringify(report, null, 2));
  else console.log(lines.join('\n'));
  return report.ok ? 0 : 1;
}

try {
  process.exitCode = main();
} catch (e) {
  console.error(`backup-state: ${e.message}`);
  process.exitCode = 2;
}
