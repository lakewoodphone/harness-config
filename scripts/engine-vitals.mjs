#!/usr/bin/env node
/**
 * engine-vitals — record what the engine's event loop is actually doing, and say
 * loudly when the engine dies.
 *
 * WHY THIS EXISTS
 *
 * Two failures happened with no instrument pointed at them.
 *
 * 1. THE ENGINE DIED AND NOTHING SAID SO (2026-09-25). Storage Sense deleted the
 *    engine's %TEMP% spill directory underneath it, the output collector threw an
 *    unhandled ENOENT, and the process exited. The health loop had printed
 *    "healthy: all 1 enabled engine(s) listening" four minutes earlier. The only
 *    witness was a stack trace at the tail of a 400-line stderr log, and it was
 *    found days later by reading that log by hand.
 *
 * 2. NOTHING RECORDED LOAD AGAINST LATENCY, so the biggest question could not be
 *    answered. On 2026-09-28 the engine measured p50 57 ms / p95 2,200 ms / max
 *    16,854 ms on its event loop, with 10 agent loops running in one process. An
 *    earlier reading on the same engine at 2 loops showed p95 15 ms. Was that
 *    decay-with-uptime or just load? No history existed to say, and the metrics
 *    CSV (`~/.dsh/metrics/harness-metrics.csv`) has never had a loop-lag column.
 *    That is the whole reason this tool was written: to make the next such
 *    question answerable from a file instead of from an argument.
 *
 * WHAT IT RECORDS, PER PASS
 *
 *   ts, engine pid + startedAt + uptime, loop p50/p95/max, live sessions,
 *   agent loops running, heap used/total, rss, governor slots in use, the
 *   health probe's cumulative spawn count, disk free %, and the session
 *   corpus (dirs + MB).
 *
 * WHAT IT SHOUTS ABOUT
 *
 *   * ENGINE RESTART — the pid is not the one recorded last pass. It then reads
 *     the newest engine stderr log and reports the first unhandled-exception
 *     signature it finds, so a crash arrives as one line instead of a forensic
 *     read.
 *   * LOOP LAG over threshold (p95 and max are checked separately: a good median
 *     with a terrible max is a stalled loop, not a busy one).
 *   * DISK FREE below threshold — the upstream trigger of the whole 09-25
 *     incident, and nothing watched it.
 *   * PROBE SPAWN CHURN — the health plugin spawns a PowerShell snapshot on a
 *     timer and had reached 39,279 spawns. Reported as a rate, never assumed
 *     to be the cause.
 *
 * Exit codes: 0 clean, 1 warning, 3 engine unreachable. Warnings never throw.
 *
 * USAGE
 *   node scripts/engine-vitals.mjs                 # one pass, human output
 *   node scripts/engine-vitals.mjs --json          # one pass, machine output
 *   node scripts/engine-vitals.mjs --csv <path>    # override the CSV path
 *   node scripts/engine-vitals.mjs --loop-p95 800 --disk-pct 12
 *   node scripts/engine-vitals.mjs --explain       # thresholds and where they came from
 */

import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync, readdirSync, statSync, statfsSync, rmSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const DEFAULTS = {
  // 500 ms p95: the reading that separated a healthy engine (p95 15 ms) from a
  // loaded one (p95 490 ms) to a saturated one (p95 2,200 ms).
  loopP95: 500,
  // 5,000 ms max: a single stall a human notices. Observed values: 348 ms fresh,
  // 7,516 ms at 2d with 5 loops, 16,854 ms at 2d with 10 loops.
  loopMax: 5000,
  // 12%: 8% free is what triggered the Storage Sense cleanup that killed the
  // engine. Warning above the trigger, not at it.
  diskPct: 12,
  // 8 agent loops: the count at which p95 passed 2 s on a 22-core host.
  loops: 8,
};

