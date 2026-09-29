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
 * `code` that the caller must turn into a reported condition.
 *
 * THE FOUR CODES, AND WHY ONE WORD WAS NOT ENOUGH (I3, docs/mesh/126-placement-hardening.md)
 * The old client reported every failure as `broker-unreachable`, so a 30 s ssh
 * timeout read exactly like the authority being switched off. The measured
 * ledger had 11 placements fail with that one blur. The codes now say what is
 * actually known, because the caller's next action differs:
 *   broker-unreachable - the authority could not be reached AT ALL (ssh refused,
 *                        DNS/route failure, or the ssh client would not launch).
 *                        The request did not land; retrying is free.
 *   broker-timeout     - the authority was reached but did not answer within the
 *                        bound. THE REQUEST MAY HAVE LANDED (a lease may have
 *                        been issued); the caller must NOT assume it did not.
 *   broker-unparsable  - the authority answered but the body was not JSON, or
 *                        was JSON that is not a placement.
 *   broker-error       - the authority answered an HTTP error (4xx/5xx).
 * Every message ends with whether the request was retried and how many attempts
 * were made, because a retry that is not stated is a retry nobody can audit.
 *
 * BOUNDED RETRY WITH ONE requestId (I2, I1). A transport failure, a timeout, an
 * unparsable body and a 5xx are retried a bounded number of times with a short
 * jittered backoff. A 4xx and a well-formed local refusal are never retried. One
 * `place()` call reuses ONE `requestId` across all its attempts, so a retry
 * after a lost answer cannot make the broker issue a second lease for work that
 * was already leased (the broker memoizes the requestId; see broker.js I1).
 */

