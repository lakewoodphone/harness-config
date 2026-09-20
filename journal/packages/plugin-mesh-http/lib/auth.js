/**
 * The route's own authentication: HMAC-SHA256 over the request body and a timestamp.
 *
 * WHY NOT THE ENGINE'S COOKIE FENCE
 * `ctx.webServer.register` hands the handler direct response ownership and the fence lives in
 * `dsh-client-connection`, which only fences `/api` and the channels it registers itself
 * (`docs/mesh/66-dsh-remote-capability.md` §2e, measured). A route registered here therefore
 * CHOSE its own auth, and the alternatives were all worse for this job:
 *
 *   * the cookie fence needs a launch token that is minted per process and never persisted
 *     (`66` §2c), so a dispatcher cannot mint one for another node and a harvested one dies
 *     on the next engine restart with a 401 indistinguishable from a permission error;
 *   * an IP allow-list cannot distinguish the devices on this tailnet — all six peers are
 *     enrolled under one Google identity (`scripts/phone-gate.py:2029-2032`, measured);
 *   * trusting the gate's device allow-list alone would make "which of the owner's devices"
 *     the whole authorisation, and every one of them can read the others' traffic by design.
 *
 * So the route authenticates the CALLER, not the device: something only a dispatcher that has
 * read `/etc/dsh-mesh.env` on that node can produce. The gate remains a second, independent
 * control in front of it (it refuses devices not in `phone-gate-allow.txt` before it relays
 * anything at all).
 *
 * THE SCHEME, EXACTLY
 *
 *   POST <path>
 *   x-mesh-timestamp: <unix seconds, decimal, no padding>
 *   x-mesh-nonce:     <8..64 chars of [A-Za-z0-9_-]>
 *   x-mesh-signature: <lowercase hex hmac-sha256>
 *   body:             the exact bytes
 *
 *     message   = "mesh-http-v1\n" + timestamp + "\n" + nonce + "\n" + body-bytes
 *     signature = hmac_sha256(secret, message)
 *     accept    = |now - timestamp| <= skewSeconds  AND  nonce not seen in that window
 *
 * The timestamp is inside the signed message, so it cannot be moved by a middle party; the
 * nonce is too, so two requests cannot be made to share one signature. Replay inside the
 * window is refused by the nonce ledger (`verify` → `replayed`), which is why the window can
 * stay generous enough for a clock that is a few seconds out without opening a replay hole.
 *
 * WHY THE COMPARISON IS `timingSafeEqual`
 * A byte-by-byte `===` on a MAC leaks, through timing, how many leading bytes were right; that
 * is the classic oracle that turns "cannot forge" into "can forge one byte at a time". The
 * comparison is constant-time and length-checked first (the length is not a secret).
 *
 * WHAT THIS IS NOT
 * It is not encryption and it is not transport security. On the tailnet this traffic is
 * WireGuard-encrypted between the two machines and terminates on loopback behind the gate;
 * over plain HTTP on a shared LAN it would be readable. See docs/mesh/83-http-transport.md §4
 * for the threat model stated as what an attacker CAN and CANNOT do.
 */

import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

/** The protocol tag inside the signed message. Changing it invalidates every old signature. */
export const PROTOCOL = 'mesh-http-v1';

/** The exact bytes that are signed. Body bytes last, unnormalised. */
export function signingMessage({ timestamp, nonce, body }) {
  return Buffer.concat([
    Buffer.from(`${PROTOCOL}\n${timestamp}\n${nonce}\n`, 'utf8'),
    Buffer.isBuffer(body) ? body : Buffer.from(String(body ?? ''), 'utf8'),
  ]);
}

/** Lowercase hex HMAC-SHA256 of the signing message. */
export function sign({ secret, timestamp, nonce, body }) {
  return createHmac('sha256', secret).update(signingMessage({ timestamp, nonce, body })).digest('hex');
}

/** A fresh nonce. 24 bytes of CSPRNG, base64url — collision is not a case worth handling. */
export function newNonce() {
  return randomBytes(24).toString('base64url');
}

