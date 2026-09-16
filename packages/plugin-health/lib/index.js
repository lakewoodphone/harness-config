/**
 * plugin-health — the live health surface the engine never had.
 *
 * WHY THIS EXISTS
 * There is no health endpoint anywhere in DSH: `GET /healthz` is a static
 * fallback miss and returns 404, `NM/dsh-host-webserver` "knows no harness
 * concepts and serves no files", and grepping the whole host tree for
 * `process.memoryUsage|loadavg|cpuUsage|freemem|totalmem|process.uptime`
 * finds nothing. `dsh-session-stats` is a per-session projection
 * (turns/steps/tokens) and `dsh-session-telemetry` is a record handoff seam
 * whose only aggregate is a private Set. So when this machine froze, there was
 * no instrument on it that could say why — the diagnosis had to be
 * reconstructed from a static code audit (`_dsh-scale/10-dsh-source-audit.md`).
 *
 * This row is that missing instrument, and nothing else. It answers one
 * question — *what is the engine doing right now, and how much of the machine is
 * it using* — on three surfaces:
 *
 *   GET /healthz            JSON, for a script or a monitor
 *   GET /healthz?format=text a few lines a human reads
 *   the `engine_health` tool for the model, in the session that is asking
 *
 * WHAT IT REPORTS, AND WHY EACH IS THE RIGHT COUNTER
 *   loopLag    p50/p95/max of a self-timing interval. One event loop serves
 *              every window, so a blocked loop is every window hanging at once.
 *              Measured with our own timer (`lib/lag.js`) so the numbers are
 *              inspectable and bounded, not a histogram we cannot read.
 *   memory     rss/heap/external/arrayBuffers and the heap limit.
 *   system     physical total and available, commit charge and commit limit,
 *              and the Windows memory-load %. Physical availability is what
 *              decides whether new work can start; commit charge is what
 *              decides whether the machine pages.
 *   processes  total, thread total, engine threads and handles, and the engine's
 *              own descendants split into tool-call runners and MCP servers by
 *              name (`lib/processes.js` documents the classification).
 *   sessions   live agents, root sessions, subagent sessions, and how many agent
 *              loops are executing right now.
 *
 * WHY THE PROCESS NUMBERS COME FROM A CHILD PROCESS
 * Node cannot read another process's parent/threads/memory, and Windows has no
 * /proc. `lib/snapshot.ps1` answers that with what Windows already ships. It is
 * spawned on a timer with `stdio: 'ignore'` and `child.unref()`, and its result
 * is picked up from a file — the engine never waits on it, never reads its
 * stdout, and a slow snapshot can never block the loop it is measuring.
 * Overlapping runs are impossible by construction (the next spawn is skipped
 * while one is alive), so the sampler cannot accumulate processes.
 *
 * HONESTY RULES THAT ARE ENCODED HERE, NOT JUST INTENDED
 *   * Every reading carries `at` and `ageMs`. A stale snapshot is labelled
 *     `stale: true`; `fresh` is false and the route answers 503 with
 *     `"probe": "stale"`. An absent snapshot is reported as absent, never as
 *     health.
 *   * No number is invented. If the process table has never been read, the
 *     process/session-process fields are `null` and `snapshot.error` says why.
 *   * The probe reports its own cost: `spawns`, `lastSpawnMs`, `lastReadMs`,
 *     so "is the instrument itself part of the problem" is answerable.
 */

import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { LagSampler } from './lag.js';
import { censusAgents, identityOf, memoryOf, humanAge, mib } from './sessions.js';
import { classifyProcesses, privateBytesOf } from './processes.js';
import {
  registerListAgents,
  listingStats,
  readListingStats,
  defaultStatsFile,
} from './agents-list.js';
import { registerAdmissionGovernor } from './admission-tool.js';
import { governorRoot, status as governorStatus } from './governor.js';

const name = 'engine-health';

/** This module's directory — `import.meta.url` is the only reliable anchor for
 * a package that may be reached through a junction or a symlink. */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SNAPSHOT_SCRIPT = path.join(HERE, 'snapshot.ps1');

/** Route paths. One exact route, two representations. */
const ROUTE = '/healthz';

/** The model-facing tool name. Deliberately not `health` — see the preset note. */
const READOUT_TOOL = 'engine_health';

/**
 * The process snapshot lives outside the repo: it is machine state, it is
 * ~58 KB, and it must never be committed. `DSH_HOME` is honored so a second
 * engine on a test home cannot read the live engine's numbers.
 */
function defaultSnapshotPath() {
  const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
  return path.join(home, 'health', 'processes.json');
}

/**
 * Resolve the interpreter for the snapshot script.
 *
 * `pwsh` (PowerShell 7) is preferred; `powershell.exe` (5.1) is the fallback
 * because a Windows Server or a stripped image may have only the latter. The
 * choice is published in the readout, because "which shell produced these
 * numbers" is part of their provenance.
 */
