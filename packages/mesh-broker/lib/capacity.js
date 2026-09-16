/**
 * The capacity client: read one node's `GET /mesh/capacity` (§2.1) through that node's
 * gate, over the tailnet, with a short timeout.
 *
 * WHY DIRECT READS AND NOT A HEARTBEAT TABLE
 * `docs/mesh/66-dsh-remote-capability.md` §4, item 1: "DROP the federation, keep the
 * surface ... the placement service reads each candidate node's /healthz directly, over
 * the tailnet, with a bounded timeout; the authority stores only the decision." §5 of the
 * program says the same thing from the other side: "A heartbeat table of node state - the
 * broker re-reads. Stale state is how this system has lied to itself before." So there is
 * no PUBLISH verb here, no heartbeat, and no node state on disk. A reading lives in a Map
 * with a timestamp for at most 15 s and then it is gone.
 *
 * WHY node:http AND NOT fetch()
 * Two reasons, both practical. `fetch` is still flagged experimental on the authority's
 * Node v20.20.2 and a service should not print warnings it cannot act on; and a raw
 * request gives an explicit socket timeout and an explicit latency measurement, which is
 * what "a short timeout, and an age for every reading" needs.
 *
 * THIS FUNCTION NEVER REJECTS. A read that times out, refuses, returns 500 or returns
 * invalid JSON resolves to `{ok:false, error}`. A client that throws is a client that
 * refuses, and refusal is the one thing this mesh does not do - the caller turns every
 * failure into `unreachable` with an age.
 */

import http from 'node:http';
import https from 'node:https';

/** The route stream S1 adds to the gate (docs/mesh/71-mesh-program.md §2.1). */
export const CAPACITY_PATH = '/mesh/capacity';

/** Short by design: a placement decision must not wait on a sleeping laptop. */
export const DEFAULT_READ_TIMEOUT_MS = 1500;

/** A capacity document is a few hundred bytes; anything larger is not one. */
export const MAX_BODY_BYTES = 256 * 1024;

/** `https://zabz-tech.tail93e6e6.ts.net` + `/mesh/capacity`. */
export function capacityUrl(node) {
  const base = String(node?.baseUrl ?? '').replace(/\/+$/, '');
  return `${base}${CAPACITY_PATH}`;
}

/**
 * GET a URL and parse it as JSON. Always resolves.
 *
 * @param {string} url
 * @param {{timeoutMs?:number}} [options]
 * @returns {Promise<{ok:boolean, status:number|null, doc:any|null, error:string|null, latencyMs:number, bytes:number}>}
 */
export function httpGetJson(url, options = {}) {
  const timeoutMs = Number.isFinite(options.timeoutMs) && options.timeoutMs > 0
    ? options.timeoutMs
    : DEFAULT_READ_TIMEOUT_MS;
  const startedAt = Date.now();
  return new Promise((resolve) => {
    let settled = false;
    // TWO timers, because one is not enough and the live run on the authority proved it:
    // `request.setTimeout()` is a SOCKET-INACTIVITY timeout, so a name that resolves slowly
    // (MagicDNS, a SYN into a black hole) spends its DNS time before the socket timeout even
    // starts. Measured 2026-09-16 on secratary: `zabz-tech-linux` reported
    // latencyMs 3031 against a 1500 ms timeout - exactly two timeouts deep. The hard timer
    // below is what makes "a short timeout" true in wall-clock terms.
    let hardTimer = null;
    const done = (result) => {
      if (settled) return;
      settled = true;
      if (hardTimer !== null) clearTimeout(hardTimer);
      resolve({ status: null, doc: null, error: null, bytes: 0, ...result, latencyMs: Date.now() - startedAt });
    };
    let parsed;
    try {
      parsed = new URL(url);
    } catch (error) {
      done({ ok: false, error: `invalid url ${JSON.stringify(url)}: ${error.message}` });
      return;
    }
    const transport = parsed.protocol === 'https:' ? https : http;
    let request;
    try {
      request = transport.get(parsed, {
        headers: { accept: 'application/json', 'user-agent': 'mesh-broker/0.1.0' },
      }, (response) => {
        const chunks = [];
        let size = 0;
        response.on('data', (chunk) => {
          size += chunk.length;
          if (size > MAX_BODY_BYTES) {
            response.destroy();
            done({ ok: false, status: response.statusCode ?? null, error: `response body exceeded ${MAX_BODY_BYTES} bytes` });
            return;
          }
          chunks.push(chunk);
        });
        response.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf8');
          let doc = null;
          let parseError = null;
          try {
            doc = JSON.parse(body);
          } catch (error) {
            parseError = error.message;
          }
          const status = response.statusCode ?? null;
          if (status !== 200) {
            done({ ok: false, status, doc, error: `HTTP ${status}`, bytes: Buffer.byteLength(body) });
            return;
          }
          if (parseError !== null) {
            done({ ok: false, status, error: `invalid JSON: ${parseError}`, bytes: Buffer.byteLength(body) });
            return;
          }
          done({ ok: true, status, doc, error: null, bytes: Buffer.byteLength(body) });
        });
        response.on('error', (error) => done({ ok: false, status: response.statusCode ?? null, error: error.message }));
      });
    } catch (error) {
      done({ ok: false, error: error.message });
      return;
    }
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error(`timed out after ${timeoutMs} ms`));
    });
    hardTimer = setTimeout(() => {
      request.destroy(new Error(`timed out after ${timeoutMs} ms (hard wall-clock deadline)`));
    }, timeoutMs);
    if (typeof hardTimer.unref === 'function') hardTimer.unref();
    request.on('error', (error) => done({ ok: false, error: error.message }));
  });
}

