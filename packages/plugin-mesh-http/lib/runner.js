/**
 * One agent turn, on this node, run by the engine's own process — and how many of them at once.
 *
 * WHY A CHILD PROCESS AND NOT AN IN-PROCESS TURN
 * The engine's `/api` surface can prompt a session in-process (`66` §2a), but that path needs a
 * live session, a preset mount and a cookie per authority (`66` §2c) — and it would put a
 * multi-minute agent turn inside the event loop that serves every other window on this machine.
 * Transport v2 exists to be the boring half of the mesh, so it runs the SAME thing transport v1
 * runs — `node <dsh>/lib/bin.js --profile <p> headless "<task>"` — as a child of the engine
 * instead of a child of the sshd session. That is precisely what removes the sshd-reparse-point
 * failure mode (`70-remote-fanout-proof.md` §4.4): the child inherits the engine's own logon
 * session, which already trusts the junctions the profile resolves through, because the
 * `--profile web` engine that is serving this request boots through them itself.
 *
 * WHAT IS BOUNDED, AND WHY EACH BOUND EXISTS
 *   * wall clock    — a hard timer; the child is killed, and the answer says `timedOut: true`
 *                     rather than hanging until the caller gives up.
 *   * concurrency   — `maxConcurrent`, derived from THIS NODE's own capacity by `lib/concurrency.js`
 *                     and published with its arithmetic. Not a constant somebody liked: see the
 *                     next paragraph.
 *   * output bytes  — stdout and stderr are capped; a runaway child cannot grow the engine's
 *                     heap through this route.
 *   * prompt size   — bounded by the platform's own command-line ceiling, because the task is a
 *                     single argv entry (the same transport v1 uses).
 *   * queue wait    — `maxQueueWaitMs`, the only bound that can end in a refusal, and it is a bound
 *                     on the CALLER'S patience rather than on the node's capacity.
 *
 * WHY THE CEILING IS NOT ONE ANY MORE — THE MEASUREMENT THAT CHANGED THIS FILE
 * v0.1.0 accepted exactly ONE run per node and answered `429 node-busy` to the rest. That is safe,
 * and it is a hard ceiling of one agent per node, which cannot serve the fleet this mesh exists
 * for (the owner's workflow is 10+ windows each running several agents — ~11 children per node
 * across five nodes, and a 55-agent mesh in total). The measurement behind this file is
 * `docs/mesh/93-transport-concurrency.md`: on `zabz-tech` (24 physical / 32 logical cores, 64 GiB),
 * twelve concurrent v2 children ran and the node's commit rose by the ~400 MiB/turn `84` §3
 * predicts, with the pagefile flat, the disk queue at 0-1 and the engine's loop lag unchanged.
 * So the ceiling became a number with arithmetic instead of the literal 1.
 *
 * IT REFUSES NOTHING FOR CAPACITY
 * A request beyond `maxConcurrent` is not refused. It joins a FIFO, is given a POSITION, and is
 * served in arrival order; its position and its wait are in its own answer
 * (`{"queue": {"position": 2, "waitedMs": 11844, "limit": 12}}`). That is the difference between
 * back-pressure and a refusal: a refused dispatch has to be re-aimed by the caller, and the caller
 * that re-aims is how work ends up on the wrong node (`70` §4.5).
 *
 * The one remaining `429` is `node-queue-wait-exceeded`, and it is not a capacity refusal: the
 * queue did not drain within `maxQueueWaitMs`, which by default (780 s) is SHORTER than a
 * dispatcher's own POST budget for a default 900 s run, so the node always answers before the
 * caller gives up. The bound that matters: a run is NOT cancelled when the client disconnects —
 * the child keeps running and the answer is lost. A caller's timeout must therefore be inside its
 * own budget, which is what the default is chosen for.
 *
 * WHAT IT NEVER DOES
 * The child is spawned with `shell: false`, so nothing in a prompt can be interpreted as a command
 * by a shell; the prompt is one argv entry and the command is a fixed array. Every refusal is a
 * value the caller can branch on, and `run()` never leaves a slot taken — a `finally` releases it.
 */