function resolveShell() {
  return process.env.DSH_HEALTH_POWERSHELL || (process.platform === 'win32' ? 'pwsh' : 'pwsh');
}

/**
 * One process sampler. Owns exactly one timer and at most one child process.
 *
 * The whole design is "never let the instrument become the load":
 *   * a tick while the previous spawn is still alive is DROPPED, not queued;
 *   * the child runs with `stdio: 'ignore'`, so it holds no pipe the engine must
 *     service, and is `unref()`d so it cannot hold the process open;
 *   * the timer is `unref`'d, so it can never keep a shutting-down engine alive;
 *   * reading is a synchronous read of a small file that another process wrote.
 */
class ProcessSampler {
  #timer;
  #child;
  #snapshot;
  #snapshotAt = 0;
  #readAt = 0;
  #spawns = 0;
  #drops = 0;
  #failures = 0;
  #lastSpawnMs = null;
  #lastReadMs = null;
  #lastError = null;
  #lastExit = null;

  /**
   * @param {object} options
   * @param {string} options.file snapshot path
   * @param {number} options.intervalMs how often to refresh
   * @param {number} options.enginePid the pid the tree is walked from
   */
  constructor({ file, intervalMs, enginePid, shell }) {
    this.file = file;
    this.intervalMs = intervalMs;
    this.enginePid = enginePid;
    this.shell = shell;
    this.supported = process.platform === 'win32';
    this.script = SNAPSHOT_SCRIPT;
  }

