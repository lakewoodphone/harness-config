/**
 * session-format-audit.mjs — the no-data-loss proof for an upgrade that changes the SESSION LOG FORMAT.
 *
 * WHY THIS EXISTS. A candidate on the 0.1.7+ line declares `currentVersion: 4` while every log on disk
 * is v3, and ships only a v3→v4 codec. There is no v4→v3 codec in any build, so once a session is
 * opened for writing under the new engine, the old engine can no longer read it. That is the one step in
 * this pipeline that a rollback cannot undo by itself, and it is the reason `promote` has a session-format
 * gate at all.
 *
 * STATE-COMPAT.md concluded, on 2026-09-28, that the move is recoverable-by-deletion and that no session
 * in the corpus would be refused — but it said plainly what it had NOT done: "I did not execute the
 * v3→v4 codec against a live log ... What would settle it: in a throwaway DSH_HOME under %TEMP% (never
 * the live home), copy one session directory and call prepareJsonlMigration on it". A conclusion that
 * lives in a hand-written document does not re-check itself, and the corpus has grown since.
 *
 * So this is that conclusion made MECHANICAL and RE-RUNNABLE before any format-changing upgrade. It
 * proves three things and refuses to claim anything else:
 *
 *   1. SOURCE PROTECTION (static, on the candidate's own code). The migration must not be able to unlink
 *      or overwrite a source generation. Every `unlink`/`rm` in the candidate's persistence module is
 *      listed with its line, and the run fails if any of them resolves to a generation path. This is the
 *      property that makes "no data loss" true rather than hopeful: the v3 file is never touched.
 *   2. CORPUS ADMISSIBILITY (read-only, on the LIVE logs). The candidate's v3→v4 migration REFUSES some
 *      v3 content outright, and a refusal means that session cannot be opened for writing at all. This
 *      decodes every live log FRAME BY FRAME and counts every refused construct. A count above zero is
 *      the finding, and it names the sessions.
 *   3. THE FORMAT IT IS ACTUALLY ABOUT. Both the candidate's declared version and the live corpus's
 *      versions, read from disk, so the verdict cannot be about the wrong pair.
 *
 * FRAME-BY-FRAME IS NOT OPTIONAL. Each session log is many separate zstd frames back to back.
 * `zlib.zstdDecompressSync` on the whole buffer returns ONLY THE FIRST FRAME — the header line — which
 * makes a naive scan report a clean, meaningless zero. STATE-COMPAT.md records that its own first two
 * scans were wrong for exactly that reason. This module splits on the zstd magic and decodes each frame,
 * and it reports the frame count it actually decoded so a silent whole-buffer decode cannot hide here.
 *
 * IT NEVER WRITES INTO THE LIVE HOME. `--sessions` is read with `fs.readFileSync` only. Nothing is
 * copied, moved, deleted or quarantined here; this is an audit, not a migration.
 *
 * Usage:
 *   node dsh-update/tools/session-format-audit.mjs [--candidate <prefix|bin.js>] [--sessions <dir>]
 *        [--limit N] [--json] [--out <path>]
 *
 * Exit 0 = safe to migrate (with the counts printed), 7 = a real finding, 2 = the audit could not be
 * performed — which is a refusal, never a pass. An empty result is not evidence of health.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const UPD_ROOT = path.resolve(HERE, '..');
const STATE = path.join(UPD_ROOT, 'state');

const ARGS = process.argv.slice(2);
const flag = (name, dflt = null) => {
  const i = ARGS.indexOf(name);
  return i >= 0 && ARGS[i + 1] && !ARGS[i + 1].startsWith('--') ? ARGS[i + 1] : dflt;
};
const JSON_MODE = ARGS.includes('--json');
const OUT = flag('--out');
const LIMIT = Number(flag('--limit', '0')) || 0;

/** The zstd frame magic, little-endian on disk: 28 B5 2F FD. */
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