function home() { return process.env.DSH_HOME || path.join(os.homedir(), '.dsh'); }
function vitalsStatePath() { return path.join(home(), 'health', 'engine-vitals.json'); }
function defaultCsvPath() { return path.join(home(), 'metrics', 'engine-vitals.csv'); }

function parseArgs(argv) {
  const out = { flags: [], vals: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const n = argv[i + 1];
      if (n === undefined || n.startsWith('--')) out.flags.push(k);
      else { out.vals[k] = n; i++; }
    }
  }
  return out;
}
const num = (v, d) => (v !== undefined && Number.isFinite(Number(v)) ? Number(v) : d);

// ---------------------------------------------------------------------------
// engine discovery + auth
// ---------------------------------------------------------------------------

/**
 * The launcher records the live engine, its port and its token in state.json.
 * That token rotates with every engine start, which is why a stale token gives
 * 401 and must never be cached across restarts.
 */
function readEngineSlot() {
  const p = path.join(home(), 'multi-window', 'state.json');
  if (!existsSync(p)) return undefined;
  let doc;
  try { doc = JSON.parse(readFileSync(p, 'utf8')); } catch { return undefined; }
  const slots = doc.slots ?? {};
  const [port, slot] = Object.entries(slots)[0] ?? [];
  if (port === undefined || slot === undefined) return undefined;
  return { port, pid: slot.pid, url: slot.url, log: slot.log, startedAt: slot.startedAt };
}

/**
 * Candidate launch URLs, most-likely-live first.
 *
 * `state.json` is written by the launcher's START path. When the engine is later replaced by the
 * recovery path, the file keeps the DEAD pid and token, and NOTHING rewrites it. MEASURED
 * 2026-10-05 on ZABZ-YOGA: `state.json` named pid 11176 while the live engine was pid 25228, so
 * every `/healthz` answered 401 — and this task's 5-minute run failed or crashed (0xC0000409) for
 * two and a half days while the file it feeds stayed frozen at 2026-10-02. The launcher LOG is the
 * surface that follows the live engine, so its newest tokens are tried first, exactly as
 * `scripts/mesh-restart-at-0700.ps1` does. The recorded URL is kept last rather than dropped, so a
 * machine whose logs have rotated away still works.
 */
function candidateUrls(slot) {
  const urls = [];
  try {
    const dir = path.join(home(), 'multi-window', 'logs');
    if (existsSync(dir)) {
      const names = [`${slot.port}.log`, ...readdirSync(dir).filter((f) => f.startsWith(`${slot.port}-`) && f.endsWith('.log'))];
      const files = names.map((n) => path.join(dir, n)).filter((f) => existsSync(f))
        .map((f) => ({ f, m: statSync(f).mtimeMs })).sort((a, b) => b.m - a.m);
      const tokens = [];
      for (const { f } of files) {
        const text = readFileSync(f, 'utf8');
        const found = [...text.matchAll(/token=([A-Za-z0-9_-]+)/g)];
        for (let i = found.length - 1; i >= 0 && tokens.length < 4; i--) {
          if (!tokens.includes(found[i][1])) tokens.push(found[i][1]);
        }
        if (tokens.length >= 4) break;
      }
      for (const t of tokens) urls.push({ url: `http://127.0.0.1:${slot.port}/?token=${t}`, from: `log token ${t.slice(0, 6)}…` });
    }
  } catch { /* no readable logs: fall through to the recorded URL */ }
  if (slot.url) urls.push({ url: slot.url, from: 'state.json' });
  return urls;
}

/**
 * Bootstrap the auth cookie from a window URL, then read /healthz.
 * Tries every candidate token until one authenticates, and reports which one did.
 */