  start() {
    if (this.#timer !== undefined || !this.supported) return;
    // The probe writes the snapshot; nothing else creates the directory. Without
    // this the PowerShell child fails on a fresh home and the surface reports
    // "no snapshot yet" forever — which is exactly the silent-no-instrument
    // failure this plugin exists to remove.
    try {
      mkdirSync(path.dirname(this.file), { recursive: true });
    } catch (error) {
      this.#failures += 1;
      this.#lastError = `cannot create ${path.dirname(this.file)}: ${error instanceof Error ? error.message : String(error)}`;
      return;
    }
    // First sample immediately: a health surface that reports "unknown" for the
    // first interval is a health surface nobody trusts.
    this.#spawnOnce();
    this.#timer = setInterval(() => this.#spawnOnce(), this.intervalMs);
    if (typeof this.#timer.unref === 'function') this.#timer.unref();
  }

  stop() {
    if (this.#timer !== undefined) {
      clearInterval(this.#timer);
      this.#timer = undefined;
    }
    // The child owns no file descriptor of ours and is unref'd; it finishes on
    // its own and writes its snapshot, which the next engine reads. Killing it
    // could leave a half-written temp file, and the temp file is renamed
    // atomically precisely so that cannot matter.
    this.#child = undefined;
  }

  #spawnOnce() {
    if (this.#child !== undefined) {
      this.#drops += 1;
      return;
    }
    // Pick up whatever the previous child wrote before starting the next one.
    // `exit` also reads; doing both means a missed event cannot leave the cache
    // stale, and a read of a 60 KB file costs microseconds.
    this.read();
    const startedAt = Date.now();
    this.#lastSpawnMs = null;
    let child;
    try {
      // `detached` is FALSE, deliberately, and this cost an hour to find:
      // measured on ZABZ-YOGA 2026-09-16 with pwsh 7, `detached: true` makes
      // pwsh.exe exit 0 after ~160 ms WITHOUT running the script — no output,
      // no file, no error, and Node reports a clean exit. The same argv with
      // `detached: false` runs normally (1173 ms, 58 KB written). A detached
      // PowerShell has no console to host itself in and quits.
      //
      // What `detached` was for — never letting the probe block or hold the
      // engine — is achieved by `stdio: 'ignore'` (no pipe for the engine to
      // service) plus `child.unref()` (no ref-count on the event loop). The
      // engine never reads this child's stdout and never waits on it.
      child = spawn(
        this.shell,
        ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', this.script,
          '-Out', this.file, '-EnginePid', String(this.enginePid)],
        { detached: false, stdio: 'ignore', windowsHide: true },
      );
    } catch (error) {
      this.#failures += 1;
      this.#lastError = `spawn failed: ${error instanceof Error ? error.message : String(error)}`;
      return;
    }
    this.#child = child;
    this.#spawns += 1;
    // A probe must never be the reason an engine cannot shut down.
    if (typeof child.unref === 'function') child.unref();
    child.once('error', (error) => {
      this.#failures += 1;
      this.#lastError = `probe error: ${error instanceof Error ? error.message : String(error)}`;
      if (this.#child === child) this.#child = undefined;
    });
    child.once('exit', (code) => {
      this.#lastExit = code;
      this.#lastSpawnMs = Date.now() - startedAt;
      if (code !== 0) {
        this.#failures += 1;
        this.#lastError = `probe exited ${code}`;
      }
      if (this.#child === child) this.#child = undefined;
      // Read inside the exit event so the first read after a refresh is fresh
      // without any polling.
      this.read();
    });
  }

  /**
   * Refresh the cached snapshot from disk. Cheap and synchronous: the file is
   * written by another process and is at most ~60 KB.
   *
   * @returns {boolean} whether a parseable snapshot is now cached
   */
  read() {
    const startedAt = Date.now();
    try {
      const text = readFileSync(this.file, 'utf8');
      const parsed = JSON.parse(text);
      if (parsed === null || typeof parsed !== 'object') throw new TypeError('snapshot is not an object');
      this.#snapshot = parsed;
      this.#snapshotAt = Date.now();
    } catch (error) {
      // A missing file is the normal first-run state, not an error worth
      // reporting as one; a malformed one is.
      const missing = error !== null && typeof error === 'object' && error.code === 'ENOENT';
      if (!missing) this.#lastError = `snapshot unreadable: ${error instanceof Error ? error.message : String(error)}`;
    }
    this.#lastReadMs = Date.now() - startedAt;
    return this.#snapshot !== undefined;
  }

  /** Cache age in ms, or null when nothing has ever been read. */
  get ageMs() {
    return this.#snapshot === undefined ? null : Date.now() - this.#snapshotAt;
  }

  get snapshot() {
    return this.#snapshot;
  }

  /** The probe's own cost and liveness — the instrument reporting on itself. */
  probe() {
    return {
      supported: this.supported,
      script: this.script,
      shell: this.shell,
      file: this.file,
      intervalMs: this.intervalMs,
      running: this.#timer !== undefined,
      inFlight: this.#child !== undefined,
      spawns: this.#spawns,
      ticksDroppedWhileInFlight: this.#drops,
      failures: this.#failures,
      lastExitCode: this.#lastExit,
      lastSpawnMs: this.#lastSpawnMs,
      lastReadMs: this.#lastReadMs,
      lastError: this.#lastError,
      ageMs: this.ageMs,
    };
  }
}

/**
 * Build the whole readout. Pure with respect to the sampler: it only reads
 * cached state, so it can be called on every route hit without spawning
 * anything.
 *
 * @param {object} deps
 * @param {ProcessSampler} deps.sampler
 * @param {LagSampler} deps.lag
 * @param {() => object} deps.agents
 * @param {number} deps.startedAtMs
 * @param {object} [deps.listAgents] listing-cache counters, if that half is mounted
 * @param {object} [deps.governor] the admission governor's read-only view
 */
export function buildReadout({ sampler, lag, agents, startedAtMs, staleMs, listAgents, governor }) {
  const age = sampler.ageMs;
  const stale = age === null || age > staleMs;
  const snapshot = sampler.snapshot;
  const classified = snapshot === undefined
    ? null
    : classifyProcesses(snapshot);
  const census = censusAgents(agents);

  // The lag summary is computed once and reused so the tool, the route and the
  // text surface cannot disagree.
  const lagSummary = lag.summary();

  return {
    at: new Date().toISOString(),
    identity: identityOf(process, startedAtMs),
    loop: {
      intervalMs: lag.intervalMs,
      window: lag.capacity,
      samples: lagSummary.count,
      p50Ms: lagSummary.p50,
      p95Ms: lagSummary.p95,
      maxMs: lagSummary.max,
      sampledAt: new Date().toISOString(),
      // The claim this number can and cannot support, stated where it is read.
      note: 'self-timing interval: a reading is how late the loop ran its own timer. A block shorter than the interval can hide between two wake-ups, which is why max matters more than the mean.',
    },
    memory: memoryOf(process),
    system: {
      hostname: os.hostname(),
      platform: process.platform,
      release: os.release(),
      cpuCount: os.cpus().length,
      loadAverage: os.loadavg(),
      physicalTotalBytes: os.totalmem(),
      physicalAvailableBytes: os.freemem(),
      probe: snapshot === undefined ? null : {
        totalPhysBytes: snapshot.system?.totalPhysBytes ?? null,
        availPhysBytes: snapshot.system?.availPhysBytes ?? null,
        commitLimitBytes: snapshot.system?.commitLimitBytes ?? null,
        commitAvailableBytes: snapshot.system?.commitAvailableBytes ?? null,
        memoryLoadPercent: snapshot.system?.memoryLoadPercent ?? null,
      },
    },
    processes: {
      snapshotAt: snapshot === undefined ? null : snapshot.at ?? null,
      ageMs: age,
      stale,
      available: classified !== null,
      source: snapshot === undefined ? null : 'snapshot.ps1 (child process, stdio ignored)',
      total: snapshot?.totals?.processes ?? null,
      threadsTotal: snapshot?.totals?.threads ?? null,
      handlesTotal: snapshot?.totals?.handles ?? null,
      nodeProcessesInvisibleToMemoryQuery: snapshot?.totals?.nodeInvisible ?? null,
      engine: classified?.engine ?? null,
      engineDescendants: classified === null ? null : classified.children,
      maxDescendantDepth: classified === null ? null : classified.maxDepth,
      toolCallRunnerProcesses: classified === null ? null : classified.runner.length,
      toolCallRunners: classified?.runner ?? [],
      toolCallRunnerBytes: classified === null ? null : privateBytesOf(classified.runner),
      mcpServerProcesses: classified === null ? null : classified.mcp.length,
      mcpServersByName: classified?.byServer ?? null,
      mcpProcesses: classified?.mcp ?? [],
      mcpBytes: classified === null ? null : privateBytesOf(classified.mcp),
    },
    sessions: {
      live: census.sessionsLive,
      root: census.sessionsRoot,
      subagents: census.subagentsLive,
      agentLoopsRunning: census.sessionsRunning,
      ...(census.unavailable === undefined ? {} : { unavailable: census.unavailable }),
      list: census.sessions,
    },
    probe: sampler.probe(),
    // The listing cache's own counters. This is how "did the deadline and the
    // cache actually remove the re-scan" is answered with a number instead of a
    // claim: `scans` counts full corpus reads, everything else was served
    // without one.
    listAgents: listAgents ?? null,
    // The admission governor's view of the same machine: how many heavy slots
    // are leased right now, out of a budget derived from measured headroom.
    // Computed by the caller (it needs `apply`-scoped configuration) and passed
    // in, so this function stays a pure projection of its inputs.
    governor: governor ?? null,
    constants: {
      route: ROUTE,
      readoutTool: READOUT_TOOL,
      staleAfterMs: staleMs,
    },
  };
}

/** A one-screen text rendering of the same readout. Never a table of everything. */
export function renderText(readout) {
  const lines = [];
  const age = readout.processes.ageMs;
  lines.push(`engine ${readout.identity.pid} up ${humanAge(readout.identity.uptimeMs)}  since ${readout.identity.startedAt}`);
  lines.push(`loop lag  p50=${fmtMs(readout.loop.p50Ms)}  p95=${fmtMs(readout.loop.p95Ms)}  max=${fmtMs(readout.loop.maxMs)}  (${readout.loop.samples} samples @ ${readout.loop.intervalMs} ms)`);
  lines.push(`memory    rss=${mib(readout.memory.rss)} MiB  heap=${mib(readout.memory.heapUsed)}/${mib(readout.memory.heapTotal)} MiB  external=${mib(readout.memory.external)} MiB`);
  lines.push(`system    phys avail ${mib(readout.system.physicalAvailableBytes)} / ${mib(readout.system.physicalTotalBytes)} MiB  cpus=${readout.system.cpuCount}  load1=${round(readout.system.loadAverage?.[0])}`);
  const probeSystem = readout.system.probe;
  if (probeSystem !== null) {
    lines.push(`          commit ${mib(probeSystem.commitAvailableBytes)} free of ${mib(probeSystem.commitLimitBytes)} MiB limit  memoryLoad=${probeSystem.memoryLoadPercent}%`);
  }
  if (!readout.processes.available) {
    lines.push(`processes NOT MEASURED — ${readout.probe.lastError ?? 'no snapshot yet'}; probe ${readout.probe.running ? 'running' : 'stopped'}, spawns=${readout.probe.spawns}, failures=${readout.probe.failures}`);
  } else {
    const staleNote = readout.processes.stale ? `  <-- STALE (${humanAge(age)})` : `  (${humanAge(age)} old)`;
    lines.push(`processes ${readout.processes.total} total, ${readout.processes.threadsTotal} threads; engine ${readout.processes.engine?.threads ?? '?'} threads, ${readout.processes.engine?.handles ?? '?'} handles${staleNote}`);
    lines.push(`          tool-call runners ${readout.processes.toolCallRunnerProcesses} (${mib(readout.processes.toolCallRunnerBytes)} MiB)   mcp ${readout.processes.mcpServerProcesses} (${mib(readout.processes.mcpBytes)} MiB) ${formatServers(readout.processes.mcpServersByName)}`);
  }
  lines.push(`sessions  ${readout.sessions.root} root, ${readout.sessions.subagents} subagent, ${readout.sessions.agentLoopsRunning} agent loop(s) executing${readout.sessions.unavailable ? `  [${readout.sessions.unavailable}]` : ''}`);
  if (readout.listAgents !== null && readout.listAgents !== undefined) {
    const listing = readout.listAgents;
    lines.push(`listing   list_agents cache ${listing.cacheMs} ms TTL, deadline ${listing.deadlineMs} ms: ${listing.scans} scan(s)`
      + `, ${listing.hits} cache hit(s), ${listing.coalesced} coalesced, ${listing.timeouts} deadline(s)`
      + ` (last scan ${listing.lastScanMs === null ? 'never' : `${listing.lastScanMs} ms`}; last ${listing.lastOutcome ?? 'never called'})`);
  }
  if (readout.governor !== null && readout.governor !== undefined && readout.governor.error === undefined) {
    const governor = readout.governor;
    lines.push(`governor  ${governor.inUse} of ${governor.budget} heavy slot(s) leased, ${governor.free} free, ${governor.waiters} waiting`
      + (governor.headroomLow ? '  <- headroom low, floored' : '')
      + (governor.deadLeases.length > 0 ? `  (${governor.deadLeases.length} dead lease(s) awaiting reap)` : ''));
  }
  lines.push(`reading taken ${readout.at} on ${readout.system.hostname} (pid ${readout.identity.pid}); process table from ${readout.processes.source ?? 'no source'} at ${readout.processes.snapshotAt ?? 'never'}`);
  return lines.join('\n');
}

const fmtMs = (value) => (value === null || value === undefined ? '?' : `${value}ms`);
const round = (value) => (Number.isFinite(value) ? Math.round(value * 100) / 100 : '?');

function formatServers(byServer) {
  if (byServer === null || byServer === undefined) return '';
  const parts = Object.entries(byServer).map(([server, count]) => `${server}=${count}`);
  return parts.length === 0 ? '' : `[${parts.join(' ')}]`;
}

/** The JSON route's body: the full readout, or the text rendering. */
function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader('content-type', 'application/json; charset=utf-8');
  res.setHeader('cache-control', 'no-store');
  res.end(JSON.stringify(payload));
}

/**
 * The tool's output schema is the small, stable projection a model can act on.
 * It is deliberately NOT the whole readout: a model does not need 400 process
 * rows, and a tool result that large would poison the context it is meant to
 * inform.
 *
 * RAW JSON Schema. `tools.register` validates this with
 * `assertSupportedJsonSchema`, which requires `required` to be an ARRAY of
 * property names — the author DSL's inline `required: true` throws there.
 */
const READOUT_TOOL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    pid: { type: 'integer' },
    startedAt: { type: 'string' },
    uptimeMs: { type: 'integer' },
    hostname: { type: 'string' },
    loopP50Ms: { type: 'integer' },
    loopP95Ms: { type: 'integer' },
    loopMaxMs: { type: 'integer' },
    loopSamples: { type: 'integer' },
    rssBytes: { type: 'integer' },
    heapUsedBytes: { type: 'integer' },
    physicalAvailableBytes: { type: 'integer' },
    physicalTotalBytes: { type: 'integer' },
    commitAvailableBytes: { type: 'integer' },
    commitLimitBytes: { type: 'integer' },
    processesTotal: { type: 'integer' },
    threadsTotal: { type: 'integer' },
    toolCallRunnerProcesses: { type: 'integer' },
    mcpServerProcesses: { type: 'integer' },
    sessionsRoot: { type: 'integer' },
    subagentsLive: { type: 'integer' },
    agentLoopsRunning: { type: 'integer' },
    processSnapshotAgeMs: { type: 'integer' },
    processSnapshotStale: { type: 'boolean' },
    notes: { type: 'array', items: { type: 'string' } },
  },
  required: [
    'pid', 'startedAt', 'uptimeMs', 'hostname',
    'loopP50Ms', 'loopP95Ms', 'loopMaxMs', 'loopSamples',
    'rssBytes', 'heapUsedBytes', 'physicalAvailableBytes', 'physicalTotalBytes',
    'sessionsRoot', 'subagentsLive', 'agentLoopsRunning',
    'processSnapshotStale',
  ],
};