/**
 * Is this a usable §2.1 document? Every field is measured or absent, so the only hard
 * requirement is the three things that identify the document at all.
 *
 * `mem.freeMiB: null` is ACCEPTED, and this is deliberate: stream S1's own checker
 * (`scripts/mesh-capacity-probe.ps1:259`) allows it, because "every field is measured or
 * absent" - a node that answered but could not measure its memory is a node that ANSWERED.
 * Calling it unreachable would be a false statement about reachability, which is worse than
 * reporting zero known slots. It arrives at the scoring with `slotsKnown: false` and a
 * rationale line saying the reading is missing.
 *
 * A mismatched `node` name is accepted but reported (`reportedNode`), not rejected: a gate
 * that names itself `zabz-yoga-1` where the roster says `zabz-yoga` is a labelling
 * disagreement, and silently calling a live node unreachable over it would be worse.
 */
export function validateCapacity(doc, expectedNode) {
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) {
    return { ok: false, reason: 'the body is not a JSON object' };
  }
  if (doc.schema !== 1) {
    return { ok: false, reason: `schema ${JSON.stringify(doc.schema)} is not 1` };
  }
  if (typeof doc.node !== 'string' || doc.node.length === 0) {
    return { ok: false, reason: 'node is not a non-empty string' };
  }
  const freeMiB = doc.mem?.freeMiB;
  if (freeMiB !== null && freeMiB !== undefined && (typeof freeMiB !== 'number' || !Number.isFinite(freeMiB))) {
    return { ok: false, reason: `mem.freeMiB is ${JSON.stringify(freeMiB)}, which is neither a number nor null` };
  }
  const notes = [];
  if (freeMiB === null || freeMiB === undefined) {
    notes.push('mem.freeMiB is null: this node answered but did not measure its free memory, so its slot budget is unknown (it is reachable, not unreachable)');
  }
  if (expectedNode !== undefined && expectedNode !== null && doc.node !== expectedNode) {
    notes.push(`the document names itself "${doc.node}", the roster says "${expectedNode}"`);
  }
  return { ok: true, note: notes.length === 0 ? null : notes.join('; ') };
}

/**
 * Read one node. The default reader used by the broker; injectable so the tests can drive
 * every failure mode without a network.
 */
export async function readNodeCapacity({ node, timeoutMs = DEFAULT_READ_TIMEOUT_MS }) {
  const url = capacityUrl(node);
  const result = await httpGetJson(url, { timeoutMs });
  if (!result.ok) return { ...result, url };
  const check = validateCapacity(result.doc, node.node);
  if (!check.ok) {
    return { ...result, ok: false, url, error: `capacity document rejected: ${check.reason}` };
  }
  return { ...result, url, note: check.note };
}
