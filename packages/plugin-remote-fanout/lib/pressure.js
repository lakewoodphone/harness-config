/**
 * Pressure: the local machine's own saturation, measured where a child is placed.
 *
 * THE GAP THIS CLOSES, MEASURED
 * The placement path asked a broker where work should run, and dispatched to the
 * node it named. Nothing in that path ever looked at *this* machine. So on
 * 2026-09-17 the owner's laptop sat saturated with 18 agent loops executing and
 * 39 live sessions while the placement ledger recorded no placement all day
 * (`docs/mesh/109-pressure-routing.md` §1). His words: *"if the laptop is used
 * up, why didn't dsh start offloading more to the mesh, isn't that the point?"*
 * The mesh is a *client* of an offer: a node that never offers work never gets
 * relief. This module is the missing sensor, and `placement.js` is where the
 * offer is made.
 *
 * WHAT IS MEASURED, AND FROM WHERE
 *
 *   commitBytes     `\Memory\Committed Bytes` — the quantity `84-calibration.md`
 *                   §1.3 measures the per-turn cost in, and the quantity the
 *                   broker's own reasoning uses. NOT `swapUsedPct`: §5.2 proved
 *                   that field is `max(0, committed − physical) /
 *                   (commitLimit − physical) × 100` and reads 0.0 across the
 *                   whole band it claims to warn about.
 *   physicalBytes   total physical RAM.
 *   availableBytes  physical memory available right now (the OS's own number,
 *                   the same quantity `Available MBytes` reports).
 *   commitLimitBytes / commitAvailableBytes   the commit ceiling and what is
 *                   left under it — the only number that says an ALLOCATION
 *                   would fail.
 *   agentsRunning   agent loops executing on this machine (the engine's own
 *                   session census), plus `nodeProcesses` from the same read as
 *                   an independent cross-check.
 *   at / ageMs / source   provenance. Every reading says where it came from and
 *                   how old it is; a reading that cannot say so is not a reading.
 *
 * WHY THE HOT PATH DOES NOT SHELL OUT (AND WHAT IT DOES INSTEAD)
 * A `pwsh` process costs ~540-700 ms on this host (measured, the harness's own
 * tool-cost audit) and a dispatch already spends one ssh. So the reader has one
 * cheap source and one bounded fallback:
 *
 *   1. `<DSH_HOME>/health/processes.json`, written every 5 s by
 *      `plugin-health`'s sampler with `GlobalMemoryStatusEx` (one P/Invoke,
 *      10 ms — `snapshot.ps1`'s own header measures it against 286 ms for the
 *      CIM read). Reading it is one `readFileSync` of a ~60 KB file: p50 0.76 ms
 *      for a file this size on this host. This is the normal path and it spawns
 *      nothing.
 *   2. Only when that file is missing or older than `maxAgeMs` does the reader
 *      run its own tiny probe — at most one in flight, at most one per
 *      `probeIntervalMs`, result cached in
 *      `<DSH_HOME>/mesh/pressure/last-probe.json` and read synchronously next
 *      time. The probe never blocks the dispatch that triggered it: a reading
 *      that cannot be had is reported as `unknown`, never guessed.
 *
 * WHAT THIS MODULE DELIBERATELY DOES NOT DO
 *   * It does not refuse on the commit-to-physical ratio alone. That ratio
 *     exceeded 100 % on this laptop while the machine had 7.4 GiB of commit
 *     headroom, 7.6 GiB of physical memory available and 194 MB resident in the
 *     pagefile — i.e. no pressure at all. A rule that fires there would be the
 *     fifth counter in this program to mislead a reader
 *     (`docs/mesh/84-calibration.md` §5.5 lists the first four). See
 *     `decidePressure` and `docs/mesh/109-pressure-routing.md` §2.
 *   * It does not invent a number. A missing reading is `band: 'unknown'` and
 *     the dispatcher behaves exactly as it did before this module existed.
 *   * It has no default node, no policy of its own about *which* remote node,
 *     and no opinion the broker cannot override.
 */

import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import path from 'node:path';

import { NODES } from './nodes.js';

/** The DSH home this engine was started with. Same rule as plugin-health's. */
export function defaultDshHome(env = process.env) {
  const home = typeof env.DSH_HOME === 'string' && env.DSH_HOME.trim() !== '' ? env.DSH_HOME : path.join(homedir(), '.dsh');
  return home;
}

/** The health snapshot `plugin-health` writes. Read, never written, by this package. */
export function defaultSnapshotFile(env = process.env) {
  return path.join(defaultDshHome(env), 'health', 'processes.json');
}

/** Where this module's own fallback probe caches its last reading. */
export function defaultProbeDir(env = process.env) {
  return path.join(defaultDshHome(env), 'mesh', 'pressure');
}

// ─────────────────────────────────────────────────────────────────────────────
// THE THRESHOLDS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * At or above this share of physical RAM committed, a new child MUST be offered
 * to the mesh rather than kept here.
 *
 * Arithmetic (docs/mesh/109-pressure-routing.md §2, on this laptop's measured
 * numbers): physical 31.62 GiB, one extra concurrent agent turn costs
 * **403 MiB** of commit (84-calibration §3, level-mean fit r²=0.948, honest CI
 * 270-530 MiB). 85 % of physical is 26.9 GiB committed, leaving ~4.7 GiB — room
 * for ~11 more turns. Below that the machine is not the worst place to put one
 * more agent; at or above it, the next node that has room is a better answer
 * than this one, which is all this threshold asserts.
 */
export const HIGH_COMMIT_PHYSICAL_PCT = 0.85;

/**
 * At or above this share of physical RAM committed, a LOCAL spawn is refused.
 *
 * Arithmetic: 92 % of 31.62 GiB is 29.1 GiB — 2.5 GiB, or ~6 of the measured
 * 403 MiB turns, from the commit limit. `84-calibration.md` measured that a
 * machine in this band with a pagefile in play turns every process's memory
 * access into pagefile traffic, and `\Memory\Pages Input/sec` reached
 * 233,604/s on this host from module loading alone.
 */