import { spawn } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';

/** The prompt's mandated first line (`71` §2.4), unanchored by design (`70` §4.6). */
export const DEFAULT_MESH_HOST_LINE = 'MESH-HOST:';

/**
 * The instruction the route prepends to every task, exactly as transport v1's provider does
 * (`packages/plugin-remote-fanout/lib/provider.js` — the two constants must stay in step, and
 * this one names the SAME marker so one verifier reads both transports).
 */
export function taskDisposition({ host }) {
  return [
    `You are running on the node "${host}".`,
    `Begin your final report with exactly this line: ${DEFAULT_MESH_HOST_LINE} ${host}`,
    'Then do the task. Be concise.',
    '',
  ].join('\n');
}

/**
 * The prompt a child receives: preamble, then the caller's task. The preamble is built from the
 * hostname THIS node measured, so a caller cannot make the child claim to be elsewhere.
 */
export function composeTask({ prompt, host, meshHostLine = DEFAULT_MESH_HOST_LINE }) {
  const preamble = meshHostLine === DEFAULT_MESH_HOST_LINE
    ? taskDisposition({ host })
    : [
      `You are running on the node "${host}".`,
      `Begin your final report with exactly this line: ${meshHostLine} ${host}`,
      'Then do the task. Be concise.',
      '',
    ].join('\n');
  return `${preamble}${prompt}`;
}

/** The command line for one turn. Pure, so the tests can pin it. */
export function childArgv({ nodeExe, dshBin, profile, task, subcommand = 'headless' }) {
  return [nodeExe, dshBin, '--profile', profile, subcommand, task];
}

/** One queue entry, so a position is a value and not a promise's internal ordering. */
function defer() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

/**
 * Execute turns. Owns: the concurrency limit, the FIFO of waiters and their positions, the
 * per-run timer, both output ceilings, and cleanup.
 *
 * @param {object} options
 * @param {string} options.task                 not here; per call
 * @param {number} [options.maxConcurrent]      how many children may generate at once. The route
 *   passes the node's own derived limit (`lib/concurrency.js`); the constructor's own default of
 *   `1` exists so a bare `new OneShotRunner(...)` in a test is the conservative case, not the
 *   production one.
 * @param {number} [options.maxQueueWaitMs]     how long a queued request waits before
 *   `node-queue-wait-exceeded`. Default 780 s = 13 min, deliberately shorter than the dispatcher's
 *   default 900 s POST budget so the node answers first.
 * @param {boolean} [options.refuseWhenFull]    the v0.1.0 behaviour (429 instead of queueing).
 *   Off by default and kept only so a caller that genuinely wants a fast refusal can have one.
 * @param {number} options.timeoutMs
 * @param {number} options.maxOutputBytes       per stream
 * @param {string} options.artifactDir          where the prompt and the streams are kept (outside the repo)
 * @param {(line: string) => void} options.log  one line of provenance for the engine's log
 * @param {number} [options.hardCeiling]        never more than this, whatever the arithmetic says
 */