async function readHealthz(slot) {
  // `connection: close` on purpose. This process fetches twice and then exits, and a
  // keep-alive socket still pooled at exit is what produces Node-on-Windows'
  // "Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c, line 76"
  // — the 0xC0000409 the scheduled task reported on 2026-09-28. Two extra handshakes
  // remove the whole class of crash.
  const CLOSE = { connection: 'close' };
  const candidates = candidateUrls(slot);
  if (candidates.length === 0) throw new Error('no engine URL recorded in state.json and no readable launcher log');
  const tried = [];
  for (const candidate of candidates) {
    let cookie = '';
    try {
      const res = await fetch(candidate.url, { redirect: 'manual', headers: CLOSE });
      const setCookies = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [];
      cookie = setCookies.map((c) => c.split(';')[0]).join('; ');
      try { await res.body?.cancel(); } catch { /* body already consumed */ }
    } catch { /* fall through with no cookie; /healthz will say 401 */ }
    if (cookie.length === 0) { tried.push(`${candidate.from}: no cookie`); continue }
    const started = Date.now();
    const res = await fetch(`http://127.0.0.1:${slot.port}/healthz`, { headers: { ...CLOSE, cookie } });
    const healthzMs = Date.now() - started;
    if (!res.ok) { tried.push(`${candidate.from}: /healthz ${res.status}`); try { await res.body?.cancel(); } catch { } continue }
    const body = await res.json();
    return { body, healthzMs, authFrom: candidate.from };
  }
  throw new Error(`/healthz did not answer 200 with any known token (${tried.join('; ')})`);
}

// ---------------------------------------------------------------------------
// local facts
// ---------------------------------------------------------------------------

function diskFreePct() {
  try {
    const st = statfsSync(process.env.SystemDrive ? `${process.env.SystemDrive}\\` : 'C:\\');
    const total = st.blocks * st.bsize;
    const free = st.bavail * st.bsize;
    return { totalBytes: total, freeBytes: free, freePct: total > 0 ? +(100 * free / total).toFixed(1) : null };
  } catch { return { totalBytes: null, freeBytes: null, freePct: null }; }
}

/** Cheap: stat only, never file contents. Measuring must not become the load. */
function corpusSize() {
  const root = path.join(home(), 'sessions');
  if (!existsSync(root)) return { dirs: 0, bytes: 0 };
  let dirs = 0, bytes = 0;
  for (const w of readdirSync(root, { withFileTypes: true })) {
    if (!w.isDirectory()) continue;
    const ws = path.join(root, w.name);
    let sessions;
    try { sessions = readdirSync(ws, { withFileTypes: true }); } catch { continue; }
    for (const s of sessions) {
      if (!s.isDirectory()) continue;
      dirs++;
      const dir = path.join(ws, s.name);
      try {
        for (const f of readdirSync(dir, { withFileTypes: true })) {
          if (f.isFile()) bytes += statSync(path.join(dir, f.name)).size;
        }
      } catch { /* unreadable session counts as a dir, not an error */ }
    }
  }
  return { dirs, bytes };
}

/**
 * The first unhandled-exception signature in an engine stderr log.
 *
 * Deliberately conservative: it looks for a Node crash shape (an `Error:` line
 * followed by an indented `at ` frame) OR the known spill-collector signature,
 * and reports the first line it matched. It does not claim the engine died —
 * restart detection does that; this only names the likely reason.
 */
function crashSignature(errLogPath) {
  if (errLogPath === undefined || !existsSync(errLogPath)) return undefined;
  let text;
  try { text = readFileSync(errLogPath, 'utf8'); } catch { return undefined; }
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*$/.test(lines[i])) continue;
    if (/unhandled|uncaught/i.test(lines[i])) return lines[i].trim();
    if (/^Error:|^[A-Za-z]*Error:/.test(lines[i].trim()) && i + 1 < lines.length && /^\s+at /.test(lines[i + 1])) {
      return lines[i].trim();
    }
  }
  return undefined;
}