export const CRITICAL_COMMIT_PHYSICAL_PCT = 0.92;

/**
 * The refusal's second half, and the reason it is required.
 *
 * Commit-to-physical is a ratio between an *accounting* number and a *hardware*
 * number, and on this machine the accounting number regularly exceeds the
 * hardware one while nothing is wrong: measured 2026-09-17 22:12 local,
 * committed 37.95 GiB against 31.62 GiB physical (120 %) with **7.4 GiB of commit
 * headroom, 7.6 GiB of physical available and a pagefile holding 194 MB**. On a
 * machine whose commit limit sits far above its RAM — the desktop's limit was
 * 69,269 MiB against 65,173 MiB physical — a refusal on the ratio alone would
 * refuse work on a machine with tens of gigabytes free.
 *
 * So a refusal needs BOTH: the commit ratio above the critical line AND less
 * than this much physical memory actually available. 1.5 GiB is ~3.8 of the
 * measured 403 MiB turns: below it there is not enough room to honour the child
 * being asked for, which is the only claim a refusal is entitled to make.
 */
export const REFUSE_AVAILABLE_FLOOR_BYTES = 1536 * 1024 * 1024;

/** How stale a health snapshot may be before the reader stops trusting it. */
export const DEFAULT_MAX_AGE_MS = 30_000;

/** The self-probe's two bounds: how often it may run, and how long it may take. */
export const DEFAULT_PROBE_INTERVAL_MS = 5_000;
/**
 * The probe's own timeout, and why it is generous.
 *
 * It costs a dispatch NOTHING — the probe's result is read by the next dispatch,
 * never by the one that started it — so the only thing a tight bound buys is a
 * higher failure rate on a machine that is already busy. Measured on ZABZ-YOGA
 * 2026-09-17 22:35 with 30+ `node.exe` processes and 41 GiB committed: the same
 * script that answered in ~1.2 s on an idle desktop was killed at 4,000 ms
 * twice, and the reader correctly fell back to `unknown`. 12 s is ~3x the
 * measured worst case, and the probe is still one process at a time.
 */
export const DEFAULT_PROBE_TIMEOUT_MS = 12_000;

/**
 * The probe script, kept as text because this package ships no `.ps1` — it is
 * junctioned into a profile's `node_modules` and resolved through the real path,
 * so a file beside this one is not findable by a path computed at runtime.
 * `GlobalMemoryStatusEx` is the same call `plugin-health/lib/snapshot.ps1` uses,
 * for the same measured reason: 10 ms against 286 ms for the equivalent CIM
 * read, and no WMI worker process into the bargain.
 *
 * It prints ONE line of JSON. It writes nothing and it cannot loop.
 */
export const PROBE_SCRIPT = [
  "$ErrorActionPreference = 'Stop'",
  "Add-Type -TypeDefinition @'",
  'using System;',
  'using System.Runtime.InteropServices;',
  'public static class DshPressure {',
  '    [StructLayout(LayoutKind.Sequential)]',
  '    struct MEMORYSTATUSEX {',
  '        public uint dwLength;',
  '        public uint dwMemoryLoad;',
  '        public ulong ullTotalPhys;',
  '        public ulong ullAvailPhys;',
  '        public ulong ullTotalPageFile;',
  '        public ulong ullAvailPageFile;',
  '        public ulong ullTotalVirtual;',
  '        public ulong ullAvailVirtual;',
  '        public ulong ullAvailExtendedVirtual;',
  '    }',
  '    [DllImport("kernel32.dll", SetLastError = true)]',
  '    static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX status);',
  '    public static long[] Read() {',
  '        var status = new MEMORYSTATUSEX();',
  '        status.dwLength = (uint)Marshal.SizeOf(typeof(MEMORYSTATUSEX));',
  '        if (!GlobalMemoryStatusEx(ref status)) return new long[] { 0, 0, 0, 0, 0 };',
  '        return new long[] {',
  '            (long)status.ullTotalPhys,',
  '            (long)status.ullAvailPhys,',
  '            (long)status.ullTotalPageFile,',
  '            (long)status.ullAvailPageFile,',
  '            (long)status.dwMemoryLoad',
  '        };',
  '    }',
  '}',
  "'@",
  '$m = [DshPressure]::Read()',
  '$totalPhys = $m[0]; $availPhys = $m[1]; $commitLimit = $m[2]; $commitFree = $m[3]',
  '# COMMITTED BYTES, IN ONE TERM, AND WHY IT IS NOT A SUM OF TWO.',
  '# `GlobalMemoryStatusEx` returns the commit limit in `ullTotalPageFile` and the',
  '# commit AVAILABLE in `ullAvailPageFile` — their difference IS the commit charge,',
  '# which is the whole reason this needs no arithmetic. Measured 2026-09-17 on',
  '# ZABZ-YOGA: the obvious-looking',
  '#   (totalPhys - availPhys) + (commitLimit - commitFree)',
  '# answered 66,878 MiB against the counter\'s 40,695 MiB — a 64 % overstatement,',
  '# because the second term already contains the first: physical memory IS part of',
  '# the commit limit. `docs/mesh/109-pressure-routing.md` §5 records the defect and',
  '# the two-term reading that replaced it.',
  '$commit = $commitLimit - $commitFree',
  '$procs = @(Get-Process -ErrorAction SilentlyContinue).Count',
  '$node = @(Get-Process -Name node -ErrorAction SilentlyContinue).Count',
  '[pscustomobject]@{',
  '  totalPhysBytes       = [long]$totalPhys',
  '  availPhysBytes       = [long]$availPhys',
  '  commitLimitBytes     = [long]$commitLimit',
  '  commitAvailableBytes = [long]$commitFree',
  '  commitBytes          = [long]$commit',
  '  memoryLoadPercent    = [int]$m[4]',
  '  processes            = [int]$procs',
  '  nodeProcesses        = [int]$node',
  '} | ConvertTo-Json -Compress',
].join('\n');