/** Project the readout onto the tool's declared schema, with its caveats. */
export function toolPayload(readout) {
  const notes = [];
  if (!readout.processes.available) {
    notes.push(`the OS process table has NOT been sampled: ${readout.probe.lastError ?? 'no snapshot yet'}. Process counts are null, not zero.`);
  } else if (readout.processes.stale) {
    notes.push(`the process snapshot is stale by ${readout.processes.ageMs} ms; process counts are the last known values.`);
  }
  notes.push('loop lag is sampled by a self-timing interval; a block shorter than the interval can go unobserved, so max is the number to watch.');
  const payload = {
    pid: readout.identity.pid,
    startedAt: readout.identity.startedAt,
    uptimeMs: readout.identity.uptimeMs,
    hostname: readout.system.hostname,
    loopP50Ms: Math.round(readout.loop.p50Ms ?? 0),
    loopP95Ms: Math.round(readout.loop.p95Ms ?? 0),
    loopMaxMs: Math.round(readout.loop.maxMs ?? 0),
    loopSamples: readout.loop.samples,
    rssBytes: readout.memory.rss,
    heapUsedBytes: readout.memory.heapUsed,
    physicalAvailableBytes: readout.system.physicalAvailableBytes,
    physicalTotalBytes: readout.system.physicalTotalBytes,
    sessionsRoot: readout.sessions.root,
    subagentsLive: readout.sessions.subagents,
    agentLoopsRunning: readout.sessions.agentLoopsRunning,
    processSnapshotStale: readout.processes.stale,
    notes,
  };
  if (readout.system.probe?.commitAvailableBytes != null) payload.commitAvailableBytes = readout.system.probe.commitAvailableBytes;
  if (readout.system.probe?.commitLimitBytes != null) payload.commitLimitBytes = readout.system.probe.commitLimitBytes;
  if (readout.processes.total !== null) payload.processesTotal = readout.processes.total;
  if (readout.processes.threadsTotal !== null) payload.threadsTotal = readout.processes.threadsTotal;
  if (readout.processes.toolCallRunnerProcesses !== null) payload.toolCallRunnerProcesses = readout.processes.toolCallRunnerProcesses;
  if (readout.processes.mcpServerProcesses !== null) payload.mcpServerProcesses = readout.processes.mcpServerProcesses;
  if (readout.processes.ageMs !== null) payload.processSnapshotAgeMs = readout.processes.ageMs;
  return payload;
}

