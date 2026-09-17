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

/**
 * The SECOND attempt's timeout, for a node that timed out but is demonstrably alive.
 *
 * MEASURED 2026-09-16 23:31:18Z: the deployed broker said `zabz-yoga: unreachable (timed out
 * after 1500 ms)` while that laptop's own gate was answering in 89-232 ms and one tailnet read
 * to `zabz-tech` took 7342 ms. The laptop was BUSY, not gone - it was running the acceptance
 * harness - and "busy" and "dead" are different facts that call for different actions: a slow
 * node should be ranked lower, a dead one avoided entirely.
 *
 * So a timeout gets exactly ONE retry at this longer budget, and the pairing is what makes the
 * distinction legitimate: within a single read, the first attempt failing and the second
 * succeeding can only mean a slow process, because a refused connection or a dead machine
 * cannot produce a success a few seconds later. Worst case per slow node per re-read is
 * 1500 + 4000 ms, which is a hard bound a caller can rely on. 4000 ms is not a guess: the
 * Mac Mini was measured answering a tailnet read door-to-door in 7342 ms under load, and the
 * dispatcher's own patience is longer than either number.
 */
export const RETRY_READ_TIMEOUT_MS = 4000;

/**
 * The error codes that mean "nothing is listening / nothing is there", as opposed to "it did
 * not answer in time". A refusal is a fact about the far side and is never retried.
 */
export const NEVER_ANSWERS_CODES = ['ECONNREFUSED', 'EHOSTUNREACH', 'ENETUNREACH', 'ENOTFOUND', 'EAI_AGAIN', 'ECONNRESET', 'EPIPE', 'ERR_INVALID_URL'];

/**
 * What makes a retried read SLOW. The rule is deliberately the simple one: **a retry happened**,
 * which means the node did not answer inside our deadline on the first attempt. The approved
 * wording is exact - "a second, longer attempt succeeds" is `slow` - and the rule is honest about
 * what it measured: *this read missed the deadline*, not "this node is congested".
 *
 * WHY IT IS NOT TIGHTENED FURTHER. A first version of this file marked `slow` only when the
 * retry was ALSO slow (>= 400 ms after a >= 1 s read), on the theory that a cold first read -
 * name resolution plus a TLS handshake, neither of which happens again - is a hiccup rather than
 * a busy node. MEASURED on the authority 23:58Z: the broker's first GET to `zabz-yoga-1` missed
 * the 1500 ms deadline and the retry answered in 455 ms, while three direct `curl` reads of the
 * same gate from the same machine took 0.15-0.32 s each. Both rules describe that event
 * differently and only one of them is defensible: the read DID miss the deadline, and the
 * ranking penalty is transient - the next read of a warm node comes back `ok` and full rank
 * (tested). A rule that hides the miss would be the "confident wrong number" this project exists
 * to avoid, so the miss is reported, with the numbers, and the cost of a false `slow` is bounded
 * to one read and one tier.
 *
 * The floor below is kept only for the `/nodes` note's wording, so a retry that came back fast is
 * still described as fast rather than as congestion.
 */
export const SLOW_READ_FLOOR_MS = 1000;

/** The retry latency below which a `slow` label is reported as a cold-start miss, not congestion. */
export function slowRetryFloorMs(timeoutMs) {
  const base = Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : DEFAULT_READ_TIMEOUT_MS;
  return Math.max(400, Math.round(base / 3));
}

/**
 * Why a read failed, as one of a small closed set, so callers can act on the KIND of failure
 * instead of matching on an English sentence. `timeout` is the only one that is retried.
 */
export function classifyReadError(error) {
  const message = error instanceof Error ? error.message : String(error ?? '');
  const code = typeof error?.code === 'string' ? error.code : null;
  if (code !== null && NEVER_ANSWERS_CODES.includes(code)) return code === 'ECONNREFUSED' ? 'refused' : 'never-answers';
  if (/timed out after|ETIMEDOUT|Timeout/i.test(message)) return 'timeout';
  if (/ENOTFOUND|EAI_AGAIN|getaddrinfo|name not resolved|dns/i.test(message)) return 'dns';
  if (/ECONNRESET|socket hang up|EPIPE/i.test(message)) return 'reset';
  if (/ECONNREFUSED|EHOSTUNREACH|ENETUNREACH/i.test(message)) return 'refused';
  return 'other';
}