// ─────────────────────────────────────────────────────────────────────────────
// READING
// ─────────────────────────────────────────────────────────────────────────────

const percent = (part, whole) => (whole > 0 ? Math.round((part / whole) * 1000) / 10 : null);
const round = (value) => (Number.isFinite(value) ? Math.round(value) : null);

/**
 * A reading that could not be made. Every consumer must be able to tell this
 * apart from a healthy machine, which is why `band` is an explicit value.
 */
export function unknownPressure(why, { at = Date.now(), source = 'none' } = {}) {
  return {
    band: 'unknown',
    why,
    source,
    at: new Date(at).toISOString(),
    ageMs: null,
    commitBytes: null,
    physicalBytes: null,
    commitLimitBytes: null,
    commitAvailableBytes: null,
    availableBytes: null,
    memoryLoadPercent: null,
    commitToPhysicalPct: null,
    commitToLimitPct: null,
    availablePct: null,
    commitAvailablePct: null,
    agentsRunning: null,
    nodeProcesses: null,
    toolRunnerProcesses: null,
  };
}

/**
 * Shape one measured reading. `measuredAt` is when the OS was read — not when
 * this function ran — because `84-calibration.md` §5.5 measured that stamping a
 * row with the start of a window and filling it from the end halves the slope
 * it appears to show.
 *
 * @param {object} raw
 * @param {number} raw.commitBytes
 * @param {number} raw.physicalBytes
 * @param {number} [raw.availableBytes]
 * @param {number} [raw.commitLimitBytes]
 * @param {number} [raw.commitAvailableBytes]
 * @param {number} [raw.memoryLoadPercent]
 * @param {number} [raw.agentsRunning]
 * @param {number} [raw.nodeProcesses]
 * @param {number} measuredAt epoch ms the OS was read
 * @param {number} now epoch ms now
 * @param {string} source where the numbers came from
 */
export function shapePressure(raw, { measuredAt, now, source, thresholds = {} } = {}) {
  const high = thresholds.high ?? HIGH_COMMIT_PHYSICAL_PCT;
  const critical = thresholds.critical ?? CRITICAL_COMMIT_PHYSICAL_PCT;
  const floorBytes = thresholds.availableFloorBytes ?? REFUSE_AVAILABLE_FLOOR_BYTES;
  const commitBytes = round(raw?.commitBytes);
  const physicalBytes = round(raw?.physicalBytes);
  if (!(commitBytes > 0) || !(physicalBytes > 0)) {
    return unknownPressure('the operating system returned no committed-bytes or physical-memory reading', { at: now, source });
  }
  const availableBytes = Number.isFinite(raw.availableBytes) ? round(raw.availableBytes) : null;
  const commitLimitBytes = Number.isFinite(raw.commitLimitBytes) ? round(raw.commitLimitBytes) : null;
  const commitAvailableBytes = Number.isFinite(raw.commitAvailableBytes) ? round(raw.commitAvailableBytes) : null;
  const commitToPhysical = commitBytes / physicalBytes;
  // THE REFUSAL, both halves, in one place. See REFUSE_AVAILABLE_FLOOR_BYTES.
  const availableStarved = availableBytes === null ? true : availableBytes < floorBytes;
  const band = commitToPhysical >= critical && availableStarved
    ? 'critical'
    : commitToPhysical >= high
      ? 'high'
      : 'ok';
  return {
    band,
    why: band === 'ok'
      ? `committed ${percent(commitBytes, physicalBytes)} % of physical, below the ${Math.round(high * 100)} % line`
      : band === 'high'
        ? `committed ${percent(commitBytes, physicalBytes)} % of physical (at or above ${Math.round(high * 100)} %): this machine is not the place for one more agent`
        : `committed ${percent(commitBytes, physicalBytes)} % of physical (at or above ${Math.round(critical * 100)} %) AND only ${round(availableBytes / 1048576)} MiB physical memory available (below the ${round(floorBytes / 1048576)} MiB floor): this machine has no room to honour another turn`,
    source,
    at: new Date(measuredAt).toISOString(),
    ageMs: Number.isFinite(now) && Number.isFinite(measuredAt) ? Math.max(0, now - measuredAt) : null,
    commitBytes,
    physicalBytes,
    commitLimitBytes,
    commitAvailableBytes,
    availableBytes,
    memoryLoadPercent: Number.isFinite(raw.memoryLoadPercent) ? raw.memoryLoadPercent : null,
    commitToPhysicalPct: percent(commitBytes, physicalBytes),
    commitToLimitPct: commitLimitBytes === null ? null : percent(commitBytes, commitLimitBytes),
    availablePct: availableBytes === null ? null : percent(availableBytes, physicalBytes),
    commitAvailablePct: commitLimitBytes === null || commitAvailableBytes === null ? null : percent(commitAvailableBytes, commitLimitBytes),
    agentsRunning: Number.isFinite(raw.agentsRunning) ? raw.agentsRunning : null,
    nodeProcesses: Number.isFinite(raw.nodeProcesses) ? raw.nodeProcesses : null,
    toolRunnerProcesses: Number.isFinite(raw.toolRunnerProcesses) ? raw.toolRunnerProcesses : null,
    availableStarved,
  };
}

