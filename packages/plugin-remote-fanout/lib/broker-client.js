/**
 * The broker client: ask the placement service where work should run, and give
 * the reservation back when it is done.
 *
 * WHY THIS IS AN SSH CALL AND NOT AN HTTP CALL
 * The broker is loopback-only on the authority (`127.0.0.1:3091`), deliberately:
 * a placement service that any device on an allow-all tailnet can drive is a
 * denial-of-service surface and an information leak about every machine on the
 * mesh. The caller already has ssh to the authority, which is the same
 * transport `bin/mesh-run.mjs` uses and the one every other caller uses today.
 * This module therefore does not open a socket: it runs one bounded `ssh` whose
 * remote command is a `curl`.
 *
 * WHY THE JSON GOES IN argv AND NOT ON STDIN
 * Measured 2026-09-17: Win32-OpenSSH's client does not exit when its STDOUT is a
 * pipe — the remote command runs, the output arrives, and the client hangs
 * (`lib/ssh-transport.js` carries the measurement). So both streams are
 * redirected to files and read after the client exits, exactly as the ssh
 * transport does. The body is single-quoted for the remote shell, and a body
 * containing a single quote is REFUSED rather than escaped: this body is built
 * by this package and never by a model, so a quote in it is a bug, and a
 * silently-escaped bug is worse than a loud one.
 *
 * WHY A FAILURE IS A TYPED ERROR AND NEVER A DEFAULT ANSWER
 * The one behaviour this module must not have is "the broker did not answer, so
 * use the node the config named". That is the defect the provider's placement
 * exists to remove: a silent default makes a mesh of one machine look like a
 * mesh of four. Every failure here is a `BrokerError` with a machine-readable
 * `code` (`broker-unreachable`, `broker-unparsable`) that the caller must turn
 * into a reported condition.
 */

