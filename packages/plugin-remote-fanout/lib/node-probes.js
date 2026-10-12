/**
 * Read every node of the mesh DIRECTLY, from here, with no broker and no ssh.
 *
 * Every node's engine mounts `plugin-mesh-http`, which answers two routes on the
 * node's own gate (`https://<dns-label>.tail<tailnet>.ts.net`):
 *
 *   GET /mesh/health    unauthenticated, and rich: the node's own concurrency
 *                       decision, its binding term, its sources, its in-flight
 *                       count, its queue, and whether it holds a usable secret.
 *   GET /mesh/capacity  the node's capacity contract (schema 1) — cores, memory,
 *                       disk, agents, governor.
 *
 * This module is the read half of dispatcher-side placement. It is deliberately
 * the boring half: probe in parallel, bound every read, and turn every failure
 * into a RECORD rather than an exception, because the caller is deciding where
 * to send work and a node that did not answer must not be mistaken for a node
 * that is full.
 *
 * WHY A RECORD AND NOT A THROW
 * The single most expensive mistake in this system's history was reporting a
 * crisis that did not exist, because an absent reading was read as a bad one.
 * A probe that threw would make "the tailnet dropped one packet" and "the
 * machine is on fire" the same event. So `error` is a field, and the only field
 * a caller may interpret is the one that is present.
 */

import { NODES } from './nodes.js';

/** The DNS suffix this mesh is addressed by. Overridable so a test can point elsewhere. */
export const DEFAULT_TAILNET = 'tail93e6e6.ts.net';

/** How long one node's health read may take. Measured: 0.13-0.44 s on the two live nodes. */
export const DEFAULT_PROBE_TIMEOUT_MS = 8_000;

/**
 * The per-node base URL. The name is the node's own DNS LABEL — the capacity
 * contract's invariant is `node === fqdn.split('.')[0]` — so this is derived
 * from the same key the rest of the package places by, not a second table.
 */
export function nodeBaseUrl(node, { tailnet = DEFAULT_TAILNET } = {}) {
  return `https://${node}.${tailnet}`;
}

async function readJson(url, { timeoutMs, fetchImpl, headers }) {
  const started = Date.now();
  try {
    const response = await fetchImpl(url, {
      method: 'GET',
      headers: headers ?? { accept: 'application/json' },
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text();
    if (response.status !== 200) {
      return { ok: false, ms: Date.now() - started, status: response.status, error: `HTTP ${response.status}`, body: text.slice(0, 300) };
    }
    try {
      return { ok: true, ms: Date.now() - started, status: response.status, doc: JSON.parse(text) };
    } catch (error) {
      return { ok: false, ms: Date.now() - started, status: response.status, error: `not JSON (${String(error?.message ?? error)})`, body: text.slice(0, 300) };
    }
  } catch (error) {
    const name = error?.name === 'TimeoutError' ? 'timeout' : String(error?.code ?? error?.name ?? error?.message ?? error);
    return { ok: false, ms: Date.now() - started, error: name };
  }
}

/**
 * Probe ONE node. Never throws: a node that did not answer comes back as
 * `{ node, health: null, error: '...' }`.
 */
export async function probeNode(node, {
  tailnet = DEFAULT_TAILNET,
  timeoutMs = DEFAULT_PROBE_TIMEOUT_MS,
  fetchImpl = globalThis.fetch,
  wantCapacity = true,
} = {}) {
  const base = nodeBaseUrl(node, { tailnet });
  const health = await readJson(`${base}/mesh/health`, { timeoutMs, fetchImpl });
  if (health.ok !== true) {
    // A MISSING ROUTE IS NOT A DEAD MACHINE (measured 2026-10-12, post-migration).
    // Two live nodes of this mesh — `zabz-tech-linux` and the office box — reach
    // their engine through a local gate (`scripts/phone-gate.py`) that forwards
    // `/mesh/capacity` and answers 404 / 502 for `/mesh/health`. Reading only
    // health therefore threw two working nodes away and left the broker-unreachable
    // fallback with half a mesh, which is the same "one machine wearing the costume
    // of five" defect this module exists to remove.
    //
    // The second read is attempted ONLY when the gate answered at all: if the
    // health read timed out or never connected, the machine is genuinely
    // unreachable and a second full-length wait would only double the cost of a
    // dead node (the mac mini is off most nights).
    if (Number.isFinite(health.status)) {
      const retry = await readJson(`${base}/mesh/capacity`, { timeoutMs, fetchImpl });
      if (retry.ok === true) {
        return {
          node,
          base,
          health: null,
          healthStatus: health.status,
          healthError: health.error ?? `health answered HTTP ${health.status}`,
          capacity: retry.doc,
          capacityError: null,
          error: null,
          healthRouteMissing: true,
          ms: health.ms + retry.ms,
          status: health.status,
        };
      }
      return {
        node,
        base,
        health: null,
        healthStatus: health.status,
        healthError: health.error ?? `health answered HTTP ${health.status}`,
        capacity: null,
        capacityError: retry.error ?? 'capacity did not answer',
        error: retry.error ?? health.error ?? 'no mesh route answered',
        healthRouteMissing: false,
        ms: health.ms + retry.ms,
        status: health.status,
      };
    }
    return { node, base, health: null, error: health.error ?? 'health did not answer', ms: health.ms, status: health.status ?? null };
  }
  let capacity = null;
  let capacityError = null;
  if (wantCapacity === true) {
    const read = await readJson(`${base}/mesh/capacity`, { timeoutMs, fetchImpl });
    if (read.ok === true) capacity = read.doc;
    else capacityError = read.error ?? 'capacity did not answer';
  }
  return { node, base, health: health.doc, error: null, ms: health.ms, capacity, capacityError };
}

/**
 * Probe every node, IN PARALLEL, and return one observation per node named.
 *
 * @param {object} [options]
 * @param {string[]} [options.nodes]      node names; default = this package's own node table
 * @param {string}   [options.tailnet]
 * @param {number}   [options.timeoutMs]
 * @param {Function} [options.fetchImpl]  injected for tests
 * @returns {Promise<{observations: object[], reached: string[], unreachable: object[], at: string}>}
 */
export async function probeMesh({
  nodes = Object.keys(NODES),
  tailnet = DEFAULT_TAILNET,
  timeoutMs = DEFAULT_PROBE_TIMEOUT_MS,
  fetchImpl = globalThis.fetch,
  wantCapacity = true,
} = {}) {
  const names = Array.isArray(nodes) && nodes.length > 0 ? nodes : Object.keys(NODES);
  const settled = await Promise.all(names.map((name) => probeNode(name, { tailnet, timeoutMs, fetchImpl, wantCapacity })));
  const reached = settled.filter((o) => o.error === null).map((o) => o.node);
  const unreachable = settled.filter((o) => o.error !== null).map((o) => ({ node: o.node, error: o.error, ms: o.ms }));
  return { observations: settled, reached, unreachable, at: new Date().toISOString() };
}

/**
 * The ssh destination this package would use for a node — so a caller that has
 * to fall back to v1 ssh takes that fact from the SAME table placement uses.
 */
export function sshDestinationFor(node) {
  return NODES[node]?.ssh ?? null;
}

/** Whether this package's own node table knows how to run a child on a node. */
export function isDispatchableNode(node) {
  const facts = NODES[node];
  return facts !== undefined && typeof facts.ssh === 'string' && facts.ssh !== '';
}
