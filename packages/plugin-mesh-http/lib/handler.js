/**
 * The `/mesh/run` request handler — the whole contract, in one function.
 *
 * ORDER OF OPERATIONS, AND WHY IT IS THAT ORDER
 *   1. method and content type  — refuse 405/415 before reading anything.
 *   2. read the body, bounded   — raw bytes, ceiling checked twice (`lib/body.js`).
 *   3. verify the MAC over EXACTLY those bytes (`lib/auth.js`).
 *   4. only then parse, validate and run.
 *
 * Nothing the caller sent is parsed, echoed or acted on before step 3, so an unauthenticated
 * caller cannot make this route allocate a parsed object, touch the filesystem, or produce a
 * log line about a prompt. The one thing a refused request does produce is a log line naming
 * its verdict — that is on purpose: a route that refuses silently is a route whose failures
 * are discovered by the owner, which is the failure mode this whole program exists to end.
 *
 * WHAT THE CALLER LEARNS WHEN IT IS REFUSED
 * Only one of the reasons is a reason a caller can act on by re-signing (`bad-signature`,
 * `outside-window`, `replayed`); the rest are the node's own state (`node-has-no-secret`,
 * `node-busy`). The distinction is carried in the status code and in `authenticated`, so a
 * dispatcher can tell "this node cannot serve me, fall back to ssh" from "my secret is wrong,
 * do not retry anywhere".
 */

import { IntakeError, isJsonContentType, parseJsonObject, readBoundedBody } from './body.js';
import { composeTask, usableWorkdir } from './runner.js';

/** Write one JSON response. Always `no-store`: a mesh reading cached by anything is a stale lie. */
export function sendJson(res, status, body, extraHeaders = {}) {
  const payload = Buffer.from(`${JSON.stringify(body)}\n`, 'utf8');
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(payload.byteLength),
    'cache-control': 'no-store',
    ...extraHeaders,
  });
  res.end(payload);
}

/** One line, on stdout and (when the composition provides one) in the engine's log. */
function logLine(log, fields) {
  log(`mesh-http ${JSON.stringify(fields)}`);
}

/**
 * @param {object} deps
 * @param {object} deps.config
 * @param {import('./auth.js').MeshAuth} deps.auth
 * @param {import('./runner.js').OneShotRunner} deps.runner
 * @param {() => object} deps.identity           `createNodeIdentity().describe()`
 * @param {(line: string) => void} deps.log
 */