import { spawn } from 'node:child_process';
import { closeSync, existsSync, openSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/** `POST /place` could not be delivered: the ssh client failed, timed out, or exited non-zero. */
export const BROKER_UNREACHABLE = 'broker-unreachable';
/** The broker answered, but what it said is not a placement this caller can act on. */
export const BROKER_UNPARSABLE = 'broker-unparsable';

/** A placement-service failure, carrying the code a caller branches on. */
export class BrokerError extends Error {
  /**
   * @param {string} code  `broker-unreachable` | `broker-unparsable`
   * @param {string} message human-readable, and the text a caller reports
   * @param {object} [detail] evidence: the argv, the exit code, the raw body
   */
  constructor(code, message, detail = {}) {
    super(message);
    this.name = 'BrokerError';
    this.code = code;
    this.detail = detail;
  }
}

/** Quote one value as a literal POSIX single-quoted word. */
function singleQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

/**
 * Run one ssh command with stdout/stderr captured through FILES (never pipes),
 * bounded by a timeout. Copied in shape from `bin/mesh-run.mjs`, which measured
 * the file-not-pipe rule against this exact ssh client.
 */
function sshRun(spawnImpl, sshExe, argv, timeoutMs) {
  const tag = `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const outPath = path.join(tmpdir(), `meshbroker-${tag}.out`);
  const errPath = path.join(tmpdir(), `meshbroker-${tag}.err`);
  const outFd = openSync(outPath, 'w');
  const errFd = openSync(errPath, 'w');
  const started = Date.now();
  return new Promise((resolve) => {
    let child;
    try {
      child = spawnImpl(sshExe, argv, { stdio: ['ignore', outFd, errFd], windowsHide: true });
    } catch (error) {
      closeSync(outFd);
      closeSync(errFd);
      rmSync(outPath, { force: true });
      rmSync(errPath, { force: true });
      resolve({ ok: false, spawnError: String(error?.message ?? error), ms: Date.now() - started, stdout: '', stderr: '', argv });
      return;
    }
    let timer;
    let timedOut = false;
    const finish = (extra) => {
      clearTimeout(timer);
      try { closeSync(outFd); } catch { /* already closed */ }
      try { closeSync(errFd); } catch { /* already closed */ }
      const stdout = existsSync(outPath) ? readFileSync(outPath, 'utf8') : '';
      const stderr = existsSync(errPath) ? readFileSync(errPath, 'utf8') : '';
      rmSync(outPath, { force: true });
      rmSync(errPath, { force: true });
      resolve({ ms: Date.now() - started, stdout, stderr, argv, ...extra });
    };
    child.on('error', (error) => finish({ ok: false, spawnError: String(error?.message ?? error) }));
    child.on('close', (code) => finish({
      ok: code === 0,
      exitCode: code === null ? undefined : code,
      timedOut,
    }));
    timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* already gone */ }
    }, timeoutMs);
    timer.unref?.();
  });
}

/** The shape a placement must have before any caller acts on it. */
function assertPlacement(json, context) {
  const body = typeof json === 'object' && json !== null ? json : {};
  const node = body.node;
  if (typeof node !== 'string' || node.trim() === '') {
    throw new BrokerError(BROKER_UNPARSABLE, 'the broker answered without naming a node', context);
  }
  if (typeof body.lease !== 'string' || body.lease === '') {
    throw new BrokerError(BROKER_UNPARSABLE, `the broker named node "${node}" without issuing a lease, so the reservation could never be released`, context);
  }
  const position = Number(body.position);
  if (!Number.isInteger(position) || position < 0) {
    throw new BrokerError(BROKER_UNPARSABLE, `the broker named node "${node}" with a position of "${body.position}", which is not a queue position`, context);
  }
  if (!Array.isArray(body.rationale) || body.rationale.length === 0) {
    throw new BrokerError(BROKER_UNPARSABLE, `the broker named node "${node}" without a rationale — that is a bug in the decision, not a warning`, context);
  }
  return {
    node,
    position,
    lease: body.lease,
    score: Number.isFinite(Number(body.score)) ? Number(body.score) : null,
    eligible: Number.isFinite(Number(body.eligible)) ? Number(body.eligible) : null,
    tier: typeof body.tier === 'string' ? body.tier : null,
    blockedBy: Array.isArray(body.blockedBy) ? body.blockedBy : [],
    queue: Array.isArray(body.queue) ? body.queue : [],
    rationale: body.rationale.map(String),
    at: typeof body.at === 'string' ? body.at : null,
    expiresAt: typeof body.expiresAt === 'string' ? body.expiresAt : null,
    leaseTtlSec: Number.isFinite(Number(body.leaseTtlSec)) ? Number(body.leaseTtlSec) : null,
  };
}

/**
 * One client for one broker.
 *
 * @param {object} [config]
 * @param {string} [config.sshExe]      ssh client (default `ssh`)
 * @param {string[]} [config.sshArgs]   extra argv before the target (default: BatchMode + ConnectTimeout=8)
 * @param {string} [config.sshTarget]   the authority's ssh destination (default `secratary-ts`)
 * @param {string} [config.url]         the broker's loopback base URL (default `http://localhost:3091`)
 * @param {number} [config.timeoutMs]   bound on one broker call (default 30000)
 * @param {object} [config.logger]      optional `{info,warn}`
 * @param {Function} [config.spawnImpl] injected for tests
 */
export function createBrokerClient(config = {}) {
  const sshExe = config.sshExe || 'ssh';
  const sshArgs = Array.isArray(config.sshArgs)
    ? config.sshArgs.map(String)
    : ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8'];
  const sshTarget = config.sshTarget ?? 'secratary-ts';
  const url = (config.url ?? 'http://localhost:3091').replace(/\/+$/, '');
  const timeoutMs = Number.isFinite(config.timeoutMs) && config.timeoutMs > 0 ? config.timeoutMs : 30_000;
  const logger = config.logger;
  const spawnImpl = typeof config.spawnImpl === 'function' ? config.spawnImpl : spawn;

  if (typeof sshTarget !== 'string' || sshTarget.trim() === '') {
    throw new Error('remote-fanout: the broker client needs `sshTarget` — the ssh destination of the machine the broker runs on');
  }

  /** One `POST`/`GET` to one broker route, over ssh. Throws `BrokerError` on anything unusable. */
  async function request(route, { body, method = 'POST', timeout = timeoutMs } = {}) {
    const where = `${sshTarget}:${url}${route}`;
    let curl = `curl -s -S -X${method} ${url}${route}`;
    if (body !== undefined) {
      const json = JSON.stringify(body);
      if (json.includes("'")) {
        throw new BrokerError(BROKER_UNPARSABLE, `refusing to send a broker body containing a single quote (it is passed through a shell): ${json.slice(0, 200)}`, { route });
      }
      curl += ` -H "content-type: application/json" -d ${singleQuote(json)}`;
    }
    const argv = [...sshArgs, sshTarget, curl];
    const result = await sshRun(spawnImpl, sshExe, argv, timeout);
    if (!result.ok) {
      const why = result.spawnError
        ?? (result.timedOut ? `no answer within ${timeout} ms` : `ssh exited ${result.exitCode ?? 'without a code'}`)
        + (result.stderr.trim() === '' ? '' : `: ${result.stderr.trim().slice(0, 300)}`);
      throw new BrokerError(BROKER_UNREACHABLE, `the placement broker could not be reached at ${where} — ${why}`, { route, argv, exitCode: result.exitCode, stderr: result.stderr.slice(0, 600), ms: result.ms });
    }
    let json;
    try {
      json = JSON.parse(result.stdout.trim());
    } catch (error) {
      throw new BrokerError(BROKER_UNPARSABLE, `the broker at ${where} answered something that is not JSON (${String(error?.message ?? error)}); body was ${result.stdout.trim().slice(0, 200)}`, { route, stdout: result.stdout.slice(0, 600) });
    }
    return { json, ms: result.ms, argv };
  }

  return {
    kind: 'broker',
    url,
    sshTarget,
    describe() {
      return `broker ${url} over ssh ${sshTarget}`;
    },

    /** `POST /place` — ask where one job should run. Never returns a default; throws when it cannot ask. */
    async place(task, { timeout } = {}) {
      const { json, ms } = await request('/place', { body: { task }, timeout });
      const placement = assertPlacement(json, { route: '/place', body: json });
      placement.ms = ms;
      return placement;
    },

    /** `POST /done` — release the reservation. A broker that will not answer is a fact, not a failure of the child. */
    async done(lease, ok = true, { timeout } = {}) {
      const { json } = await request('/done', { body: { lease, ok: ok !== false }, timeout });
      return json;
    },

    /** `GET /nodes[?fresh=1]` — the live mesh, every node with its age. */
    async nodes({ fresh = false, timeout } = {}) {
      const { json } = await request(`/nodes${fresh ? '?fresh=1' : ''}`, { method: 'GET', timeout });
      if (!Array.isArray(json?.nodes)) {
        throw new BrokerError(BROKER_UNPARSABLE, `the broker's /nodes answer carries no node list (keys: ${Object.keys(json ?? {}).join(', ')})`, { body: json });
      }
      return json;
    },

    /** `GET /healthz` — used by the proof scripts to show the broker was live, not assumed live. */
    async healthz({ timeout } = {}) {
      const { json } = await request('/healthz', { method: 'GET', timeout });
      return json;
    },

    log(line) {
      logger?.info?.(`remote-fanout: ${line}`);
    },
  };
}