/** Constant-time comparison of two hex strings of the same length. */
export function signatureMatches(expected, presented) {
  if (typeof expected !== 'string' || typeof presented !== 'string') return false;
  if (!/^[0-9a-f]+$/.test(presented) || presented.length !== expected.length) return false;
  const a = Buffer.from(expected, 'utf8');
  const b = Buffer.from(presented, 'utf8');
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** The nonce ledger: bounded, and it forgets a nonce exactly when the timestamp window expires. */
class NonceLedger {
  constructor({ windowSeconds, capacity = 8192 }) {
    this.windowMs = windowSeconds * 1000;
    this.capacity = capacity;
    this.seen = new Map();
  }

  /** @returns {true} when this (timestamp, nonce) has NOT been used inside the window. */
  claim(timestamp, nonce) {
    this.prune();
    const key = `${timestamp}:${nonce}`;
    if (this.seen.has(key)) return false;
    this.seen.set(key, Date.now());
    if (this.seen.size > this.capacity) {
      // The ledger is bounded by construction: a caller cannot grow the engine's memory by
      // sending requests. Oldest-first eviction is correct here because the ledger only ever
      // refuses a replay it still remembers, and the timestamp window is the real bound.
      const oldest = this.seen.keys().next();
      if (!oldest.done) this.seen.delete(oldest.value);
    }
    return true;
  }

  prune(now = Date.now()) {
    for (const [key, at] of this.seen) {
      if (now - at > this.windowMs) this.seen.delete(key);
      else break; // insertion order is time order, so the first survivor ends the scan
    }
  }

  get size() {
    return this.seen.size;
  }
}

/**
 * One verifier per route. Stateful by exactly one thing: the nonce ledger.
 */
export class MeshAuth {
  /**
   * @param {object} options
   * @param {() => {ok: boolean, secret?: string, path: string, reason?: string}} options.resolveSecret
   *   called per request, so a rotated file takes effect without a restart.
   * @param {number} options.skewSeconds accepted |now - timestamp|.
   * @param {() => number} [options.nowMs] injectable clock, for tests.
   */
  constructor({ resolveSecret, skewSeconds = 120, nowMs = () => Date.now() }) {
    this.resolveSecret = resolveSecret;
    this.skewSeconds = skewSeconds;
    this.nowMs = nowMs;
    this.ledger = new NonceLedger({ windowSeconds: skewSeconds });
  }

  /** Sign a body for dispatch. Used by the client half and by the tests. */
  static headersFor({ secret, body, timestamp, nonce }) {
    const ts = timestamp ?? Math.floor(Date.now() / 1000);
    const n = nonce ?? newNonce();
    return {
      'x-mesh-timestamp': String(ts),
      'x-mesh-nonce': n,
      'x-mesh-signature': sign({ secret, timestamp: String(ts), nonce: n, body }),
    };
  }

  /**
   * Verify one request's headers + body bytes.
   *
   * @returns {{ok: true, timestampMs: number}} | {{ok: false, status: number, reason: string,
   *   detail?: string, authenticated: boolean}}
   *
   * `authenticated` is false for every refusal that a caller could fix by signing correctly,
   * and true only for a refusal from a caller that DID authenticate (busy, path, and so on).
   * A 401 and a 503 must not be confused by a dispatcher deciding whether to fall back.
   */
  verify({ headers, body }) {
    const resolved = this.resolveSecret();
    if (resolved.ok !== true) {
      // 503, not 401: the node cannot authenticate ANYONE right now — its own configuration
      // is the fault, and a dispatcher must be able to tell "this node has no route/secret"
      // (fall back to v1) apart from "your signature is wrong" (do not).
      return { ok: false, status: 503, reason: 'node-has-no-secret', detail: resolved.reason, authenticated: false };
    }
    const timestamp = String(headers['x-mesh-timestamp'] ?? '');
    const nonce = String(headers['x-mesh-nonce'] ?? '');
    const presented = String(headers['x-mesh-signature'] ?? '');
    if (!/^\d{1,12}$/.test(timestamp)) {
      return { ok: false, status: 401, reason: 'bad-timestamp-header', authenticated: false };
    }
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(nonce)) {
      return { ok: false, status: 401, reason: 'bad-nonce-header', authenticated: false };
    }
    if (!/^[0-9a-f]{64}$/.test(presented)) {
      return { ok: false, status: 401, reason: 'bad-signature-header', authenticated: false };
    }
    const timestampMs = Number(timestamp) * 1000;
    const driftMs = Math.abs(this.nowMs() - timestampMs);
    if (driftMs > this.skewSeconds * 1000) {
      return {
        ok: false,
        status: 401,
        reason: 'outside-window',
        detail: `drift ${Math.round(driftMs / 1000)}s exceeds ${this.skewSeconds}s`,
        authenticated: false,
      };
    }
    const expected = sign({ secret: resolved.secret, timestamp, nonce, body });
    if (!signatureMatches(expected, presented)) {
      return { ok: false, status: 401, reason: 'bad-signature', authenticated: false };
    }
    // Only a request with a VALID MAC may consume a nonce: otherwise an unauthenticated
    // caller could burn nonces and deny service to the real dispatcher.
    if (!this.ledger.claim(timestamp, nonce)) {
      return { ok: false, status: 401, reason: 'replayed', authenticated: true };
    }
    return { ok: true, timestampMs };
  }
}
