/**
 * One agent turn, on this node, run by the engine's own process.
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
 *   * concurrency   — one run per node by default. Measured: one actively generating turn costs
 *                     ~0.81 GB commit and ~1 core (`71` §2.2), and the admission governor exists
 *                     because nothing else caps how much runs at once. A route that accepted
 *                     unlimited concurrent runs would be an uncapped fleet, which is the exact
 *                     failure the governor was written to stop.
 *   * output bytes  — stdout and stderr are capped; a runaway child cannot grow the engine's
 *                     heap through this route.
 *   * prompt size   — bounded by the platform's own command-line ceiling, because the task is a
 *                     single argv entry (the same transport v1 uses).
 *
 * WHAT IT REFUSES, AND WHAT IT NEVER DOES
 * While a run is in flight this answers 429 with a position — a refusal, never a queue, never a
 * crash, and never a second run. Every refusal is a value the caller can branch on. The child is
 * spawned with `shell: false`, so nothing in a prompt can be interpreted as a command by a shell;
 * the prompt is one argv entry and the command is a fixed array.
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

/** The template that tells a caller how to aim a node at a specific expected hostname. */
const HOST_PLACEHOLDER = '{{host}}';

/**
 * Execute one turn. Owns: the concurrency slot, the timer, both output ceilings, and cleanup.
 *
 * @param {object} options
 * @param {string} options.task           the full prompt (preamble + user task)
 * @param {string} options.cwd            working directory for the child
 * @param {string} options.nodeExe
 * @param {string} options.dshBin
 * @param {string} options.profile
 * @param {number} options.timeoutMs
 * @param {number} options.maxOutputBytes per stream
 * @param {string} options.artifactDir    where the prompt and the streams are kept (outside the repo)
 * @param {() => string} options.log      one line of provenance for the engine's log
 * @param {boolean} [options.keepArtifacts]
 */
export class OneShotRunner {
  constructor(options) {
    this.options = options;
    /** The single concurrency slot. `null` when idle. */
    this.inFlight = null;
    /** Counters, so the route can report what it has actually done. */
    this.stats = { started: 0, completed: 0, failed: 0, refusedBusy: 0, timedOut: 0, lastStartAt: null, lastEndAt: null };
  }

  /** Whether a caller would be refused right now, without starting anything. */
  busy() {
    return this.inFlight !== null;
  }

  /** What the route reports in `/mesh/health` — never a secret, never a prompt. */
  view() {
    return {
      busy: this.busy(),
      inFlight: this.inFlight === null ? null : {
        requestId: this.inFlight.requestId,
        startedAt: this.inFlight.startedAt,
        ageMs: Date.now() - this.inFlight.startedAtMs,
        timeoutMs: this.inFlight.timeoutMs,
      },
      ...this.stats,
    };
  }

  /**
   * Run one turn. Resolves with the result object; never throws for a caller-fixable problem
   * (those are refusals with a status), and never leaves the slot taken.
   */
  async run({ task, cwd, timeoutMs, requestId, host }) {
    const { log } = this.options;
    if (this.busy()) {
      this.stats.refusedBusy += 1;
      return {
        ok: false,
        status: 429,
        reason: 'node-busy',
        detail: `one run at a time: a turn started ${Math.round((Date.now() - this.inFlight.startedAtMs) / 1000)}s ago is still running`,
        busy: this.view().inFlight,
      };
    }

    const artifactDir = path.join(this.options.artifactDir, `${new Date().toISOString().replace(/[:.]/g, '-')}-${requestId}`);
    mkdirSync(artifactDir, { recursive: true });
    const taskPath = path.join(artifactDir, 'task.txt');
    const outPath = path.join(artifactDir, 'stdout.txt');
    const errPath = path.join(artifactDir, 'stderr.txt');
    // The task is written BEFORE the child starts, so the record of what was asked survives a
    // crash of either process. It contains whatever the caller sent, so it lives outside the
    // repository and is the caller's own responsibility to redact (`71` §2.3's job record).
    writeFileSync(taskPath, task, { encoding: 'utf8', mode: 0o600 });

    const outFd = openSync(outPath, 'w');
    const errFd = openSync(errPath, 'w');
    const startedAtMs = Date.now();
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

    const slot = { requestId, startedAt: new Date(startedAtMs).toISOString(), startedAtMs, timeoutMs };
    this.inFlight = slot;
    this.stats.started += 1;
    this.stats.lastStartAt = slot.startedAt;
    log(`RUN ${requestId} node-exe=${this.options.nodeExe} profile=${this.options.profile} cwd=${cwd} timeoutMs=${timeoutMs} artifacts=${artifactDir}`);

    const outcome = await new Promise((resolve) => {
      let timedOut = false;
      let settled = false;
      let child;
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
      const timer = setTimeout(() => {
        timedOut = true;
        this.stats.timedOut += 1;
        try { child.kill('SIGKILL'); } catch { /* already gone */ }
      }, timeoutMs);
      timer.unref?.();
    });

    const ms = Date.now() - startedAtMs;
    this.inFlight = null;
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

    return { ok: true, ms, artifacts: artifactDir, ...outcome };
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