/**
 * Run `body` once `deps` are available, WITHOUT making them hard dependencies.
 *
 * WHY THIS IS `ctx.inject` AND NOT `ctx.get`
 * This is the defect that cost the most time building this plugin, so it is
 * written down where the next reader will hit it:
 *
 *   A loader entry's ACTIVATION ORDER is not its order in the composed tree. A
 *   plugin row placed last in `--dump-config` output can still be applied before
 *   the row that provides the service it wants. A bare `ctx.get('webServer')`
 *   inside `apply` therefore returns `undefined`, the `if` guard skips the
 *   contribution, and the plugin looks mounted while contributing NOTHING —
 *   with no error anywhere, because skipping was the designed behaviour.
 *
 * Declaring `inject: ['webServer']` on the plugin object fixes the ordering but
 * makes the service a HARD dependency: in a headless profile that never mounts a
 * webserver, the fiber stays pending and `assertEntriesActivated` fails the whole
 * boot. A health plugin must never be able to stop an engine from starting.
 *
 * `ctx.inject(deps, body)` is the middle path and the idiom the shipped plugins
 * use (`dsh-pwsh-local` for `settings`): it starts a CHILD fiber that waits for
 * the services, runs `body` when they appear, and whose effects are disposed with
 * the parent. A child fiber that never activates is not a loader entry, so it can
 * never fail the boot.
 */