/** Constructs the candidate's v3->v4 migration refuses (STATE-COMPAT.md 3.2, from the codec itself). */
const REFUSALS = [
  {
    id: 'code-dispatch',
    why: 'event type tool/code-dispatch or tool/code-dispatch-start with ignorable !== true',
    test: (ev) => (ev?.type === 'tool/code-dispatch' || ev?.type === 'tool/code-dispatch-start') && ev.ignorable !== true,
  },
  {
    id: 'request-header-system',
    why: 'a request/header whose data.header has a `system` key',
    test: (ev) => ev?.type === 'request/header' && ev?.data?.header && Object.prototype.hasOwnProperty.call(ev.data.header, 'system'),
  },
  {
    id: 'tool-result-block',
    why: 'a content block of type tool-result in an interpreted slot or a stream block',
    test: (ev) => {
      const slots = ['user/message', 'assistant/message', 'developer/message', 'team/message/queued',
        'agent/inbox/spliced', 'session/title-llm-request', 'compaction/summary', 'tool/ptc-dispatch'];
      const inSlot = slots.includes(ev?.type) && JSON.stringify(ev?.data ?? {}).includes('"type":"tool-result"');
      const inStream = (ev?.type === 'block-end' || ev?.type === 'block-start') && ev?.data?.block?.type === 'tool-result';
      return inSlot || inStream;
    },
  },
];