/** A failure worth one longer second attempt: only a timeout, and only a timeout. */
export function isRetryableRead(result) {
  return result?.ok !== true && result?.errorKind === 'timeout';
}

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
      const withTiming = { status: null, doc: null, error: null, bytes: 0, ...result, latencyMs: Date.now() - startedAt };
      // `errorKind` is the classification of WHY it failed, in a closed set, so a caller can
      // say "slow" instead of "unreachable" without parsing the sentence (`classifyReadError`).
      // The original Error is preferred when there is one: Node puts the errno code
      // (`ECONNREFUSED`, `ETIMEDOUT`) on it and the sentence may not carry that code.
      const cause = result.errorObject ?? (withTiming.error === null ? null : Object.assign(new Error(withTiming.error), { code: withTiming.code ?? null }));
      resolve({ ...withTiming, errorKind: withTiming.ok === true ? null : classifyReadError(cause) });
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
        response.on('error', (error) => done({ ok: false, status: response.statusCode ?? null, error: error.message, code: error.code ?? null }));
      });
    } catch (error) {
      done({ ok: false, error: error.message, code: error.code ?? null });
      return;
    }
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error(`timed out after ${timeoutMs} ms`));
    });
    hardTimer = setTimeout(() => {
      request.destroy(new Error(`timed out after ${timeoutMs} ms (hard wall-clock deadline)`));
    }, timeoutMs);
    if (typeof hardTimer.unref === 'function') hardTimer.unref();
    request.on('error', (error) => done({ ok: false, error: error.message, code: error.code ?? null }));
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
 *
 * TWO ATTEMPTS, ONE MEANING (requirement 3, approved 2026-09-17). A timeout gets exactly one
 * retry at `retryTimeoutMs` (4000), and the pairing is what turns "no answer in 1500 ms" into
 * an honest reading of the machine: a node that answers 2 s later was BUSY, and a node that
 * does not answer at all - or refuses the connection outright - is gone. The two states are
 * reported as `slow` and `unreachable` respectively, never conflated, because the first should
 * be ranked lower and the second avoided entirely. A refusal, a DNS failure, a 5xx or bad JSON
 * is never retried: those are facts about the far side that a second second cannot change.
 *
 * The worst case is bounded at `timeoutMs + retryTimeoutMs` (5.5 s at the defaults), which is
 * what keeps a caller that must not hang still safe.
 *
 * A 200 that is not a usable §2.1 document is `capacity-unreadable`, NOT unreachable and NOT a
 * silent drop (requirement 4): the node answered, so calling it unreachable would be a false
 * claim, and dropping it would hide a broken reader behind an offline-looking row.
 */
export async function readNodeCapacity({ node, timeoutMs = DEFAULT_READ_TIMEOUT_MS, retryTimeoutMs }) {
  // The retry budget SCALES with the configured deadline when the caller does not name one:
  // a 300 ms timeout (the tests) must not grow a 4000 ms second attempt, or the caller's own
  // bound becomes meaningless. Four times the first attempt, floored at 1 s, capped at the
  // measured 4000 ms - so the shipping pair is (1500, 4000) and a tight pair stays tight.
  const retryBudgetMs = Number.isFinite(retryTimeoutMs) && retryTimeoutMs > 0
    ? retryTimeoutMs
    : Math.min(RETRY_READ_TIMEOUT_MS, Math.max(1000, Math.round(timeoutMs * 4)));
  const url = capacityUrl(node);
  const startedAt = Date.now();
  let result = await httpGetJson(url, { timeoutMs });
  let retried = false;
  let firstLatencyMs = result.latencyMs;
  if (isRetryableRead(result)) {
    retried = true;
    result = await httpGetJson(url, { timeoutMs: retryBudgetMs });
  }
  const elapsedMs = Date.now() - startedAt;
  if (!result.ok) {
    return { ...result, url, retried, firstLatencyMs, elapsedMs };
  }
  const check = validateCapacity(result.doc, node.node);
  if (!check.ok) {
    return {
      ...result,
      ok: false,
      url,
      retried,
      firstLatencyMs,
      elapsedMs,
      status: result.status,
      doc: result.doc,
      state: 'capacity-unreadable',
      error: `capacity document rejected: ${check.reason}`,
      reason: check.reason,
    };
  }
  // SLOW = the first attempt missed our deadline and the second answered. See SLOW_READ_FLOOR_MS
  // above for why the rule is this simple and what it costs.
  const slow = retried;
  const retryWasFast = slow && result.latencyMs < slowRetryFloorMs(timeoutMs);
  return {
    ...result,
    url,
    retried,
    firstLatencyMs,
    elapsedMs,
    // The validator's note (a labelling disagreement, a null freeMiB) still travels with a
    // good reading: /nodes surfaces it as `warning`.
    note: check.note ?? result.note ?? null,
    state: slow ? 'slow' : 'ok',
    // Whether the retry came back fast, which distinguishes "missed the deadline once (cold)"
    // from "still slow on the second attempt (congested)" in the wording of the note.
    retryWasFast,
  };
}