function withServices(ctx, deps, body) {
  if (typeof ctx.inject === 'function') {
    ctx.inject(deps, (scoped) => body(scoped));
    return;
  }
  // A context without `inject` (a test double, or a much older Cordis): take the
  // service now if it is there and contribute nothing if it is not.
  if (deps.every((name) => ctx.get(name) !== undefined)) body(ctx);
}

/**
 * Cordis plugin entry.
 *
 * `inject` is deliberately EMPTY. Every service is reached through
 * {@link withServices} or read with `ctx.get()` behind an absence check, so this
 * row mounts and contributes whatever the composition actually has — a headless
 * profile with no webserver and no tool registry still gets a sampler and a log
 * line, and does not enter permanent waiting on a service that will never appear.
 */
function apply(ctx, config = {}) {
  const intervalMs = Number.isFinite(config.probeIntervalMs) && config.probeIntervalMs >= 1000 ? config.probeIntervalMs : 5000;
  const lagIntervalMs = Number.isFinite(config.lagIntervalMs) && config.lagIntervalMs >= 50 ? config.lagIntervalMs : 250;
  const lagCapacity = Number.isInteger(config.lagWindow) && config.lagWindow > 0 ? config.lagWindow : 512;
  const staleMs = Number.isFinite(config.staleAfterMs) && config.staleAfterMs > 0 ? config.staleAfterMs : 30000;
  const startedAtMs = Date.now() - Math.round(process.uptime() * 1000);
  const dshHome = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
  const statsFile = config.listAgentsStatsFile || defaultStatsFile(dshHome);

  // Registration failures are recorded, not just logged. A `logger.warn` in a
  // context without a logger is a silent failure, and a tool that failed to
  // register while the plugin reports itself mounted is precisely the class of
  // bug this surface exists to expose.
  const registration = { listAgents: null, readout: null, governor: null };

  // ── the tool plane: `list_agents` with a deadline and a shared cache ─────
  //
  // WHY THIS IS REGISTERED HERE (GLOBAL) AND NOT FROM THE PRESET
  // The shipped tool is registered by a row inside the agent preset's delegation
  // group, i.e. in a SCOPED layer. A scoped tool shadows a global one, so the
  // only ways to replace it are (a) register from the same scope — which means a
  // preset row that names THIS package, so a machine where the package is not
  // installed fails to mount its preset and cannot create sessions at all — or
  // (b) register globally and remove the preset row, which is what is done here.
  //
  // (b) is the safer shape on every axis: one registration for the whole process
  // instead of one per preset; the counters live in the same instance that serves
  // `/healthz`, so there is no cross-instance mirror to reconcile; and the failure
  // mode of a missing package becomes "the engine does not boot" (loud, immediate,
  // reported by the sync) instead of "sessions silently fail to mount".
  //
  // The tool keeps the shipped name, arguments, output schema and rendering, so
  // the model's catalog does not shift; only the two behaviours under load change.
  withServices(ctx, ['tools'], (toolCtx) => {
    try {
      toolCtx.effect(() => registerListAgents(toolCtx, {
        cacheMs: config.listAgentsCacheMs,
        deadlineMs: config.listAgentsTimeoutMs,
        maxDeadlineMs: config.listAgentsMaxTimeoutMs,
        toolName: config.listAgentsToolName,
        statsFile,
      }));
    } catch (error) {
      registration.listAgents = error instanceof Error ? error.message : String(error);
      ctx.logger?.warn?.(`engine-health: could not register list_agents: ${registration.listAgents}`);
    }
  });

  // ── the admission governor: the shell CLI's own protocol, from the model ──
  const governorDir = config.governorRoot || governorRoot(dshHome);
  withServices(ctx, ['tools'], (toolCtx) => {
    try {
      toolCtx.effect(() => registerAdmissionGovernor(toolCtx, {
        root: governorDir,
        toolName: config.governorToolName,
        budget: {
          perSlotBytes: config.slotBytes,
          maxSlots: config.maxSlots,
          minSlots: config.minSlots,
        },
      }));
    } catch (error) {
      registration.governor = error instanceof Error ? error.message : String(error);
      ctx.logger?.warn?.(`engine-health: could not register admission_governor: ${registration.governor}`);
    }
  });

  const lag = new LagSampler({ intervalMs: lagIntervalMs, capacity: lagCapacity });
  lag.start();
  ctx.effect(() => () => lag.stop());

  const shell = resolveShell();
  const sampler = new ProcessSampler({
    file: config.snapshotFile || defaultSnapshotPath(),
    intervalMs,
    enginePid: process.pid,
    shell,
  });
  sampler.start();
  ctx.effect(() => () => sampler.stop());
  // Read once immediately so the surface is honest from the first request: if a
  // snapshot from a previous engine exists it is read, and its age is reported,
  // which is exactly the provenance a reader needs.
  sampler.read();

  const governorView = () => {
    try {
      const view = governorStatus({
        root: governorDir,
        reapFirst: false,
        perSlotBytes: config.slotBytes,
        maxSlots: config.maxSlots,
        minSlots: config.minSlots,
      });
      const tools = ctx.get('tools');
      const registered = tools !== undefined && typeof tools.get === 'function'
        ? tools.get(config.governorToolName || 'admission_governor') !== undefined
        : false;
      return {
        root: view.root,
        budget: view.budget,
        inUse: view.inUse,
        free: view.free,
        waiters: view.waiters,
        holders: view.holders,
        deadLeases: view.deadLeases,
        derivation: view.derivation,
        headroomLow: view.headroomLow,
        freeMiB: view.freeMiB,
        reserveMiB: view.reserveMiB,
        toolRegistered: registered,
        ...(registration.governor === undefined ? {} : { registrationError: registration.governor }),
      };
    } catch (error) {
      return { root: governorDir, error: error instanceof Error ? error.message : String(error) };
    }
  };

  const readoutNow = () => buildReadout({
    sampler,
    lag,
    agents: ctx.get('agents'),
    startedAtMs,
    staleMs,
    governor: governorView(),
    // Same module instance in this process and the preset-mounted one usually
    // share `listingStats`; when they do not, the mirror file has it. Reading
    // the file only when this instance has never seen a call keeps the route
    // cheap.
    listAgents: {
      // Reading the registry back is the single cheapest proof that the
      // replacement is the definition an agent would actually execute — this is
      // the same lookup `dsh-tool-call-timeout-policy` performs to find
      // `timeoutMs`, and the shipped tool has none.
      ...(function registryView() {
        const tools = ctx.get('tools');
        if (tools === undefined || typeof tools.get !== 'function') {
          return { registry: 'no tools service in this context' };
        }
        try {
          const definition = tools.get(config.listAgentsToolName || 'list_agents');
          if (definition === undefined) {
            return {
              registry: 'not registered',
              ...(registration.listAgents === null ? {} : { registrationError: registration.listAgents }),
            };
          }
          return {
            registry: 'registered',
            registeredName: definition.name,
            registeredTimeoutMs: definition.timeoutMs ?? null,
            registeredByHealthPlugin: typeof definition.description === 'string' && definition.description.includes('short-lived shared cache'),
          };
        } catch (error) {
          return { registry: `lookup failed: ${error instanceof Error ? error.message : String(error)}` };
        }
      })(),
      readoutToolRegistrationError: registration.readout,
      ...(listingStats.scans + listingStats.hits + listingStats.coalesced + listingStats.timeouts > 0
        ? { ...listingStats, source: 'this process' }
        : { ...(readListingStats(statsFile) ?? listingStats), source: readListingStats(statsFile) === undefined ? 'this process (no listing call yet)' : 'mirror file' }),
    },
  });

  // ── surface 1: the HTTP route ────────────────────────────────────────────
  withServices(ctx, ['webServer'], (webCtx) => {
    const webServer = webCtx.get('webServer');
    if (webServer === undefined || typeof webServer.register !== 'function') return;
    webCtx.effect(() => webServer.register({
      kind: 'exact',
      path: ROUTE,
      handler: (req, res) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.statusCode = 405;
          res.setHeader('allow', 'GET, HEAD');
          res.end();
          return;
        }
        // Authenticate exactly as every other host route does when the
        // composition provides the connection service. Without it, the route is
        // still loopback-only, so the fallback is a refusal to serve anything
        // other than a loopback peer — never a silent open door.
        const connection = ctx.get('connection');
        if (connection !== undefined && typeof connection.requestRejection === 'function') {
          const rejection = connection.requestRejection(req);
          if (rejection !== undefined) {
            res.statusCode = rejection;
            res.end();
            return;
          }
        } else {
          const remote = req.socket?.remoteAddress ?? '';
          if (remote !== '' && remote !== '127.0.0.1' && remote !== '::1' && remote !== '::ffff:127.0.0.1') {
            res.statusCode = 403;
            res.end('engine-health: loopback only (no connection service to authenticate against)\n');
            return;
          }
        }
        let url;
        try {
          url = new URL(req.url ?? ROUTE, 'http://localhost');
        } catch {
          res.statusCode = 400;
          res.end();
          return;
        }
        const readout = readoutNow();
        // A stale or absent probe is NOT healthy, and saying so with a status
        // code is the whole point of a health endpoint.
        const status = readout.processes.available && !readout.processes.stale ? 200 : 503;
        if (url.searchParams.get('format') === 'text') {
          res.statusCode = status;
          res.setHeader('content-type', 'text/plain; charset=utf-8');
          res.setHeader('cache-control', 'no-store');
          res.end(req.method === 'HEAD' ? undefined : `${renderText(readout)}\n`);
          return;
        }
        sendJson(res, status, req.method === 'HEAD' ? undefined : readout);
      },
    }));
  });

  // ── surface 2: the model-facing tool ────────────────────────────────────
  withServices(ctx, ['tools'], (toolCtx) => {
    const tools = toolCtx.get('tools');
    if (tools === undefined || typeof tools.register !== 'function') return;
    try {
      toolCtx.effect(() => tools.register({
        name: config.toolName || READOUT_TOOL,
        description: 'Read this engine\'s live health: event-loop lag (p50/p95/max over a self-timing window), '
          + 'process memory, physical and commit-charge availability, total process and thread counts, the number of '
          + 'live shell tool-call runner processes, the number of live MCP server processes, and how many agent loops '
          + 'are executing right now. Read-only and cheap: the numbers come from counters the engine already keeps plus '
          + 'a process snapshot refreshed every few seconds by a detached child. Use it before fanning out a large fleet '
          + 'or when a call feels slow. When `processSnapshotStale` is true the process counts are the last known values, '
          + 'not current ones; `notes` says what is unmeasured.',
        parameters: {
          type: 'object',
          additionalProperties: false,
          properties: {
            format: {
              type: 'string',
              enum: ['json', 'text'],
              description: 'json (default) returns the structured numbers; text returns the same reading as a few lines for a human.',
            },
          },
        },
        output: {
          schema: {
            type: 'object',
            additionalProperties: false,
            properties: {
              json: { type: 'string' },
              text: { type: 'string' },
            },
          },
          render(args, value) {
            const requested = args !== null && typeof args === 'object' && args.format === 'text' ? 'text' : 'json';
            const body = requested === 'text' ? value.text : value.json;
            // NEVER an empty string: a blank card is unreadable. An unavailable
            // reading is rendered as the refusal it is.
            return [{ type: 'text', text: typeof body === 'string' && body.length > 0 ? body : 'engine_health: the reading could not be rendered' }];
          },
        },
        execute(args) {
          const readout = readoutNow();
          const payload = toolPayload(readout);
          return {
            json: JSON.stringify(payload, null, 2),
            text: renderText(readout),
          };
        },
      }));
    } catch (error) {
      // A name collision with another row must not take the whole plugin down —
      // the route and the sampler are still worth having.
      registration.readout = error instanceof Error ? error.message : String(error);
      ctx.logger?.warn?.(`engine-health: could not register the ${config.toolName || READOUT_TOOL} tool: ${registration.readout}`);
    }
  });

  ctx.logger?.info?.(`engine-health: /healthz on this engine (pid ${process.pid}); process probe via ${shell} every ${intervalMs} ms, snapshot ${config.snapshotFile || defaultSnapshotPath()}`);
}

export {
  name,
  apply,
  ROUTE,
  READOUT_TOOL,
  ProcessSampler,
  defaultSnapshotPath,
};