/** Parse `plugin-health`'s snapshot document into a reading, or `undefined`. */
export function readingFromSnapshot(snapshot, { now = Date.now(), maxAgeMs = DEFAULT_MAX_AGE_MS, thresholds = {} } = {}) {
  const system = snapshot?.system;
  if (system === null || typeof system !== 'object') return undefined;
  const commitLimitBytes = Number(system.commitLimitBytes);
  const commitAvailableBytes = Number(system.commitAvailableBytes);
  const physicalBytes = Number(system.totalPhysBytes);
  if (!Number.isFinite(commitLimitBytes) || !Number.isFinite(commitAvailableBytes) || !Number.isFinite(physicalBytes)) return undefined;
  const measuredAt = Date.parse(String(snapshot.at ?? ''));
  if (!Number.isFinite(measuredAt)) return undefined;
  if (now - measuredAt > maxAgeMs) return undefined;
  const processes = Array.isArray(snapshot.processes) ? snapshot.processes : undefined;
  const nodeRows = processes === undefined ? undefined : processes.filter((row) => /^node(\.exe)?$/i.test(String(row?.name ?? '')));
  const enginePid = Number(snapshot.enginePid);
  const engineChildren = processes === undefined || !Number.isInteger(enginePid)
    ? undefined
    : processes.filter((row) => Number(row?.ppid) === enginePid);
  return shapePressure({
    commitBytes: commitLimitBytes - commitAvailableBytes,
    physicalBytes,
    availableBytes: Number(system.availPhysBytes),
    commitLimitBytes,
    commitAvailableBytes,
    memoryLoadPercent: Number(system.memoryLoadPercent),
    nodeProcesses: nodeRows === undefined ? undefined : nodeRows.length,
    // THE TOOL-RUNNER COUNT IS A FLOOR ON THE LOCAL AGENT COUNT, and it is
    // labelled as one: `processes.json` is the engine's own process tree, so a
    // direct `node` child of the engine is a runner process — the same
    // classification `plugin-health/lib/processes.js` makes. A remote child is
    // NOT in this tree (it runs on another machine), which is exactly the
    // limitation `agentsRunning` from the live census exists to fix.
    toolRunnerProcesses: engineChildren === undefined
      ? undefined
      : engineChildren.filter((row) => /^node(\.exe)?$/i.test(String(row?.name ?? ''))).length,
  }, { measuredAt, now, source: 'plugin-health snapshot (GlobalMemoryStatusEx, refreshed every 5 s)', thresholds });
}

/** Parse this module's own probe's JSON into a reading, or `undefined`. */
export function readingFromProbe(probe, { now = Date.now(), maxAgeMs = DEFAULT_MAX_AGE_MS, thresholds = {} } = {}) {
  if (probe === null || typeof probe !== 'object') return undefined;
  const measuredAt = Number(probe.at);
  if (!Number.isFinite(measuredAt)) return undefined;
  if (now - measuredAt > maxAgeMs) return undefined;
  return shapePressure({
    commitBytes: Number(probe.commitBytes),
    physicalBytes: Number(probe.totalPhysBytes),
    availableBytes: Number(probe.availPhysBytes),
    commitLimitBytes: Number(probe.commitLimitBytes),
    commitAvailableBytes: Number(probe.commitAvailableBytes),
    memoryLoadPercent: Number(probe.memoryLoadPercent),
    nodeProcesses: Number(probe.nodeProcesses),
  }, { measuredAt, now, source: 'this package\'s own probe (GlobalMemoryStatusEx, spawned at most once per interval)', thresholds });
}

// ─────────────────────────────────────────────────────────────────────────────
// THE READER
// ─────────────────────────────────────────────────────────────────────────────

const readJson = (file) => {
  try {
    const parsed = JSON.parse(readFileSync(file, 'utf8'));
    return parsed !== null && typeof parsed === 'object' ? parsed : undefined;
  } catch {
    return undefined;
  }
};

/**
 * The reader the placement path uses: one cached reading, refreshed from the
 * cheapest source that can answer, never blocking on a probe it started.
 *
 * @param {object} [options]
 * @param {string} [options.snapshotFile]  plugin-health's snapshot
 * @param {string} [options.probeDir]      where this module's own probe caches
 * @param {number} [options.maxAgeMs]
 * @param {number} [options.probeIntervalMs]
 * @param {Function} [options.spawnImpl]   injected for tests
 * @param {() => number} [options.now]
 * @param {(reading: object) => void} [options.onReading] told every fresh reading
 * @param {() => (number|undefined)} [options.agentsRunning] the engine's own census
 */