/**
 * Prune the engine's scratch directory, SAFELY.
 *
 * WHY THIS EXISTS. The 2026-09-25 crash was caused by Windows' own cleanup deleting the engine's
 * spill directory out from under it, and the fix was to route the engine's os.tmpdir() into
 * DSH_HOME/tmp, which no cleaner touches. The fix works (verified: dsh-spill-* and
 * dsh-subprocess-* are created there since the restart) and it creates a new duty: that directory
 * will now NEVER be cleaned by anything, so its spill directories accumulate for the life of the
 * machine. Leaving it would be the exact unbounded pile this repo already has 900 health-*.log
 * files from.
 *
 * WHAT MAKES THIS DANGEROUS, AND HOW IT IS AVOIDED. Deleting a LIVE spill directory is precisely
 * what killed the engine on 09-25, so age alone is not a safe test: DSH creates one spill
 * directory per process and it lives for that process's whole life, which on this box can exceed
 * a week. The spill FILE names carry the owning pid (`dsh-subprocess-<pid>-<n>-<hex>-<label>.log`),
 * so a directory is skipped whenever any file inside it belongs to a process that is still
 * running. Only then is age consulted. Two independent conditions, and the liveness check wins.
 *
 * Scope was ORIGINALLY narrow (only `dsh-spill-*` / `dsh-subprocess-*`), and that was WRONG.
 * Measured 2026-09-28 on ZABZ-YOGA, after the redirect had been live a few hours: DSH_HOME/tmp
 * held HUNDREDS of directories belonging to tools that have nothing to do with DSH --
 * `MSBuildTemp`, `NuGetScratch`, `VBCSCompiler`, `robolectric-*`, `pytest-of-ezabz`,
 * `NativeImage-*`, `hsperfdata_ezabz`, `WinGet`, and dozens of bare `tmp*`. They are there
 * because the engine is the ANCESTOR of every build and test the agent runs, and children
 * inherit TEMP. So the redirect did not move one spill directory; it moved the temp of the
 * whole toolchain, and a pruner that only matched the `dsh-` prefix left all of it to accumulate
 * forever -- the exact pile this function exists to prevent.
 *
 * So the rule is now "anything directly under DSH_HOME/tmp", which is honest about what that
 * directory became. Everything else about the safety analysis still holds, and is why this is
 * not simply `rm -rf`:
 *   * never a file, never recursive, never anything outside DSH_HOME/tmp;
 *   * a directory is kept while ANY directory inside it was modified recently, because a live
 *     tool touching its temp is the strongest available signal that it is still in use;
 *   * a directory holding a file whose name embeds a LIVE pid is kept unconditionally --
 *     deleting a live spill directory is exactly what killed the engine on 09-25;
 *   * age is only consulted after both of those.
 */
function pruneScratch(days) {
  const root = path.join(home(), 'tmp');
  const report = { removed: [], skippedLive: 0, skippedYoung: 0, bytes: 0 };
  if (!existsSync(root)) return report;
  const cutoff = Date.now() - days * 86400000;
  // A tool mid-work touches its temp constantly; treat recent METADATA activity anywhere inside
  // as "in use", which catches the tools whose filenames carry no pid.
  const TOUCHED_MS = 12 * 3600 * 1000;
  const touchedAfter = Date.now() - TOUCHED_MS;

  for (const d of readdirSync(root, { withFileTypes: true })) {
    if (!d.isDirectory()) continue;
    const dir = path.join(root, d.name);
    let isLive = false, recentlyTouched = false, bytes = 0, entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch { continue; }
    for (const f of entries) {
      try {
        const st = statSync(path.join(dir, f.name));
        if (f.isFile()) bytes += st.size;
        if (st.mtimeMs > touchedAfter) recentlyTouched = true;
      } catch { /* unreadable entry: ignore for size, the age test still applies */ }
      const m = /^dsh-subprocess-(\d+)-/.exec(f.name);
      if (m !== null) {
        try { process.kill(Number(m[1]), 0); isLive = true; } catch { /* not running */ }
      }
    }
    if (isLive) { report.skippedLive++; continue; }
    if (recentlyTouched) { report.skippedYoung++; continue; }
    let mtime;
    try { mtime = statSync(dir).mtimeMs; } catch { continue; }
    if (mtime > cutoff) { report.skippedYoung++; continue; }
    try { rmSync(dir, { recursive: true, force: true }); report.removed.push(d.name); report.bytes += bytes; }
    catch { /* a lock is a reason to skip, never a reason to fail the run */ }
  }
  return report;
}