export class OneShotRunner {
  constructor(options) {
    this.options = options;
    const asked = Number(options.maxConcurrent);
    const hard = Number(options.hardCeiling) > 0 ? Number(options.hardCeiling) : 64;
    this.hardCeiling = hard;
    this.maxConcurrent = Number.isFinite(asked) && asked >= 1 ? Math.min(Math.floor(asked), hard) : 1;
    const wait = Number(options.maxQueueWaitMs);
    this.maxQueueWaitMs = Number.isFinite(wait) && wait > 0 ? Math.floor(wait) : 780000;
    this.refuseWhenFull = options.refuseWhenFull === true;
    /**
     * Occupancy, as a COUNTER and not as the size of a map. The admission decision and the
     * reservation it makes have to be one synchronous step: if a caller could `await` between
     * "there is a free slot" and "I have taken it", N simultaneous dispatches would all read the
     * same free slot and the node would run N children with a limit of 1. `run()` therefore
     * decides and reserves with no `await` in between, and `release()` hands the slot over inside
     * the same step that frees it, so the queue can never over-admit.
     */
    this.active = 0;
    /** In-flight runs, keyed by requestId. Diagnostics and `/mesh/health`; not the accounting. */
    this.inFlight = new Map();
    /** Waiters, arrival order. `position` is 1-based and renumbered as the queue drains. */
    this.queue = [];
    /** Counters, so the route can report what it has actually done. */
    this.stats = {
      started: 0, completed: 0, failed: 0, refusedBusy: 0, refusedQueueWait: 0, timedOut: 0,
      queued: 0, queuePeak: 0, maxInFlightSeen: 0, maxQueueWaitMsSeen: 0,
      lastStartAt: null, lastEndAt: null,
    };
  }

  /** Whether a caller would be put in the queue right now, without starting anything. */
  busy() {
    return this.active >= this.maxConcurrent;
  }

  /**
   * Move the ceiling, never above `hardCeiling`. Called when the node's capacity contract is
   * re-read: the ceiling follows the machine's own numbers, so a node that loses memory narrows
   * itself. Lowering it never interrupts a run in flight — the next admission is what waits.
   */
  setLimit(value) {
    const asked = Number(value);
    const previous = this.maxConcurrent;
    this.maxConcurrent = Number.isFinite(asked) && asked >= 1
      ? Math.min(Math.floor(asked), this.hardCeiling)
      : 1;
    return { previous, limit: this.maxConcurrent };
  }

  /** What the route reports in `/mesh/health` — never a secret, never a prompt. */
  view() {
    return {
      limit: this.maxConcurrent,
      hardCeiling: this.hardCeiling,
      busy: this.busy(),
      inFlightCount: this.inFlight.size,
      inFlight: [...this.inFlight.values()].map((slot) => ({
        requestId: slot.requestId,
        startedAt: slot.startedAt,
        ageMs: Date.now() - slot.startedAtMs,
        timeoutMs: slot.timeoutMs,
      })),
      queueDepth: this.queue.length,
      queue: this.queue.map((entry) => ({
        requestId: entry.requestId,
        position: entry.position,
        waitedMs: Date.now() - entry.enqueuedAtMs,
      })),
      queueWaitBudgetMs: this.maxQueueWaitMs,
      refuseWhenFull: this.refuseWhenFull,
      ...this.stats,
    };
  }

  /**
   * Decide, and RESERVE, in one synchronous step. Nothing may be awaited between the test and the
   * increment — see `this.active`'s note in the constructor.
   *
   * `null` means "no slot, and you have been put in the queue": the caller must await
   * `entry.promise`, and the slot will be handed over by `release()` with `reserved: true`, so the
   * caller must NOT reserve again.
   *
   * @returns {{admitted: true, position: number, waitedMs: number, reserved: boolean}
   *          |{admitted: false, position: number, waitedMs: number, reason: string}
   *          |null}
   */
  admitSync(requestId) {
    if (this.active < this.maxConcurrent) {
      this.active += 1;
      return { admitted: true, position: 0, waitedMs: 0, reserved: true };
    }
    const position = this.queue.length + 1;
    if (this.refuseWhenFull) {
      this.stats.refusedBusy += 1;
      return { admitted: false, position, waitedMs: 0, reason: 'node-busy' };
    }
    const entry = {
      requestId,
      position,
      // The place it held WHEN IT ARRIVED. `position` is renumbered as the queue drains so
      // `/mesh/health` shows live places, but a caller's answer must report the place it actually
      // waited at — reporting the renumbered one told the third arrival it had been first.
      enqueuedPosition: position,
      enqueuedAtMs: Date.now(),
      settled: false,
      ...defer(),
    };
    this.queue.push(entry);
    this.stats.queued += 1;
    this.stats.queuePeak = Math.max(this.stats.queuePeak, this.queue.length);
    this.options.log?.(`QUEUE ${requestId} position=${position} limit=${this.maxConcurrent}`
      + ` queueDepth=${this.queue.length} inFlight=${this.active}`);
    entry.expiry = setTimeout(() => {
      if (entry.settled) return;
      entry.settled = true;
      const at = this.queue.indexOf(entry);
      if (at !== -1) this.queue.splice(at, 1);
      this.renumber();
      this.stats.refusedQueueWait += 1;
      this.options.log?.(`QUEUE-EXPIRED ${requestId} position=${position}`
        + ` waitedMs=${Date.now() - entry.enqueuedAtMs}`);
      entry.resolve({
        admitted: false, position: entry.enqueuedPosition,
        waitedMs: Date.now() - entry.enqueuedAtMs,
        reason: 'node-queue-wait-exceeded',
      });
    }, this.maxQueueWaitMs);
    entry.expiry.unref?.();
    return null;
  }