export function createPressureReader(options = {}) {
  const snapshotFile = options.snapshotFile ?? defaultSnapshotFile();
  const probeDir = options.probeDir ?? defaultProbeDir();
  const maxAgeMs = Number.isFinite(options.maxAgeMs) ? options.maxAgeMs : DEFAULT_MAX_AGE_MS;
  const probeIntervalMs = Number.isFinite(options.probeIntervalMs) ? options.probeIntervalMs : DEFAULT_PROBE_INTERVAL_MS;
  const probeTimeoutMs = Number.isFinite(options.probeTimeoutMs) ? options.probeTimeoutMs : DEFAULT_PROBE_TIMEOUT_MS;
  const spawnImpl = typeof options.spawnImpl === 'function' ? options.spawnImpl : spawn;
  const now = typeof options.now === 'function' ? options.now : () => Date.now();
  const logger = options.logger;
  const thresholds = options.thresholds ?? {};
  const shell = options.shell ?? process.env.DSH_PRESSURE_POWERSHELL ?? 'pwsh';
  const supported = options.supported ?? process.platform === 'win32';
  const census = typeof options.agentsRunning === 'function' ? options.agentsRunning : () => undefined;

  let lastReading;
  let lastAttemptAt = -Infinity;
  let probeInFlight = false;
  let spawns = 0;
  let probeErrors = 0;
  let lastProbeError = null;
  let agentCountErrors = 0;

  const probeFile = path.join(probeDir, 'last-probe.json');

  /** Decorate a reading with the engine's live agent census. Never throws. */
  function withAgents(reading) {
    if (reading === undefined) return undefined;
    try {
      const agents = census();
      if (Number.isFinite(agents)) reading.agentsRunning = agents;
    } catch (error) {
      agentCountErrors += 1;
      if (agentCountErrors === 1) logger?.warn?.(`remote-fanout: the agent census could not be read (${String(error?.message ?? error)}); the local generating-agent count is reported as null, not as zero`);
    }
    return reading;
  }

  function fromSnapshot() {
    const document = readJson(snapshotFile);
    return document === undefined ? undefined : readingFromSnapshot(document, { now: now(), maxAgeMs, thresholds });
  }

  function fromProbeCache() {
    const document = readJson(probeFile);
    return document === undefined ? undefined : readingFromProbe(document, { now: now(), maxAgeMs, thresholds });
  }

  /**
   * Start the fallback probe, at most one in flight and at most one per
   * interval. Its result is cached in a file for the NEXT dispatch to read, so
   * the dispatch that starts it is never delayed by it.
   */
  function startProbe() {
    if (!supported || probeInFlight) return;
    const at = now();
    if (at - lastAttemptAt < probeIntervalMs) return;
    lastAttemptAt = at;
    probeInFlight = true;
    spawns += 1;
    const startedAt = Date.now();
    let child;
    try {
      mkdirSync(probeDir, { recursive: true });
      child = spawnImpl(shell, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', PROBE_SCRIPT], {
        // `detached: false` for the reason plugin-health measured on this host:
        // a detached pwsh 7 exits 0 after ~160 ms having run nothing.
        detached: false,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
    } catch (error) {
      probeInFlight = false;
      probeErrors += 1;
      lastProbeError = String(error?.message ?? error);
      return;
    }
    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (why) => {
      if (settled) return;
      settled = true;
      probeInFlight = false;
      clearTimeout(timer);
      if (why !== undefined) {
        probeErrors += 1;
        lastProbeError = why;
        return;
      }
      let parsed;
      try {
        parsed = JSON.parse(stdout.trim());
      } catch (error) {
        probeErrors += 1;
        lastProbeError = `the probe printed something that is not JSON (${String(error?.message ?? error)}): ${stdout.trim().slice(0, 200)}`;
        return;
      }
      const reading = readingFromProbe({ ...parsed, at: startedAt }, { now: now(), maxAgeMs, thresholds });
      if (reading === undefined) {
        probeErrors += 1;
        lastProbeError = 'the probe answered without a usable memory reading';
        return;
      }
      try {
        mkdirSync(probeDir, { recursive: true });
        // Written to a temp name and renamed: a reader in another process must
        // never see a half-written document.
        const temp = `${probeFile}.tmp-${process.pid}`;
        writeFileSync(temp, `${JSON.stringify({ ...parsed, at: startedAt }, null, 2)}\n`, 'utf8');
        renameSync(temp, probeFile);
      } catch (error) {
        probeErrors += 1;
        lastProbeError = `the probe's reading could not be cached (${String(error?.message ?? error)})`;
        return;
      }
      lastReading = withAgents(reading);
    };
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* already gone */ }
      finish(`the probe did not answer within ${probeTimeoutMs} ms`);
    }, probeTimeoutMs);
    timer.unref?.();
    child.stdout?.on?.('data', (chunk) => { stdout += String(chunk); });
    child.stderr?.on?.('data', (chunk) => { stderr += String(chunk); });
    child.once?.('error', (error) => finish(`the probe could not be spawned (${String(error?.message ?? error)})`));
    child.once?.('close', (code) => finish(code === 0 ? undefined : `the probe exited ${code}${stderr.trim() === '' ? '' : `: ${stderr.trim().slice(0, 200)}`}`));
    if (typeof child.unref === 'function') child.unref();
  }

  return {
    /** The current reading. Cheap: one small file read in the normal case. */
    read() {
      const at = now();
      const snapshot = withAgents(fromSnapshot());
      if (snapshot !== undefined) {
        lastReading = snapshot;
        return snapshot;
      }
      const cached = withAgents(fromProbeCache());
      if (cached !== undefined) {
        lastReading = cached;
        return cached;
      }
      startProbe();
      // The reading that was last good is still the best answer available; but
      // its age travels with it, so a reader can discount it.
      if (lastReading !== undefined) return lastReading;
      const unknown = unknownPressure(
        supported
          ? `no pressure reading is available: ${snapshotFile} is missing or older than ${maxAgeMs} ms and this package's own probe has not answered yet${lastProbeError === null ? '' : ` (${lastProbeError})`}`
          : `this package reads local pressure from the Windows counters and this host is ${process.platform}`,
        { at, source: 'none' },
      );
      try {
        const agents = census();
        if (Number.isFinite(agents)) unknown.agentsRunning = agents;
      } catch {
        // The census failing must not turn a missing reading into a thrown one.
      }
      return unknown;
    },

    /** The reader's own cost and failures — the instrument reporting on itself. */
    probe() {
      return {
        snapshotFile,
        probeFile,
        supported,
        shell,
        maxAgeMs,
        probeIntervalMs,
        spawns,
        probeErrors,
        lastProbeError,
        agentCountErrors,
        inFlight: probeInFlight,
      };
    },
  };
}

let shared;
/** One reader per process, so a fleet's dispatches share one cache. */
export function sharedPressureReader(options = {}) {
  if (shared === undefined) shared = createPressureReader(options);
  return shared;
}

/** Reset the process-wide reader. Tests only. */
export function resetSharedPressureReader() {
  shared = undefined;
}