import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { closeSync, existsSync, openSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/** The authority could not be reached at all: the ssh client failed, refused, or would not launch. */
export const BROKER_UNREACHABLE = 'broker-unreachable';
/** The authority was reached but did not answer in time. The request MAY have landed. */
export const BROKER_TIMEOUT = 'broker-timeout';
/** The broker answered, but what it said is not a placement this caller can act on. */
export const BROKER_UNPARSABLE = 'broker-unparsable';
/** The broker answered an HTTP error status (4xx or 5xx). */
export const BROKER_ERROR = 'broker-error';

/** Total attempts for a `place()` or `nodes()` call, including the first. */
export const DEFAULT_CALL_ATTEMPTS = 3;
/** First backoff step; each subsequent step doubles until `DEFAULT_RETRY_CAP_MS`. */
export const DEFAULT_RETRY_BASE_MS = 250;
/** Ceiling on one backoff step, so a bounded retry stays bounded. */
export const DEFAULT_RETRY_CAP_MS = 4_000;

/** A placement-service failure, carrying the code a caller branches on. */
export class BrokerError extends Error {
  /**
   * @param {string} code  `broker-unreachable` | `broker-timeout` | `broker-unparsable` | `broker-error`
   * @param {string} message human-readable, and the text a caller reports
   * @param {object} [detail] evidence: the argv, the exit code, the raw body, `retryable`, `attempts`
   */
  constructor(code, message, detail = {}) {
    super(message);
    this.name = 'BrokerError';
    this.code = code;
    this.detail = detail;
    this.retryable = detail.retryable === true;
    this.attempts = Number.isFinite(detail.attempts) ? detail.attempts : 1;
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

/**
 * Split the trailing HTTP status curl was asked to append (`-w "\n%{http_code}"`)
 * from the body. Tolerates a body with no status suffix, so an older fake or an
 * older curl still parses as before.
 */
function parseCurlOutput(stdout) {
  const text = String(stdout ?? '');
  const trimmed = text.replace(/\s+$/, '');
  if (trimmed === '') return { body: '', status: null };
  const newline = trimmed.lastIndexOf('\n');
  const last = (newline === -1 ? trimmed : trimmed.slice(newline + 1)).trim();
  if (/^\d{3}$/.test(last)) {
    return { body: newline === -1 ? '' : trimmed.slice(0, newline), status: Number(last) };
  }
  return { body: trimmed, status: null };
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
    requestId: typeof body.requestId === 'string' ? body.requestId : null,
    idempotentReplay: body.idempotentReplay === true,
  };
}

/** Append the honest accounting every failure message must carry: was it retried, and how often. */
function decorateAttempts(error, made, maxAttempts) {
  const account = made > 1
    ? `retried with a short jittered backoff: ${made} of ${maxAttempts} attempt(s) were made`
    : `not retried: 1 attempt was made (the maximum for this call is ${maxAttempts})`;
  error.attempts = made;
  error.retried = made > 1;
  error.detail = { ...error.detail, attempts: made, maxAttempts, retried: made > 1 };
  error.message = `${error.message} [${account}]`;
  return error;
}

/**
 * One client for one broker.
 *
 * @param {object} [config]
 * @param {string} [config.sshExe]      ssh client (default `ssh`)
 * @param {string[]} [config.sshArgs]   extra argv before the target (default: BatchMode + ConnectTimeout=8)
 * @param {string} [config.sshTarget]   the authority's ssh destination (default `secratary-ts`)
 * @param {string} [config.url]         the broker's loopback base URL (default `http://localhost:3091`)
 * @param {number} [config.timeoutMs]   bound on ONE broker attempt (default 30000)
 * @param {number} [config.attempts]    total attempts for place/nodes, including the first (default 3)
 * @param {number} [config.retryBaseMs] first backoff step (default 250)
 * @param {number} [config.retryCapMs]  ceiling on one backoff step (default 4000)
 * @param {object} [config.logger]      optional `{info,warn}`
 * @param {Function} [config.spawnImpl] injected for tests
 * @param {Function} [config.sleep]     injected for tests (default a real setTimeout)
 */
export function createBrokerClient(config = {}) {
  const sshExe = config.sshExe || 'ssh';
  const sshArgs = Array.isArray(config.sshArgs)
    ? config.sshArgs.map(String)
    : ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8'];
  const sshTarget = config.sshTarget ?? 'secratary-ts';
  const url = (config.url ?? 'http://localhost:3091').replace(/\/+$/, '');
  const timeoutMs = Number.isFinite(config.timeoutMs) && config.timeoutMs > 0 ? config.timeoutMs : 30_000;
  const callAttempts = Number.isFinite(config.attempts) && config.attempts > 0 ? Math.floor(config.attempts) : DEFAULT_CALL_ATTEMPTS;
  const retryBaseMs = Number.isFinite(config.retryBaseMs) && config.retryBaseMs >= 0 ? config.retryBaseMs : DEFAULT_RETRY_BASE_MS;
  const retryCapMs = Number.isFinite(config.retryCapMs) && config.retryCapMs >= 0 ? config.retryCapMs : DEFAULT_RETRY_CAP_MS;
  const logger = config.logger;
  const spawnImpl = typeof config.spawnImpl === 'function' ? config.spawnImpl : spawn;
  const sleep = typeof config.sleep === 'function'
    ? config.sleep
    : (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

  if (typeof sshTarget !== 'string' || sshTarget.trim() === '') {
    throw new Error('remote-fanout: the broker client needs `sshTarget` — the ssh destination of the machine the broker runs on');
  }

  /** The jittered backoff before attempt `made + 1`: half to full exponential, capped. */
  function backoffMs(made) {
    const raw = Math.min(retryCapMs, retryBaseMs * (2 ** (made - 1)));
    return Math.round(raw * (0.5 + Math.random() * 0.5));
  }

  /** ONE `POST`/`GET` to one broker route. Throws a `BrokerError` carrying whether it is retryable. */
  async function oneAttempt(route, { body, method = 'POST', timeout = timeoutMs } = {}) {
    const where = `${sshTarget}:${url}${route}`;
    let curl = `curl -s -S -X${method} ${url}${route}`;
    if (body !== undefined) {
      const json = JSON.stringify(body);
      if (json.includes("'")) {
        // A LOCAL bug, not a transport fact: retrying it can never succeed.
        throw new BrokerError(BROKER_UNPARSABLE, `refusing to send a broker body containing a single quote (it is passed through a shell): ${json.slice(0, 200)}`, { route, retryable: false });
      }
      curl += ` -H "content-type: application/json" -d ${singleQuote(json)}`;
    }
    // The status is appended so a 5xx can be told from a 200 with a bad body; a body with no
    // status suffix still parses (see parseCurlOutput), so an older server or fake is tolerated.
    curl += ' -w "\\n%{http_code}"';
    const argv = [...sshArgs, sshTarget, curl];
    const result = await sshRun(spawnImpl, sshExe, argv, timeout);
    if (!result.ok) {
      if (result.timedOut === true) {
        throw new BrokerError(
          BROKER_TIMEOUT,
          `the placement broker at ${where} was reached but did not answer within ${timeout} ms — the request MAY have landed (a lease may already have been issued)`,
          { route, argv, timeoutMs: timeout, timedOut: true, ms: result.ms, stderr: result.stderr.slice(0, 600), retryable: true },
        );
      }
      const why = result.spawnError
        ?? `ssh exited ${result.exitCode ?? 'without a code'}`
        + (result.stderr.trim() === '' ? '' : `: ${result.stderr.trim().slice(0, 300)}`);
      throw new BrokerError(BROKER_UNREACHABLE, `the placement broker could not be reached at ${where} — ${why}`, { route, argv, exitCode: result.exitCode, stderr: result.stderr.slice(0, 600), ms: result.ms, retryable: true });
    }
    const { body: text, status } = parseCurlOutput(result.stdout);
    if (status !== null && status >= 400) {
      const retryable = status >= 500;
      throw new BrokerError(
        BROKER_ERROR,
        `the broker at ${where} answered HTTP ${status}${retryable ? ' (a server error)' : ' (a client error)'}: ${text.trim().slice(0, 200)}`,
        { route, status, stdout: result.stdout.slice(0, 600), retryable },
      );
    }
    let json;
    try {
      json = JSON.parse(text.trim());
    } catch (error) {
      throw new BrokerError(BROKER_UNPARSABLE, `the broker at ${where} answered something that is not JSON (${String(error?.message ?? error)}); body was ${text.trim().slice(0, 200)}`, { route, stdout: result.stdout.slice(0, 600), retryable: true });
    }
    return { json, ms: result.ms, argv, status };
  }

  /**
   * A bounded, jittered retry of one route. `maxAttempts` is 1 for routes that must not be
   * retried (done/healthz) and `callAttempts` (3) for place/nodes.
   */
  async function request(route, { body, method = 'POST', timeout = timeoutMs, maxAttempts = 1 } = {}) {
    let last;
    for (let made = 1; made <= maxAttempts; made += 1) {
      try {
        const result = await oneAttempt(route, { body, method, timeout });
        return { ...result, attempts: made };
      } catch (caught) {
        const error = caught instanceof BrokerError
          ? caught
          : new BrokerError(BROKER_UNREACHABLE, `the placement call to ${sshTarget}:${url}${route} failed unexpectedly: ${String(caught?.message ?? caught)}`, { route, retryable: true });
        last = error;
        if (error.retryable !== true || made >= maxAttempts) throw decorateAttempts(error, made, maxAttempts);
        await sleep(backoffMs(made));
      }
    }
    throw decorateAttempts(last, maxAttempts, maxAttempts);
  }

  return {
    kind: 'broker',
    url,
    sshTarget,
    describe() {
      return `broker ${url} over ssh ${sshTarget}`;
    },

    /**
     * `POST /place` — ask where one job should run. Never returns a default; throws when it
     * cannot ask. One `requestId` is generated (or supplied) per call and reused across every
     * attempt, so a retry after a lost answer cannot issue a second lease (I1/I2).
     */
    async place(task, { timeout, requestId } = {}) {
      const id = typeof requestId === 'string' && requestId.trim() !== '' ? requestId.trim() : randomUUID();
      const { json, ms, attempts } = await request('/place', { body: { task, requestId: id }, timeout, maxAttempts: callAttempts });
      const placement = assertPlacement(json, { route: '/place', body: json });
      placement.ms = ms;
      placement.attempts = attempts;
      placement.requestId = id;
      return placement;
    },

    /** `POST /done` — release the reservation. A broker that will not answer is a fact, not a failure of the child. */
    async done(lease, ok = true, { timeout } = {}) {
      const { json } = await request('/done', { body: { lease, ok: ok !== false }, timeout, maxAttempts: 1 });
      return json;
    },

    /** `GET /nodes[?fresh=1]` — the live mesh, every node with its age. Retried like `place`. */
    async nodes({ fresh = false, timeout } = {}) {
      const { json, attempts } = await request(`/nodes${fresh ? '?fresh=1' : ''}`, { method: 'GET', timeout, maxAttempts: callAttempts });
      if (!Array.isArray(json?.nodes)) {
        throw new BrokerError(
          BROKER_UNPARSABLE,
          `the broker's /nodes answer carries no node list (keys: ${Object.keys(json ?? {}).join(', ')}) [the authority answered; this body parsed but its shape is wrong, so it is not retried]`,
          { body: json, attempts, retried: attempts > 1 },
        );
      }
      return { ...json, attempts };
    },

    /** `GET /healthz` — used by the proof scripts to show the broker was live, not assumed live. */
    async healthz({ timeout } = {}) {
      const { json } = await request('/healthz', { method: 'GET', timeout, maxAttempts: 1 });
      return json;
    },

    log(line) {
      logger?.info?.(`remote-fanout: ${line}`);
    },
  };
}