  /** 1-based positions that mean what a caller thinks they mean while the queue drains. */
  renumber() {
    this.queue.forEach((entry, index) => { entry.position = index + 1; });
  }

  /**
   * Give the slot back and hand it to the head of the queue, in ARRIVAL ORDER, inside one step:
   * `active` is decremented and immediately incremented again for the waiter, so no caller can
   * observe a free slot that belongs to somebody already waiting.
   */
  release(requestId) {
    this.inFlight.delete(requestId);
    this.active = Math.max(0, this.active - 1);
    for (;;) {
      const next = this.queue.shift();
      if (next === undefined) return;
      if (next.settled) continue; // its wait expired; the slot is free, so the next one gets it
      clearTimeout(next.expiry);
      next.settled = true;
      this.active += 1;
      this.renumber();
      const waitedMs = Date.now() - next.enqueuedAtMs;
      this.stats.maxQueueWaitMsSeen = Math.max(this.stats.maxQueueWaitMsSeen, waitedMs);
      this.options.log?.(`DEQUEUE ${next.requestId} position=${next.position} waitedMs=${waitedMs}`
        + ` limit=${this.maxConcurrent}`);
      next.resolve({ admitted: true, position: next.enqueuedPosition, waitedMs, reserved: true });
      return;
    }
  }