// ─────────────────────────────────────────────────────────────────────────────
// THE POLICY: prefer-remote (a policy, not a sensor)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The defect this closes, and what was measured.
 *
 * 2026-09-18: three dispatches that each believed they were aimed elsewhere all
 * produced a child running on the owner's laptop while a 32-core desktop sat
 * with 38 GiB free. The placement was CORRECT BY THE RULES AS WRITTEN -
 * `HIGH_COMMIT_PHYSICAL_PCT` is 0.85 and `CRITICAL_COMMIT_PHYSICAL_PCT` is 0.92
 * behind a 1.5 GiB availability floor - and the laptop sat far below both
 * lines, so the broker balanced onto it as soon as the bigger node filled.
 * There was no mechanism anywhere for "the owner is using this machine right
 * now", and there still is not one; see the next paragraph.
 *
 * WHY THIS IS A POLICY AND NOT A SENSOR. No cheap, non-lying signal for "a
 * human is driving this machine" exists in this package, and none was invented:
 *
 *   * `createPressureReader`'s `agentsRunning` census is the ENGINE's own
 *     session registry (`lib/index.js` passes `ctx.get('agents').list()` and
 *     counts `status === 'running'`). It counts agent loops EXECUTING, which is
 *     a fact about this engine and not about a human at the keyboard: an idle
 *     human with two background loops and a busy human with none are the same
 *     number to it, in both directions, and the count is `null` whenever the
 *     census cannot be read.
 *   * `plugin-health`'s snapshot carries memory counters and a process list and
 *     nothing else - no input-idle time and no active-session flag. A real
 *     signal would be `GetLastInputInfo`, which nothing in this tree samples,
 *     and which would cost a `pwsh` spawn (~540-700 ms measured on this host)
 *     on the very dispatch path this module exists to keep free.
 *
 * THE POLICY, AND THE INPUT IT ALREADY HAS. `/place` answers with the eligible
 * set it ranked (`eligible`, beside `node`, `tier`, `blockedBy` and
 * `rationale`). When that answer says there is at least one eligible node other
 * than this one, there is somewhere else to put the child, and this machine is
 * excluded from the ranking. When there is nowhere else, this machine is used
 * exactly as today. When the eligible set cannot be read from the answer,
 * NOTHING CHANGES and the reason says so: a reading that could not be made
 * never changes a decision - this module's own rule, and the rule that was
 * violated four times on this mesh in one day.
 *
 * WHERE IT IS EVALUATED, AND WHERE IT IS NOT. The policy is evaluated in the
 * `ok` band, which is the band the reported defect sits in (the laptop was far
 * below both lines). At or above the high line the thresholds have ALREADY
 * excluded the local node, so the policy has nothing to add, and when the
 * pressure reading is unavailable this module's rule is to behave exactly as
 * before - which the policy must not override.
 */
export const PREFER_REMOTE_POLICY = 'prefer-remote';

/**
 * IS IT ON BY DEFAULT? NO, and this is a decision rather than an oversight.
 *
 * Today's defect is that the DEFAULT treated a machine a human is using as an
 * ordinary worker. A fix that silently turned that default around on every
 * machine - including the three nodes nobody is sitting at, where it would
 * trade a local start-now for a remote queue the moment any other node is
 * eligible - would be the same mistake pointing the other way, and this change
 * carries no measurement that the trade is net-positive on any machine but the
 * one in the report. So it is an explicit opt-in (`preferRemote: true` in the
 * row, or `MESH_PREFER_REMOTE=1`), logged at boot by `lib/index.js` the same
 * way `placement: 'fixed'` is logged, and a deployment turns it on on purpose
 * after the placement ledger shows what it did.
 */
export const PREFER_REMOTE_DEFAULT = false;

/**
 * Read the broker's OWN answer for whether an eligible alternative to
 * `localNode` existed - or `known: false` when the answer cannot say, which is
 * never the same thing as "no".
 *
 * HOW THE ANSWER IS READ, AND WHERE IT STOPS BEING READABLE. `/place`'s
 * `eligible` field is the size of the pool the broker ranked for the tier it
 * chose (`mesh-broker/lib/broker.js`, `decide()`: `eligible: pool.length`).
 * Every pool except one is built from candidates that are reachable, that
 * accept the task, and that the CALLER did not exclude - so its size is "how
 * many nodes were in the ranking with this one", and subtracting this machine
 * when the broker named it gives the number of alternatives. The exception is
 * the `queued` tier (and the `internal-fault` last resort), whose pool is the
 * raw arena of EVERY placeable node: its size is not an eligible set and is
 * reported as unknown rather than read as evidence. An answer with no
 * `eligible` field, no `node`, or no local node name to compare against is
 * unknown for the same reason.
 *
 * @param {object|undefined|null} placement the broker's `/place` answer, or nothing when it has not been asked
 * @param {object} [options]
 * @param {string|null} [options.localNode] this machine's name in the broker's vocabulary
 * @returns {{known:boolean, count:number|null, alternatives:number|null, localChosen:boolean|null, why:string}}
 */