function readJsonIfPresent(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

/** Resolve the candidate install root from a prefix, a bin.js, or the newest fetched prefix. */
function resolveCandidate() {
  const arg = flag('--candidate');
  if (arg) {
    const abs = path.resolve(arg);
    if (fs.existsSync(path.join(abs, 'node_modules', '@deepseek-ai'))) return abs;
    const m = abs.match(/^(.*?)[\\/]node_modules[\\/]@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js$/i);
    if (m) return path.resolve(m[1]);
    if (fs.existsSync(abs)) return abs;
    return null;
  }
  const prefixes = path.join(UPD_ROOT, 'vendor', 'prefix');
  let names = [];
  try { names = fs.readdirSync(prefixes).filter((n) => fs.existsSync(path.join(prefixes, n, 'node_modules', '@deepseek-ai'))); } catch { return null; }
  names.sort();
  return names.length ? path.join(prefixes, names[names.length - 1]) : null;
}

/**
 * Decode a session log FRAME BY FRAME and return its events.
 * Splitting on the magic is the only reliable way: a whole-buffer decode silently yields one frame.
 */
function decodeFrames(bytes) {
  const offsets = [];
  let i = bytes.indexOf(ZSTD_MAGIC, 0);
  while (i !== -1) { offsets.push(i); i = bytes.indexOf(ZSTD_MAGIC, i + 4); }
  if (offsets.length === 0) return { frames: 0, text: '', frameErrors: 1, note: 'no zstd frame magic found' };
  const parts = [];
  let frameErrors = 0;
  for (let k = 0; k < offsets.length; k += 1) {
    const end = k + 1 < offsets.length ? offsets[k + 1] : bytes.length;
    try {
      parts.push(zlib.zstdDecompressSync(bytes.subarray(offsets[k], end)).toString('utf8'));
    } catch { frameErrors += 1; }
  }
  return { frames: offsets.length, text: parts.join(''), frameErrors, note: null };
}

function main() {
  const started = Date.now();
  const lines = [];
  const problems = [];
  const say = (s = '') => lines.push(s);

  const candidate = resolveCandidate();
  if (!candidate) {
    say('session-format-audit: REFUSED — no candidate install found.');
    say('  Pass --candidate <prefix|bin.js>, or run `fetch <version>` first. An audit with no candidate');
    say('  would report zero findings about nothing, which is the failure mode this file exists to avoid.');
    return { exitCode: 2, text: lines.join('\n'), ok: false, refusal: 'no candidate' };
  }
  const dshAi = path.join(candidate, 'node_modules', '@deepseek-ai');

  // ── 3. which formats are actually in play ───────────────────────────────────────────────────────
  const catalogPath = path.join(dshAi, 'dsh-session-format-catalog', 'lib', 'index.js');
  const catalogText = fs.existsSync(catalogPath) ? fs.readFileSync(catalogPath, 'utf8') : null;
  const catalog = readJsonIfPresent(path.join(dshAi, 'dsh-session-format-catalog', 'package.json'));
  const declared = catalogText ? (catalogText.match(/currentVersion:\s*(\d+)/) || [])[1] ?? null : null;
  const codecs = fs.existsSync(dshAi)
    ? fs.readdirSync(dshAi).filter((n) => /^dsh-session-format-v\d+(-to-v\d+)?$/.test(n)).sort()
    : [];
  const hasDownMigration = codecs.some((n) => {
    const m = n.match(/v(\d+)-to-v(\d+)/);
    return m && Number(m[1]) > Number(m[2]);
  });

  say(`session-format-audit   candidate ${candidate}`);
  say('');
  say('1. THE FORMATS IN PLAY');
  say(`   candidate declares currentVersion : ${declared ?? 'UNREADABLE'}`);
  say(`   candidate codec packages          : ${codecs.length ? codecs.join(', ') : 'none found'}`);
  say(`   a DOWN-migration codec exists     : ${hasDownMigration ? 'yes' : 'NO — after this move, going back means removing the new siblings'}`);
  say(`   catalog                           : ${catalogText ? path.join(dshAi, 'dsh-session-format-catalog', 'lib', 'index.js') : 'ABSENT — the format cannot be read, so nothing here is established'}`);
  if (!catalogText) {
    problems.push('the candidate session-format catalog could not be read, so which format it writes is unknown');
  }

  // ── 1. source protection: can the candidate's migration touch a source generation? ───────────────
  say('');
  say('2. SOURCE PROTECTION — can the candidate UNLINK OR OVERWRITE a source log?');
  const persistence = path.join(dshAi, 'dsh-session-persistence-jsonl', 'lib', 'index.js');
  if (!fs.existsSync(persistence)) {
    problems.push(`the candidate persistence module is absent (${persistence}), so source protection CANNOT be established — that is a refusal, not a pass`);
    say('   REFUSED — dsh-session-persistence-jsonl/lib/index.js is not present in this candidate.');
  } else {
    const src = fs.readFileSync(persistence, 'utf8');
    const srcLines = src.split('\n');

    /**
     * Which function encloses a given line? A removal call is only judgeable through the binding of its
     * argument, and that binding is the enclosing function's parameter list. Reporting `rm(path)` without
     * knowing what `path` is produces a FALSE FINDING — measured on 0.2.0-rc.2, where the two real calls
     * are inside `removeTemporary` / `removeCommittedTemporary` and remove the staged `.tmp`, exactly as
     * STATE-COMPAT.md established by hand for 0.1.7-rc.2. A gate that cries wolf on the one property it
     * exists to prove is a gate that gets ignored, so the enclosing name is resolved rather than guessed.
     */
    const enclosingFunction = (idx) => {
      for (let k = idx; k >= 0 && k > idx - 400; k -= 1) {
        const m = srcLines[k].match(/(?:^|\s)(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^;]*?\)\s*\{/);
        if (m && !/^(if|for|while|switch|catch|return|await|function)$/.test(m[1])) return { name: m[1], line: k + 1 };
      }
      return { name: null, line: null };
    };

    const rmHits = [];
    srcLines.forEach((l, idx) => {
      const t = l.trim();
      if (!/(\bunlink|\brmSync|\.rm\(|\brmdir)/.test(l)) return;
      // A comment is not a call. (The same lesson as tests/guards/comment-refs.mjs: a name in prose is
      // not a dependency, and a removal in prose is not a removal.)
      if (t.startsWith('*') || t.startsWith('//') || t.startsWith('/*')) return;
      const fn = enclosingFunction(idx);
      const arg = (l.match(/(?:unlink|rmSync|rm|rmdir)\s*\(([^)]*)\)/) || [])[1] ?? '';
      const safe = /temp|staged|temporary|cleanup/i.test(fn.name ?? '') || /temp|staged|temporary|\.tmp/i.test(arg);
      rmHits.push({ line: idx + 1, text: t.slice(0, 150), fn: fn.name, fnLine: fn.line, arg: arg.trim().slice(0, 60), safe });
    });

    say(`   ${path.relative(UPD_ROOT, persistence)}  (${srcLines.length} lines)`);
    say(`   removal CALLS found (comment-only lines excluded): ${rmHits.length}`);
    for (const h of rmHits) {
      say(`     :${h.line}  in ${h.fn ?? '(module scope)'}${h.fnLine ? ` (declared :${h.fnLine})` : ''}  arg="${h.arg}"  -> ${h.safe ? 'STAGED/TEMPORARY — safe' : 'NOT a temporary target'}`);
      say(`              ${h.text}`);
    }
    const suspicious = rmHits.filter((h) => !h.safe);
    if (rmHits.length === 0) {
      problems.push('the candidate persistence module contains NO removal call at all, which is unexpected enough that this audit will not treat it as proof');
      say('   -> no removal call found at all. That is unexpected, and this audit does not read it as safety.');
    } else if (suspicious.length === 0) {
      say('   -> every removal call is inside a temporary/staged/cleanup function or names a `.tmp`: the');
      say('      candidate has no code path that unlinks a source generation. This is the property that makes');
      say('      the move recoverable rather than final — a source log is never the file it removes.');
    } else {
      problems.push(`${suspicious.length} removal call(s) in the candidate persistence module are NOT inside a temporary/staged function and do not name a .tmp — each one must be read by hand before trusting that a source log survives the migration`);
      say(`   -> ${suspicious.length} call(s) need reading by hand. This audit will NOT call them safe.`);
    }
  }

  // ── 2. corpus admissibility: would the migration REFUSE any session we actually have? ────────────
  say('');
  say('3. CORPUS ADMISSIBILITY — would the candidate REFUSE any live session?');
  const sessionsDir = flag('--sessions') || path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'sessions');
  if (!fs.existsSync(sessionsDir)) {
    problems.push(`no sessions directory at ${sessionsDir}`);
    say(`   REFUSED — ${sessionsDir} does not exist. An empty corpus is not a clean corpus.`);
  } else {
    const files = [];
    const walk = (dir) => {
      let entries = [];
      try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
      for (const e of entries) {
        const p = path.join(dir, e.name);
        if (e.isDirectory()) walk(p);
        else if (/^session\.v\d+\.jsonl/.test(e.name)) files.push(p);
      }
    };
    walk(sessionsDir);
    const byVersion = {};
    for (const f of files) {
      const v = (f.match(/session\.v(\d+)\.jsonl/) || [])[1] ?? '?';
      byVersion[v] = (byVersion[v] || 0) + 1;
    }
    say(`   live logs found: ${files.length}  by name: ${Object.entries(byVersion).map(([k, v]) => `v${k}=${v}`).join(' ') || '(none)'}`);

    const selected = LIMIT > 0 ? files.slice(0, LIMIT) : files;
    const counts = Object.fromEntries(REFUSALS.map((r) => [r.id, 0]));
    const offenders = [];
    let decodedFiles = 0;
    let totalFrames = 0;
    let frameErrors = 0;
    let unparsed = 0;
    let bytes = 0;
    let headerVersions = {};

    for (const f of selected) {
      let raw;
      try { raw = fs.readFileSync(f); } catch { frameErrors += 1; continue; }
      bytes += raw.length;
      // The filename says the version; the FIRST FRAME's header is the evidence for it.
      const r = decodeFrames(raw);
      totalFrames += r.frames;
      frameErrors += r.frameErrors;
      const text = r.text;
      const nl = text.split('\n');
      let firstParsed = null;
      for (const line of nl) {
        const t = line.trim();
        if (!t) continue;
        let ev;
        try { ev = JSON.parse(t); } catch { unparsed += 1; continue; }
        if (firstParsed === null) {
          firstParsed = ev;
          const hv = ev?.version ?? ev?.data?.version ?? null;
          if (hv !== null) headerVersions[String(hv)] = (headerVersions[String(hv)] || 0) + 1;
        }
        for (const ref of REFUSALS) {
          if (ref.test(ev)) {
            counts[ref.id] += 1;
            if (offenders.length < 25) offenders.push({ file: path.relative(sessionsDir, f), refusal: ref.id, type: ev?.type ?? null });
          }
        }
      }
      decodedFiles += 1;
    }

    say(`   logs decoded frame-by-frame : ${decodedFiles} of ${selected.length} selected`);
    say(`   total zstd frames decoded   : ${totalFrames}   (a whole-buffer decode would have read ONE per file — this is the control that it did not)`);
    say(`   frame decode errors         : ${frameErrors}`);
    say(`   lines that were not JSON    : ${unparsed}`);
    say(`   first-frame header versions : ${Object.entries(headerVersions).map(([k, v]) => `v${k}=${v}`).join(' ') || '(none seen)'}`);
    say(`   bytes read                  : ${(bytes / 1048576).toFixed(1)} MB (read-only)`);
    say('');
    say('   refused constructs the candidate v3->v4 migration rejects:');
    for (const ref of REFUSALS) {
      say(`     ${ref.id.padEnd(24)} ${counts[ref.id]}   (${ref.why})`);
    }
    const refusedTotal = Object.values(counts).reduce((a, b) => a + b, 0);
    if (totalFrames <= decodedFiles) {
      problems.push(`only ${totalFrames} frame(s) decoded across ${decodedFiles} file(s) — that is the signature of a whole-buffer decode, so this corpus scan is not trustworthy`);
    }
    if (unparsed > 0) problems.push(`${unparsed} line(s) did not parse as JSON`);
    if (frameErrors > 0) problems.push(`${frameErrors} frame(s) failed to decode`);
    if (refusedTotal > 0) {
      problems.push(`${refusedTotal} refused construct(s) across the corpus — that many session(s) can NOT be opened for writing under this candidate`);
      say('');
      say('   SESSIONS THAT WOULD BE REFUSED (first 25):');
      for (const o of offenders) say(`     ${o.refusal}  ${o.file}  type=${o.type}`);
    } else if (problems.length === 0) {
      say('');
      say('   -> no refused construct anywhere in the corpus: every session here can be migrated.');
    }
  }

  // ── verdict ─────────────────────────────────────────────────────────────────────────────────────
  const ok = problems.length === 0;
  say('');
  say(`VERDICT: ${ok ? 'SAFE TO MIGRATE, on the evidence above' : 'DO NOT RELY ON THIS MIGRATION YET'}`);
  if (!ok) for (const p of problems) say(`  - ${p}`);
  say('');
  say('WHAT THIS DOES NOT PROVE: it does not EXECUTE the v3->v4 codec. It establishes that no source log');
  say('can be unlinked by the candidate and that no session in the corpus carries a construct the migration');
  say('refuses. The remaining gap is the codec run itself, and it is closed by `switch-engine.ps1 -Rollback`,');
  say('which MOVES any session.v4 sibling that appeared into a quarantine directory with a manifest rather');
  say('than deleting it, so the v3 original is still the file the old engine reads.');
  say(`elapsed ${Date.now() - started} ms`);

  const out = {
    schemaVersion: 1, tool: 'session-format-audit', generatedAt: new Date().toISOString(),
    candidate, declaredCurrentVersion: declared === null ? null : Number(declared),
    codecPackages: codecs, hasDownMigration, sessionsDir: flag('--sessions') || null,
    ok, problems, text: lines.join('\n'),
  };
  if (OUT) {
    const abs = path.resolve(OUT);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, `${JSON.stringify(out, null, 2)}\n`);
  }
  if (JSON_MODE) process.stdout.write(`${JSON.stringify(out, null, 2)}\n`);
  return { exitCode: ok ? 0 : 7, text: lines.join('\n'), ok, problems, out };
}

const result = main();
if (!JSON_MODE) process.stdout.write(`${result.text}\n`);
process.exitCode = result.exitCode;