  /**
   * Run one turn. Resolves with the result object; never throws for a caller-fixable problem
   * (those are refusals with a status), and never leaves a slot taken.
   */
  async run({ task, cwd, timeoutMs, requestId, host }) {
    const { log } = this.options;
    // ---- admission: synchronous, because a slot must be taken in the same step it is tested ----
    let admission = this.admitSync(requestId);
    if (admission === null) {
      // Queued. The only await in the whole admission path, and no slot is held while it waits.
      const entry = this.queue[this.queue.length - 1];
      admission = await entry.promise;
    }
    if (admission.admitted !== true) {
      const detail = admission.reason === 'node-busy'
        ? `${this.active} of ${this.maxConcurrent} runs are in flight and this node answers 429 instead of queueing (refuseWhenFull)`
        : `waited ${Math.round(admission.waitedMs / 1000)}s for a slot (limit ${this.maxConcurrent}); the queue did not drain within the ${Math.round(this.maxQueueWaitMs / 1000)}s queue budget`;
      return {
        ok: false,
        status: 429,
        reason: admission.reason,
        detail,
        busy: this.view().inFlight,
        queue: { position: admission.position, waitedMs: admission.waitedMs, limit: this.maxConcurrent },
      };
    }

    // ---- everything below holds the slot, and the slot is returned in the outer `finally` ----
    const startedAtMs = Date.now();
    const slot = { requestId, startedAt: new Date(startedAtMs).toISOString(), startedAtMs, timeoutMs };
    this.inFlight.set(requestId, slot);
    this.stats.started += 1;
    this.stats.lastStartAt = slot.startedAt;
    this.stats.maxInFlightSeen = Math.max(this.stats.maxInFlightSeen, this.active);

    const artifactDir = path.join(this.options.artifactDir, `${new Date().toISOString().replace(/[:.]/g, '-')}-${requestId}`);
    const taskPath = path.join(artifactDir, 'task.txt');
    const outPath = path.join(artifactDir, 'stdout.txt');
    const errPath = path.join(artifactDir, 'stderr.txt');

    let outcome;
    try {
      mkdirSync(artifactDir, { recursive: true });
      // The task is written BEFORE the child starts, so the record of what was asked survives a
      // crash of either process. It contains whatever the caller sent, so it lives outside the
      // repository and is the caller's own responsibility to redact (`71` §2.3's job record).
      writeFileSync(taskPath, task, { encoding: 'utf8', mode: 0o600 });

      const outFd = openSync(outPath, 'w');
      const errFd = openSync(errPath, 'w');
      const argv = childArgv({
        nodeExe: this.options.nodeExe,
        dshBin: this.options.dshBin,
        profile: this.options.profile,
        subcommand: this.options.subcommand,
        task,
      });
      const env = { ...process.env, MESH_HOST_LOCAL_HOSTNAME: host, MESH_HTTP_RUN_ID: requestId };
      // Hygiene, not security theatre: the child is an agent turn with a full toolbelt, and it has
      // no business holding the mesh's shared secret. (A caller who can already run an agent turn
      // on this node can read the file; that is stated in the document, not hidden here.)
      delete env.MESH_HTTP_SECRET;
      delete env.MESH_SECRET;

      log(`RUN ${requestId} node-exe=${this.options.nodeExe} profile=${this.options.profile} cwd=${cwd} timeoutMs=${timeoutMs}`
        + ` inFlight=${this.active}/${this.maxConcurrent} queued=${this.queue.length}`
        + ` queuePosition=${admission.position} queueWaitedMs=${admission.waitedMs} artifacts=${artifactDir}`);

      outcome = await new Promise((resolve) => {
        let timedOut = false;
        let settled = false;
        let child;
        let timer;
        try {
          child = spawn(this.options.nodeExe, argv.slice(1), {
            cwd,
            env,
            shell: false,
            windowsHide: true,
            stdio: ['ignore', 'pipe', 'pipe'],
          });
        } catch (error) {
          resolve({ spawnError: String(error?.message ?? error), exitCode: undefined, timedOut: false });
          return;
        }
        const outChunks = [];
        const errChunks = [];
        let outBytes = 0;
        let errBytes = 0;
        let outTruncated = false;
        let errTruncated = false;
        const collect = (chunks, chunk, which) => {
          const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          const total = which === 'out' ? outBytes : errBytes;
          if (total >= this.options.maxOutputBytes) {
            if (which === 'out') outTruncated = true; else errTruncated = true;
            return;
          }
          const room = this.options.maxOutputBytes - total;
          const kept = buffer.byteLength <= room ? buffer : buffer.subarray(0, room);
          chunks.push(kept);
          if (which === 'out') {
            outBytes += kept.byteLength;
            if (kept.byteLength < buffer.byteLength) outTruncated = true;
          } else {
            errBytes += kept.byteLength;
            if (kept.byteLength < buffer.byteLength) errTruncated = true;
          }
        };
        const finish = (extra) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          try { closeSync(outFd); } catch { /* already closed */ }
          try { closeSync(errFd); } catch { /* already closed */ }
          const readBack = (file) => {
            try { return existsSync(file) ? readFileSync(file, 'utf8') : ''; } catch { return ''; }
          };
          const captured = (chunks, file) => Buffer.concat(chunks).toString('utf8') || readBack(file);
          resolve({
            exitCode: extra.exitCode,
            timedOut: extra.timedOut ?? timedOut,
            spawnError: extra.spawnError,
            stdout: captured(outChunks, outPath),
            stderr: captured(errChunks, errPath),
            stdoutBytes: Math.max(outBytes, 0),
            stderrBytes: Math.max(errBytes, 0),
            stdoutTruncated: outTruncated,
            stderrTruncated: errTruncated,
          });
        };
        child.stdout?.on('data', (chunk) => collect(outChunks, chunk, 'out'));
        child.stderr?.on('data', (chunk) => collect(errChunks, chunk, 'err'));
        child.stdout?.on('error', () => { /* the cap already ended the read; the child still matters */ });
        child.stderr?.on('error', () => { /* same */ });
        child.on('error', (error) => finish({ spawnError: String(error?.message ?? error), exitCode: undefined }));
        child.on('close', (code) => finish({ exitCode: code === undefined ? undefined : code }));
        timer = setTimeout(() => {
          timedOut = true;
          this.stats.timedOut += 1;
          try { child.kill('SIGKILL'); } catch { /* already gone */ }
        }, timeoutMs);
        timer.unref?.();
      });
    } finally {
      // The slot is returned even if the promise above were to reject: a slot leaked by an
      // exception is a node that quietly stops accepting work, which is the worst outcome here.
      this.release(requestId);
    }

