/**
 * The lease table: the broker's ONLY state, and it is deliberately the smallest thing that
 * can work.
 *
 * §2.2: "A lease older than its TTL is reclaimed by the broker itself, so a dead dispatcher
 * cannot wedge the mesh." That single sentence is why this is a TTL and not a pid or a
 * liveness ping: a dispatcher that dies between /place and /done is not detected, it is
 * simply outlived. Nothing has to notice, nothing has to run, and no second process can be
 * wrong about whether the first is alive (packages/plugin-health/lib/governor.js:27-31
 * makes the same argument for the node-local governor: "pids are reused").
 *
 * WHY IN MEMORY, WITH NOTHING ON DISK
 * §2.2: "It stores nothing it can go stale on. No heartbeat table, no node state on disk
 * beyond live leases." A lease is *live* or it is nothing - it has no meaning after its TTL
 * and no meaning across a broker restart, and a broker restart therefore costs at most one
 * TTL of over-counted slots, never a stale answer. Writing them out would buy exactly
 * nothing and would be one more thing that can be believed after it is false.
 *
 * POSITION IS COMPUTED, NEVER STORED
 * §2.2 and the governor both insist on this (governor.js:37-39): a waiter holds nothing, so
 * "position" is a count of what is ahead of you right now, recomputed on every call. There
 * is no ticket, no FIFO, and therefore no queue that can rot. The cost, stated honestly:
 * a caller that arrives later can win a slot that frees up before an earlier queued caller.
 * FIFO would need a stored queue, which is the thing this design refuses to keep.
 */

import { randomBytes } from 'node:crypto';

/**
 * A lease TTL long enough for a real fleet, short enough that a dead dispatcher is
 * outlived within the same working session. 15 minutes: a 6-child fleet on a worker node
 * finishes well inside it, and an abandoned reservation is gone before the next coffee.
 * Overridable (`--lease-ttl-ms` / MESH_BROKER_LEASE_TTL_MS) so acceptance can use seconds.
 */
export const DEFAULT_LEASE_TTL_MS = 900_000;

/** A lease is either holding a slot or waiting for one. Nothing else holds memory (20-placement §4.1). */
export const LEASE_STATES = ['running', 'queued'];

let counter = 0;

/** An opaque lease id: opaque because nothing may parse it, and unique because a Map key needs it. */
function leaseId(now) {
  counter += 1;
  return `${now.toString(36)}-${process.pid.toString(36)}-${counter.toString(36)}-${randomBytes(4).toString('hex')}`;
}

/**
 * @param {{ttlMs?:number, now?:() => number}} [options]
 */
export function createLeaseTable(options = {}) {
  const defaultTtlMs = Number.isFinite(options.ttlMs) && options.ttlMs > 0 ? options.ttlMs : DEFAULT_LEASE_TTL_MS;
  const now = typeof options.now === 'function' ? options.now : () => Date.now();
  /** @type {Map<string, {id:string,node:string,kind:string,children:number,state:string,issuedAt:number,expiresAt:number,ttlMs:number}>} */
  const leases = new Map();

  /** Drop every expired lease. Called on every read, so no daemon is needed and none can be missing. */
  function reap(at) {
    let reaped = 0;
    for (const [id, lease] of leases) {
      if (lease.expiresAt <= at) {
        leases.delete(id);
        reaped += 1;
      }
    }
    return reaped;
  }

  function live(at) {
    reap(at);
    return [...leases.values()].sort((a, b) => a.issuedAt - b.issuedAt || (a.id < b.id ? -1 : 1));
  }

  function onNode(node, at) {
    return live(at).filter((lease) => lease.node === node);
  }

  function issue({ node, kind, children, state = 'running', at = now(), ttlMs = defaultTtlMs }) {
    const ttl = Number.isFinite(ttlMs) && ttlMs > 0 ? ttlMs : defaultTtlMs;
    const lease = {
      id: leaseId(at),
      node,
      kind,
      children,
      state: LEASE_STATES.includes(state) ? state : 'running',
      issuedAt: at,
      expiresAt: at + ttl,
      ttlMs: ttl,
    };
    leases.set(lease.id, lease);
    return { ...lease };
  }

  function byId(id, at = now()) {
    reap(at);
    const lease = leases.get(id);
    return lease === undefined ? null : { ...lease };
  }

  function release(id, at = now()) {
    reap(at);
    const lease = leases.get(id);
    if (lease === undefined) {
      return { released: false, node: null, state: null, heldMs: null };
    }
    leases.delete(id);
    return { released: true, node: lease.node, state: lease.state, heldMs: at - lease.issuedAt, children: lease.children, kind: lease.kind };
  }

  function stats(at = now()) {
    const all = live(at);
    return {
      live: all.length,
      running: all.filter((lease) => lease.state === 'running').length,
      queued: all.filter((lease) => lease.state === 'queued').length,
      byNode: all.reduce((accumulator, lease) => {
        accumulator[lease.node] = (accumulator[lease.node] ?? 0) + 1;
        return accumulator;
      }, {}),
      leaseTtlSec: Math.round(defaultTtlMs / 1000),
      oldestAgeSec: all.length === 0 ? null : Math.round((at - all[0].issuedAt) / 1000),
    };
  }

  return {
    issue,
    live: (at = now()) => live(at),
    onNode: (node, at = now()) => onNode(node, at),
    byId: (id, at = now()) => byId(id, at),
    release: (id, at = now()) => release(id, at),
    reap: (at = now()) => reap(at),
    stats: (at = now()) => stats(at),
    size: () => leases.size,
    defaultTtlMs,
  };
}