export function createMeshRunHandler({ config, auth, runner, identity, log }) {
  return async function meshRunHandler(req, res) {
    const at = new Date().toISOString();
    const requestId = typeof req.headers['x-mesh-request-id'] === 'string' && /^[A-Za-z0-9._-]{1,64}$/.test(req.headers['x-mesh-request-id'])
      ? req.headers['x-mesh-request-id']
      : `local-${Math.random().toString(36).slice(2, 10)}`;
    const base = () => ({ at: new Date().toISOString(), requestId, ...identity() });
    const refuse = (status, reason, detail, extra = {}) => {
      logLine(log, { ...base(), verdict: 'refused', reason, status, detail: detail ?? null, ...extra });
      sendJson(res, status, { ok: false, reason, detail: detail ?? null, status, requestId, ...identity(), ...extra });
    };

    try {
      if (req.method !== 'POST') {
        res.setHeader('allow', 'POST');
        return refuse(405, 'method-not-allowed', `use POST, not ${req.method}`);
      }
      if (!isJsonContentType(req.headers['content-type'])) {
        return refuse(415, 'content-type-must-be-application-json', String(req.headers['content-type'] ?? 'absent'));
      }

      let body;
      try {
        body = await readBoundedBody(req, config.maxBodyBytes);
      } catch (error) {
        if (error instanceof IntakeError) return refuse(error.status, error.reason, error.detail ?? null);
        throw error;
      }

      const verdict = auth.verify({ headers: req.headers, body });
      if (verdict.ok !== true) {
        // The MAC check comes BEFORE any parse, so this is the first and only place a body that
        // failed authentication is described — and it is described by length, never content.
        if (verdict.status === 503) {
          return refuse(503, verdict.reason, verdict.detail ?? null, { authenticated: false, bodyBytes: body.byteLength });
        }
        return refuse(verdict.status, verdict.reason, verdict.detail ?? null, { authenticated: false, bodyBytes: body.byteLength });
      }
      logLine(log, { ...base(), verdict: 'hmac-valid', bodyBytes: body.byteLength, nonce: String(req.headers['x-mesh-nonce'] ?? '').slice(0, 12) });

      let request;
      try {
        request = parseJsonObject(body);
      } catch (error) {
        if (error instanceof IntakeError) return refuse(error.status, error.reason, 'body verified but not a JSON object');
        throw error;
      }

      const prompt = typeof request.prompt === 'string' ? request.prompt : '';
      if (prompt.trim() === '') return refuse(400, 'prompt-required', 'the body has no non-empty "prompt" string');
      if (prompt.length > config.maxPromptChars) {
        return refuse(413, 'prompt-too-large', `${prompt.length} chars > ${config.maxPromptChars}; the task travels as one argv entry, so the platform's own command-line ceiling is the binding limit`);
      }
      if (request.meshHost !== undefined && typeof request.meshHost === 'string' && request.meshHost.trim() !== '') {
        // The caller's expectation is echoed for the log, and it is NOT trusted: the running host
        // is the one this node measured, and a mismatch is the dispatcher's to detect, not ours.
        // (Refusing here would let a caller learn the node's real name by probing, which is
        // already answered by `/mesh/health`.)
      }
      let cwd = config.cwd;
      if (typeof request.workdir === 'string' && request.workdir.trim() !== '') {
        if (!config.allowRequestWorkdir) {
          return refuse(403, 'workdir-not-allowed', `this node pins its working directory to ${config.cwd}; a caller may not choose one`);
        }
        if (!usableWorkdir(request.workdir)) {
          return refuse(400, 'workdir-unusable', `not an existing directory on this node: ${request.workdir}`);
        }
        cwd = request.workdir;
      }
      if (!usableWorkdir(cwd)) {
        return refuse(503, 'node-workdir-unusable', `this node's configured working directory does not exist: ${cwd}`);
      }
      const requestedTimeout = Number(request.timeoutSec);
      const timeoutMs = Number.isFinite(requestedTimeout) && requestedTimeout > 0
        ? Math.min(Math.round(requestedTimeout * 1000), config.maxTimeoutSec * 1000)
        : config.defaultTimeoutSec * 1000;

      const me = identity();
      const task = composeTask({ prompt, host: me.host, meshHostLine: config.meshHostLine });
      const result = await runner.run({ task, cwd, timeoutMs, requestId, host: me.host });

      if (result.ok !== true) {
        // A refusal from the runner (busy) is not a failure of the request; it is the node
        // saying no, with a position. 429 + Retry-After is the honest answer.
        return refuse(result.status, result.reason, result.detail ?? null, {
          authenticated: true,
          busy: result.busy ?? null,
          retryAfterSec: config.busyRetryAfterSec,
        });
      }

      const answered = {
        ok: result.timedOut !== true && result.exitCode === 0 && result.spawnError === undefined,
        exitCode: result.exitCode ?? null,
        timedOut: result.timedOut === true,
        spawnError: result.spawnError ?? null,
        stdout: result.stdout,
        stderr: result.stderr,
        stdoutBytes: result.stdoutBytes,
        stderrBytes: result.stderrBytes,
        truncated: result.stdoutTruncated === true || result.stderrTruncated === true,
        host: me.host,
        node: me.node,
        nodeSource: me.nodeSource,
        fqdn: me.fqdn,
        ms: result.ms,
        requestId,
        artifacts: result.artifacts,
        // The device the gate reported, when the request came through the gate. Echoed as
        // provenance, never used as a credential: it is a header the caller's infrastructure
        // added, and this route's authorisation is the MAC, which does not depend on it.
        viaGate: typeof req.headers['x-forwarded-for'] === 'string' ? String(req.headers['x-forwarded-for']).slice(0, 128) : null,
      };
      logLine(log, {
        ...base(),
        verdict: 'ran',
        requestId,
        exitCode: answered.exitCode,
        timedOut: answered.timedOut,
        ms: answered.ms,
        stdoutBytes: answered.stdoutBytes,
        meshHostLineSeen: new RegExp(`^\\s*${config.meshHostLine.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\S`, 'm').test(result.stdout),
      });
      // 504 for a timeout and 502 for a child that could not be started: the caller asked for an
      // answer and did not get one, and the status should not look like success.
      const status = result.timedOut === true ? 504 : (result.spawnError !== undefined ? 502 : 200);
      sendJson(res, status, answered);
    } catch (error) {
      // A route that vanishes is worse than one that fails: the connection is answered, and the
      // exception is named in the log without any request content in it.
      logLine(log, { ...base(), verdict: 'error', error: String(error?.message ?? error) });
      if (!res.headersSent) {
        sendJson(res, 500, { ok: false, reason: 'node-error', detail: String(error?.message ?? error), requestId, ...identity() });
      } else {
        try { res.end(); } catch { /* already gone */ }
      }
    }
  };
}

/**
 * `GET /mesh/health` — how a dispatcher learns, before it spends a prompt, whether this node
 * has the route and a secret at all. Deliberately UNAUTHENTICATED and deliberately empty of
 * anything that helps an attacker: no secret, no paths beyond the ones a mesh operator already
 * knows, no prompt, no caller names.
 *
 * WHY IT IS WORTH ITS OWN ROUTE
 * The alternative is `POST /mesh/run` with a real prompt and a 3-minute timeout, discovering on
 * the 401 that the node has no route. A capability probe is the difference between a fallback
 * (v1 still works, the fleet keeps moving) and a failure.
 */
export function createMeshHealthHandler({ config, auth, runner, identity, log, version }) {
  return function meshHealthHandler(req, res) {
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      res.setHeader('allow', 'GET, HEAD');
      sendJson(res, 405, { ok: false, reason: 'method-not-allowed' });
      return;
    }
    const resolved = auth.resolveSecret();
    const me = identity();
    const body = {
      ok: true,
      service: 'mesh-http',
      protocol: 'mesh-http-v1',
      version,
      route: config.path,
      ...me,
      auth: {
        scheme: 'hmac-sha256-over(timestamp,nonce,body)',
        secretConfigured: resolved.ok === true,
        secretPath: resolved.path,
        secretReason: resolved.ok === true ? null : resolved.reason,
        skewSeconds: auth.skewSeconds,
        secretBytes: resolved.ok === true ? resolved.bytes : null,
      },
      limits: {
        maxBodyBytes: config.maxBodyBytes,
        maxPromptChars: config.maxPromptChars,
        maxTimeoutSec: config.maxTimeoutSec,
        defaultTimeoutSec: config.defaultTimeoutSec,
        oneRunAtATime: true,
      },
      runner: runner.view(),
      at: new Date().toISOString(),
    };
    logLine(log, { at: body.at, requestId: 'health', verdict: 'health', secretConfigured: body.auth.secretConfigured, busy: body.runner.busy });
    sendJson(res, 200, body);
  };
}