    const ms = Date.now() - startedAtMs;
    this.stats.lastEndAt = new Date().toISOString();
    if (outcome.spawnError !== undefined) this.stats.failed += 1;
    else if (outcome.timedOut || outcome.exitCode !== 0) this.stats.failed += 1;
    else this.stats.completed += 1;

    // The streams are written from memory so the file is exactly what was captured, and the
    // stderr half is kept because transport v1's most useful failure line was stderr's
    // (`powershell: command not found`, exit 127 — `70` §4.5).
    writeFileSync(outPath, outcome.stdout, 'utf8');
    writeFileSync(errPath, outcome.stderr, 'utf8');
    // Nothing is removed here: `task.txt`, `stdout.txt` and `stderr.txt` are the node's own
    // record of what it was asked and what it answered (`71` §2.3). `cleanupArtifacts()` is
    // what a keeper job calls when a node fills up, and it is age-based on purpose.
    log(`END ${requestId} exit=${outcome.exitCode ?? 'none'} timedOut=${outcome.timedOut} spawnError=${outcome.spawnError ?? 'none'} ms=${ms} stdoutBytes=${outcome.stdoutBytes} stderrBytes=${outcome.stderrBytes}${outcome.stdoutTruncated || outcome.stderrTruncated ? ' TRUNCATED' : ''}`);

    return {
      ok: true,
      ms,
      artifacts: artifactDir,
      // The position this run held, and how long it held it. A caller that was queued learns it
      // waited; a caller that was admitted immediately reads position 0, waitedMs 0.
      queue: { position: admission.position, waitedMs: admission.waitedMs, limit: this.maxConcurrent },
      ...outcome,
    };
  }

  /** Remove artifacts older than `days`, called by a keeper (`bin/mesh-http.mjs clean`). */
  cleanupArtifacts({ days }) {
    const root = this.options.artifactDir;
    if (!existsSync(root)) return { removed: 0, root };
    const cutoff = Date.now() - days * 24 * 3600 * 1000;
    let removed = 0;
    for (const entry of readdirSafe(root)) {
      const full = path.join(root, entry);
      try {
        if (statSync(full).mtimeMs < cutoff) {
          rmSync(full, { recursive: true, force: true });
          removed += 1;
        }
      } catch { /* a directory that vanished under us is not an error */ }
    }
    return { removed, root };
  }
}

function readdirSafe(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

/** The default artifact root: machine state, outside the repository, beside the mesh logs. */
export function defaultArtifactDir() {
  const home = process.env.DSH_HOME || path.join(homedir(), '.dsh');
  return path.join(home, 'mesh', 'http');
}

/** A workdir is usable when it exists and is a directory. Never created on a caller's behalf. */
export function usableWorkdir(candidate) {
  if (typeof candidate !== 'string' || candidate.trim() === '') return false;
  try {
    return statSync(candidate).isDirectory();
  } catch {
    return false;
  }
}

export { tmpdir };