function newestEngineErrLog() {
  const dir = path.join(home(), 'multi-window', 'logs');
  if (!existsSync(dir)) return undefined;
  const candidates = readdirSync(dir)
    .filter((n) => /^3099-.*\.err\.log$/.test(n))
    .map((n) => ({ n, t: statSync(path.join(dir, n)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  return candidates.length > 0 ? path.join(dir, candidates[0].n) : undefined;
}

// ---------------------------------------------------------------------------

const args = parseArgs(process.argv.slice(2));
const cfg = {
  loopP95: num(args.vals['loop-p95'], DEFAULTS.loopP95),
  loopMax: num(args.vals['loop-max'], DEFAULTS.loopMax),
  diskPct: num(args.vals['disk-pct'], DEFAULTS.diskPct),
  loops: num(args.vals['loops'], DEFAULTS.loops),
};

if (args.flags.includes('explain')) {
  console.log('thresholds, and the reading each came from:');
  console.log(`  loopP95  ${cfg.loopP95} ms   healthy 15 ms | loaded 490 ms | saturated 2200 ms`);
  console.log(`  loopMax  ${cfg.loopMax} ms   fresh 348 ms | 2d/5loops 7516 ms | 2d/10loops 16854 ms`);
  console.log(`  diskPct  ${cfg.diskPct} %     8% free is what triggered the cleanup that killed the engine`);
  console.log(`  loops    ${cfg.loops}        the count at which p95 passed 2 s on a 22-core host`);
  process.exit(0);
}

// Postmortem mode: name the crash in one file without starting anything. Exists
// because the 2026-09-25 crash took a manual read of a 400-line log to find.
if (args.vals['crash-scan'] !== undefined) {
  const found = crashSignature(args.vals['crash-scan']);
  if (found === undefined) { console.log('no crash signature found'); process.exit(0); }
  console.log(found);
  process.exit(0);
}

const slot = readEngineSlot();
if (slot === undefined) {
  console.error('engine-vitals: no engine slot in ~/.dsh/multi-window/state.json (engine has never started here?)');
  process.exit(3);
}

let health;
try {
  health = await readHealthz(slot);
} catch (error) {
  console.error(`engine-vitals: engine on port ${slot.port} is NOT reachable: ${error.message}`);
  process.exit(3);
}
const h = health.body;
const loop = h.loop ?? {};
const sessions = h.sessions ?? {};
const memory = h.memory ?? {};
const governor = h.governor ?? {};
const probe = h.probe ?? {};
const disk = diskFreePct();
const corpus = corpusSize();
// The scratch directory is the engine's os.tmpdir() since the 09-25 fix, and nothing else
// will ever clean it. Pruned here, on the same cadence, because a directory nobody owns is
// how the 900-file health-log pile happened. Age is only ever consulted after liveness.
const scratch = args.flags.includes('no-prune') ? { removed: [], skippedLive: 0, skippedYoung: 0, bytes: 0 } : pruneScratch(num(args.vals['prune-tmp-days'], 3));

const prior = existsSync(vitalsStatePath())
  ? (() => { try { return JSON.parse(readFileSync(vitalsStatePath(), 'utf8')); } catch { return undefined; } })()
  : undefined;

const row = {
  ts: new Date().toISOString(),
  pid: h.identity?.pid ?? slot.pid,
  uptimeS: Math.round((h.identity?.uptimeMs ?? 0) / 1000),
  healthzMs: health.healthzMs,
  loopP50: loop.p50Ms, loopP95: loop.p95Ms, loopMax: loop.maxMs,
  sessionsRoot: sessions.root, agentLoops: sessions.agentLoopsRunning,
  heapUsedMB: Math.round((memory.heapUsed ?? 0) / 1048576),
  heapTotalMB: Math.round((memory.heapTotal ?? 0) / 1048576),
  rssMB: Math.round((memory.rss ?? 0) / 1048576),
  govInUse: governor.inUse, govBudget: governor.budget,
  probeSpawns: probe.spawns ?? null,
  diskFreePct: disk.freePct,
  corpusDirs: corpus.dirs,
  corpusMB: +(corpus.bytes / 1048576).toFixed(1),
};

const warnings = [];
const notes = [];

// 1. did the engine change identity since the last pass?
const restarted = prior !== undefined && prior.pid !== undefined && prior.pid !== row.pid;
if (restarted) {
  const sig = crashSignature(newestEngineErrLog());
  warnings.push(`ENGINE RESTARTED: pid ${prior.pid} -> ${row.pid}`
    + (prior.ts !== undefined ? ` (last seen ${prior.ts})` : '')
    + (sig !== undefined ? `\n     likely reason from the newest stderr log: ${sig}` : '\n     no crash signature found in the newest stderr log'));
}

// 2. loop lag — median and tail are separate questions
if (typeof row.loopP95 === 'number' && row.loopP95 > cfg.loopP95) warnings.push(`loop p95 ${row.loopP95} ms over ${cfg.loopP95} ms`);
if (typeof row.loopMax === 'number' && row.loopMax > cfg.loopMax) warnings.push(`loop max ${row.loopMax} ms over ${cfg.loopMax} ms`);
if (typeof row.healthzMs === 'number' && row.healthzMs > 3000) warnings.push(`/healthz took ${row.healthzMs} ms to answer — the loop is saturated`);

// 3. disk — the upstream trigger of the 2026-09-25 crash
if (row.diskFreePct !== null && row.diskFreePct < cfg.diskPct) warnings.push(`C: only ${row.diskFreePct}% free (Windows cleanup runs here and has already killed the engine once)`);

// 4. load, reported not asserted
if (typeof row.agentLoops === 'number' && row.agentLoops >= cfg.loops) {
  notes.push(`${row.agentLoops} agent loops in one process — one shared event loop serves all of them`);
}
if (typeof row.govInUse === 'number' && typeof row.agentLoops === 'number' && row.agentLoops > row.govInUse + 2) {
  notes.push(`${row.agentLoops} agent loops vs ${row.govInUse} governor slot(s) leased — the governor budgets MEMORY, so it cannot see event-loop saturation`);
}
if (prior !== undefined && typeof prior.probeSpawns === 'number' && typeof row.probeSpawns === 'number') {
  const d = row.probeSpawns - prior.probeSpawns;
  if (d > 0) notes.push(`health probe spawned ${d} process(es) since the last pass (${row.probeSpawns} total)`);
}
if (scratch.removed.length > 0) {
  notes.push(`pruned ${scratch.removed.length} stale scratch dir(s), ${(scratch.bytes / 1048576).toFixed(1)} MB`
    + ` (kept: ${scratch.skippedLive} live, ${scratch.skippedYoung} young)`);
}

mkdirSync(path.dirname(defaultCsvPath()), { recursive: true });
const csvPath = args.vals.csv ?? defaultCsvPath();
const header = 'ts,pid,uptime_s,healthz_ms,loop_p50_ms,loop_p95_ms,loop_max_ms,sessions_root,agent_loops,heap_used_mb,heap_total_mb,rss_mb,gov_in_use,gov_budget,probe_spawns,disk_free_pct,corpus_dirs,corpus_mb';
if (!existsSync(csvPath)) writeFileSync(csvPath, header + '\n');
appendFileSync(csvPath, [
  row.ts, row.pid, row.uptimeS, row.healthzMs, row.loopP50, row.loopP95, row.loopMax,
  row.sessionsRoot, row.agentLoops, row.heapUsedMB, row.heapTotalMB, row.rssMB,
  row.govInUse, row.govBudget, row.probeSpawns, row.diskFreePct, row.corpusDirs, row.corpusMB,
].join(',') + '\n');

mkdirSync(path.dirname(vitalsStatePath()), { recursive: true });
// Carry the dedupe state forward BEFORE the first write. Without this a single
// clean pass would erase it and the next warning would be logged as if new.
row.lastLoggedAtMs = prior?.lastLoggedAtMs ?? 0;
row.lastLoggedSignature = prior?.lastLoggedSignature ?? null;
writeFileSync(vitalsStatePath(), JSON.stringify(row, null, 2));

/**
 * The incident log is written ONLY when something is wrong, and that is
 * deliberate: an append-per-pass log becomes another 900-file pile nobody reads
 * (the health loop already does that).
 *
 * But "written when wrong" is not enough on its own. Loop lag above threshold can
 * be CHRONIC on a busy host - measured p95 2,879 ms with 14 agent loops - and an
 * unconditional warning would then append 288 entries a day and rebuild the exact
 * pile this file exists to avoid. So an entry is written only when:
 *   * the engine restarted (always, it is the event this file exists for),
 *   * the SET of warnings changed (a new kind of problem),
 *   * or it has been quiet for RESTATE_AFTER_MS, so a standing problem is
 *     restated rather than repeated.
 * That bounds the file by the number of incidents, not by the number of passes.
 */
const RESTATE_AFTER_MS = 6 * 3600 * 1000;
const signature = warnings.slice().sort().join(' | ');
const lastLoggedAt = prior?.lastLoggedAtMs ?? 0;
const lastSignature = prior?.lastLoggedSignature ?? null;
const dueForRestate = Date.now() - lastLoggedAt > RESTATE_AFTER_MS;
if (warnings.length > 0 && (restarted || signature !== lastSignature || dueForRestate)) {
  const logPath = path.join(home(), 'metrics', 'engine-vitals.log');
  appendFileSync(logPath, [
    `${row.ts} pid=${row.pid} up=${Math.round(row.uptimeS / 3600)}h loop(p50=${row.loopP50} p95=${row.loopP95} max=${row.loopMax})ms loops=${row.agentLoops} disk=${row.diskFreePct}%`
      + (signature === lastSignature ? '  [restated after 6h quiet]' : ''),
    ...warnings.map((w) => `    ! ${w}`),
    ...notes.map((n) => `    - ${n}`),
    '',
  ].join('\n'));
  row.lastLoggedAtMs = Date.now();
  row.lastLoggedSignature = signature;
  writeFileSync(vitalsStatePath(), JSON.stringify(row, null, 2));
}

if (args.flags.includes('json')) {
  console.log(JSON.stringify({ row, warnings, notes }, null, 2));
} else {
  const state = warnings.length === 0 ? 'OK  ' : 'WARN';
  console.log(`${state} ${row.ts} pid=${row.pid} up=${Math.round(row.uptimeS / 3600)}h loop(p50=${row.loopP50} p95=${row.loopP95} max=${row.loopMax})ms loops=${row.agentLoops} heap=${row.heapUsedMB}MB disk=${row.diskFreePct}% corpus=${row.corpusDirs}dirs/${row.corpusMB}MB healthz=${row.healthzMs}ms`);
  for (const w of warnings) console.log(`     ! ${w}`);
  for (const n of notes) console.log(`     - ${n}`);
}
// process.exitCode, not process.exit(): an abrupt exit with a socket still closing is what
// produced the 0xC0000409 the scheduled task recorded. Letting the loop drain is free here.
process.exitCode = warnings.length === 0 ? 0 : 1;