export function alternativeEligibility(placement, { localNode = null } = {}) {
  if (placement === null || typeof placement !== 'object') {
    return { known: false, count: null, alternatives: null, localChosen: null, why: 'the broker has not been asked, so there is no eligible set to read' };
  }
  const rawCount = placement.eligible;
  const count = rawCount === null || rawCount === undefined || rawCount === '' ? Number.NaN : Number(rawCount);
  if (!Number.isFinite(count) || count < 0) {
    return { known: false, count: null, alternatives: null, localChosen: null, why: `the broker's answer carried no eligible count (eligible=${JSON.stringify(rawCount ?? null)})` };
  }
  const chosen = typeof placement.node === 'string' && placement.node !== '' ? placement.node : null;
  if (chosen === null) {
    return { known: false, count, alternatives: null, localChosen: null, why: 'the broker did not name a node, so which machine it ranked cannot be read' };
  }
  if (localNode === null || localNode === undefined || localNode === '') {
    return { known: false, count, alternatives: null, localChosen: null, why: 'this machine could not be translated into the broker\'s node vocabulary, so "a node other than the local one" cannot be evaluated' };
  }
  if (placement.tier === 'queued' || placement.tier === 'internal-fault' || placement.tier === null || placement.tier === undefined) {
    return {
      known: false,
      count,
      alternatives: null,
      localChosen: chosen === localNode,
      why: `the broker answered from its "${placement.tier ?? 'unstated'}" tier, whose pool is every placeable node rather than the eligible set, so a count of ${count} cannot say whether an eligible node other than this one existed`,
    };
  }
  if (chosen !== localNode) {
    return {
      known: true,
      count,
      alternatives: Math.max(1, count),
      localChosen: false,
      why: `the broker named "${chosen}", not this machine, so at least one node other than this one was in the pool it ranked`,
    };
  }
  return {
    known: true,
    count,
    alternatives: Math.max(0, count - 1),
    localChosen: true,
    why: `the broker named this machine from a pool of ${count}, so ${Math.max(0, count - 1)} other eligible node(s) were ranked against it`,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// THE DECISION
// ─────────────────────────────────────────────────────────────────────────────

/** A reading that could not be made never changes a routing decision. */
export const PRESSURE_BANDS = Object.freeze(['ok', 'high', 'critical', 'unknown']);

/**
 * Turn a reading plus the state of the mesh into the decision the placement path
 * acts on. Pure, and the only place the thresholds are applied.
 *
 * The `prefer-remote` policy is evaluated here and ONLY in the `ok` band, and
 * only when `mesh.preferRemote` is true. Above the high line the thresholds
 * have already excluded the local node, so the policy has nothing to add; in
 * the `unknown` band this module's rule is to behave exactly as before a
 * reading existed, which the policy must not override.
 *
 * @param {object} reading a reading from `createPressureReader().read()`
 * @param {object} [mesh]
 * @param {boolean} [mesh.brokerReachable]   set only when the broker was actually asked and failed
 * @param {string}  [mesh.brokerError]       its code
 * @param {boolean} [mesh.preferRemote]      the `prefer-remote` policy (off by default: `PREFER_REMOTE_DEFAULT`)
 * @param {object}  [mesh.placement]         the broker's own `/place` answer, when one has been made; the eligible set is read from it
 * @returns {{decision:'ok'|'route-remote'|'refuse-local', reason:string, refuse:boolean, meshUnavailable:boolean, localNode:string|null, routeAwayFromLocal:boolean, policy?:string, eligible?:object}}
 */
export function decidePressure(reading, mesh = {}) {
  const localNode = mesh.localNode ?? null;
  const meshUnavailable = mesh.brokerReachable === false;
  const band = reading?.band ?? 'unknown';
  if (band === 'unknown') {
    return {
      decision: 'ok',
      reason: `no pressure reading (${reading?.why ?? 'unknown'}); behaving exactly as before this check existed`,
      refuse: false,
      meshUnavailable,
      localNode,
      routeAwayFromLocal: false,
    };
  }
  if (band === 'ok') {
    // THE POLICY, EVALUATED ABOVE THE THRESHOLDS AND NOT AS ONE.
    // `prefer-remote` is not a fifth line on the commit ratio; it is a
    // statement about WHERE work goes when there is a choice.
    if (mesh.preferRemote === true && !meshUnavailable) {
      const eligibility = alternativeEligibility(mesh.placement, { localNode });
      const shaped = { refuse: false, meshUnavailable, localNode, policy: PREFER_REMOTE_POLICY, eligible: eligibility };
      if (!eligibility.known) {
        return {
          ...shaped,
          decision: 'ok',
          routeAwayFromLocal: false,
          reason: `under no pressure: ${reading.why}; ${PREFER_REMOTE_POLICY} is ON but the eligible set could not be determined (${eligibility.why}), so the local node is NOT excluded and the placement is decided exactly as it was before the policy existed`,
        };
      }
      if (eligibility.localChosen === false) {
        return {
          ...shaped,
          decision: 'ok',
          routeAwayFromLocal: false,
          reason: `under no pressure: ${reading.why}; ${PREFER_REMOTE_POLICY} is ON and needed no exclusion - the broker named "${mesh.placement.node}", not this machine (${eligibility.why})`,
        };
      }
      if (eligibility.alternatives >= 1) {
        return {
          ...shaped,
          decision: 'route-remote',
          routeAwayFromLocal: true,
          reason: `under no pressure, but ${PREFER_REMOTE_POLICY} is ON and the broker's own eligible set held ${eligibility.alternatives} node(s) other than this machine (${eligibility.why}): the local node is excluded from the ranking and the child is offered to the mesh`,
        };
      }
      return {
        ...shaped,
        decision: 'ok',
        routeAwayFromLocal: false,
        reason: `under no pressure: ${reading.why}; ${PREFER_REMOTE_POLICY} is ON but there is no eligible node other than this machine (${eligibility.why}), so the local node is used exactly as today`,
      };
    }
    return {
      decision: 'ok',
      reason: `under no pressure: ${reading.why}`,
      refuse: false,
      meshUnavailable,
      localNode,
      routeAwayFromLocal: false,
    };
  }
  if (meshUnavailable) {
    // THE CASE THE BRIEF ASKS TO DECIDE EXPLICITLY: the mesh cannot be reached
    // AND this machine is over its high line. Refuse, at BOTH bands. Above the
    // high line the local option has already been declined — telling the broker
    // to exclude this node is the mechanism by which the work is offered to the
    // mesh — so with no mesh to offer it to, dispatching here would issue a
    // placement this decision has just declared unwanted, without recording that
    // it changed its mind. Nothing is dispatched, and the error says why.
    return {
      decision: 'refuse-local',
      reason: `this machine is under pressure (${reading.why}) AND the mesh cannot be reached`
        + (mesh.brokerError === undefined ? '' : ` (${mesh.brokerError})`)
        + ': the local option has been declined, there is no node to offer the child to, and nothing is dispatched',
      refuse: true,
      meshUnavailable: true,
      localNode,
      routeAwayFromLocal: true,
    };
  }
  if (band === 'critical') {
    return {
      decision: 'refuse-local',
      reason: `${reading.why}, and the mesh IS reachable, so remote placement is what is wanted`,
      refuse: true,
      meshUnavailable: false,
      localNode,
      routeAwayFromLocal: true,
    };
  }
  return {
    decision: 'route-remote',
    reason: `${reading.why}: the mesh is asked to take this child, and the local node is excluded from the ranking rather than forbidden`,
    refuse: false,
    meshUnavailable: false,
    localNode,
    routeAwayFromLocal: true,
  };
}

/**
 * This machine's node name in the broker's vocabulary, or `undefined`.
 *
 * Matched through `nodes.js`'s own allow-lists rather than by string equality,
 * because the broker names nodes by their Tailscale DNS label (`zabz-yoga-1`)
 * while the OS calls this machine `ZABZ-YOGA` — the same translation
 * `hostMatchesNode` exists for.
 */
export function localNodeName(host = hostname()) {
  const normalized = String(host ?? '').trim().toLowerCase().split('.')[0].replace(/-ts$/, '');
  if (normalized === '') return undefined;
  for (const [node, facts] of Object.entries(NODES)) {
    if (node.trim().toLowerCase() === normalized) return node;
    for (const candidate of Array.isArray(facts?.hosts) ? facts.hosts : []) {
      if (String(candidate).trim().toLowerCase().split('.')[0].replace(/-ts$/, '') === normalized) return node;
    }
  }
  return undefined;
}

/** One line a human reads: the reading, the decision, and what it acted on. */
export function describePressure(reading, decision) {
  if (reading?.band === 'unknown') return `pressure UNKNOWN — ${reading.why}; ${decision.reason}`;
  const mib = (bytes) => (Number.isFinite(bytes) ? `${Math.round(bytes / 1048576)} MiB` : '?');
  return [
    `pressure ${reading.band.toUpperCase()}`,
    `commit ${mib(reading.commitBytes)} of ${mib(reading.physicalBytes)} physical (${reading.commitToPhysicalPct} %)`,
    `commit free ${mib(reading.commitAvailableBytes)}${reading.commitAvailablePct === null ? '' : ` (${reading.commitAvailablePct} % of the limit)`}`,
    `available ${mib(reading.availableBytes)}`,
    `agents ${reading.agentsRunning ?? '?'} (node processes ${reading.nodeProcesses ?? '?'}, tool-call runners ${reading.toolRunnerProcesses ?? '?'})`,
    `read ${reading.ageMs === null ? '?' : `${reading.ageMs} ms ago`} from ${reading.source}`,
  ].join('; ');
}

/**
 * THE CHILD'S OWN REPORT LINE (docs/mesh/109-pressure-routing.md §3.2).
 *
 * A pressure-informed decision that is only in a ledger file is a decision the
 * model that made the call cannot see, and the next thing it does depends on it.
 * So the child's result carries the reason, the numbers it was made from, the
 * node that was chosen, and the sentence that says the local option was
 * declined — which is the sentence that answers the owner's question.
 *
 * @param {object} placement a placement record from `createNodePlacer().acquire()`
 * @param {string} [chosen] the node the child actually ran on, when different
 */
export function pressureLine(placement, chosen) {
  const reading = placement?.pressure;
  const decision = placement?.pressureDecision;
  if (reading === undefined || reading === null) return undefined;
  if (decision === undefined || decision === null) return undefined;
  const where = chosen === undefined || chosen === null || chosen === placement.node ? `"${placement.node}"` : `"${placement.node}" (the child's own report named ${chosen})`;
  const mib = (bytes) => (Number.isFinite(bytes) ? `${Math.round(bytes / 1048576)} MiB` : '?');
  if (reading.band === 'unknown') {
    return `NOT MEASURED — ${reading.why}; the placement was decided exactly as it was before this check existed, and it went to ${where}`;
  }
  const head = `${reading.band.toUpperCase()} — ${decision.decision}`;
  const numbers = `${mib(reading.commitBytes)} of ${mib(reading.physicalBytes)} physical committed (${reading.commitToPhysicalPct} %),`
    + ` commit free ${mib(reading.commitAvailableBytes)}, ${mib(reading.availableBytes)} physical available`;
  const what = decision.decision === 'route-remote'
    ? `the LOCAL option was declined and offered to the mesh as excluded; the child was placed on ${where}`
    : decision.decision === 'refuse-local'
      ? `the LOCAL option was REFUSED (${reading.why}) and the child was placed on ${where}`
      : `under no pressure: the local node was NOT excluded, and the child was placed on ${where}`;
  const conflict = placement.pressureConflict === undefined ? '' : `; ${placement.pressureConflict}`;
  return `${head} — ${what}; ${numbers}; ${decision.reason}${conflict}`;
}

/**
 * The one-line answer to "was the local option even considered?", for any band.
 *
 * `decision` is optional; when it carries a `policy`, the line names the policy
 * and its reason, so a placement changed by `prefer-remote` is readable from
 * the same line as the numbers it was made with.
 */
export function pressureCheckLine(reading, decision) {
  if (reading === undefined || reading === null) {
    return `local pressure has NOT been sampled; the local option was not measured, and is neither preferred nor declined (${HIGH_COMMIT_PHYSICAL_PCT} / ${CRITICAL_COMMIT_PHYSICAL_PCT} of physical committed are the lines, docs/mesh/109-pressure-routing.md)`;
  }
  if (reading.band === 'unknown') return `local pressure UNKNOWN — ${reading.why}`;
  const mib = (bytes) => (Number.isFinite(bytes) ? `${Math.round(bytes / 1048576)} MiB` : '?');
  const line = `local pressure ${reading.band.toUpperCase()} — ${mib(reading.commitBytes)} of ${mib(reading.physicalBytes)} physical committed`
    + ` (${reading.commitToPhysicalPct} %; lines: ${Math.round(HIGH_COMMIT_PHYSICAL_PCT * 100)} % to route remote, ${Math.round(CRITICAL_COMMIT_PHYSICAL_PCT * 100)} % to refuse local)`;
  return decision === undefined || decision === null || decision.policy === undefined
    ? line
    : `${line}; ${decision.policy} → ${decision.decision}: ${decision.reason}`;
}

/** Exported for tests and for `bin/mesh-pressure.mjs`. */
export { percent, round };
