/**
 * The failover placer: ask the broker, and if the broker cannot be ASKED, read
 * the mesh directly from here and place from what this machine can measure.
 *
 * ── WHY THIS FILE EXISTS, IN ONE MEASUREMENT ────────────────────────────────
 *
 * 2026-10-09, from ZABZ-YOGA, with the owner watching:
 *
 *   remote-ssh: broker-unreachable: the placement broker could not be reached at
 *   secratary-ts:http://localhost:3091/place — ssh exited 255: ssh: connect to
 *   host secratary.tail93e6e6.ts.net port 22: Connection timed out
 *
 * while `zabz-yoga-1` and `zabz-tech` were both answering `GET /mesh/health` in
 * under a quarter of a second. The `subagent` tool — the mesh provider — could
 * not start a single child. **The fan-out plane's availability was the
 * availability of one process on one machine**, and that machine is a 4-core
 * box that also runs the company API and is offline as a matter of routine.
 *
 * ── HOW IT COMPOSES, AND WHY THAT SHAPE ─────────────────────────────────────
 *
 * This is a WRAPPER around the real broker placer (`createNodePlacer`), never a
 * reimplementation of it. That matters: the broker placer owns the pressure
 * policy, the prefer-remote policy, the per-child lease, the queue, the
 * credential-aware node table and the lease record — all of it measured and all
 * of it under test. A wrapper that re-implemented any of that would be a second
 * source of truth for placement, which is the defect class this whole
 * programme exists to kill.
 *
 * So every call delegates; `acquire()` is the only one with a branch:
 *
 *   broker answers        → the inner placer's placement, `source: broker`
 *   broker UNREACHABLE    → this machine probes every node and places, `source: direct-probe`
 *   broker answers badly  → the error propagates (a live broker with a bad
 *                           answer is a bug, and hiding it behind a fallback
 *                           would be the `broker-unparsable` version of a
 *                           silent default)
 *   neither can place     → one error naming both halves, and no local default
 *
 * ── THE LEASE, WHEN THERE IS NO BROKER ──────────────────────────────────────
 *
 * A broker lease is an accounting object and there is nothing to account
 * against without the broker, so a probe placement carries a LOCAL lease marked
 * `leaseSource: 'local'`. That keeps the provider's release path total and — the
 * part that matters — lets a reader of the ledger tell at a glance which
 * placements were broker-accounted and which were decided by a machine on its
 * own.
 */

import { BrokerError, BROKER_UNREACHABLE } from './broker-client.js';
import { chooseFailoverPlacement, NO_CANDIDATE } from './failover-placement.js';
import { probeMesh } from './node-probes.js';
import { factsForNode, invocationForNode, NODES, nodeNames } from './nodes.js';
import {
  barredNodeNames,
  loadPosture,
  placementRefusal,
  postureForNode,
  PostureRefusalError,
} from './posture.js';

/** The placement was made by reading the nodes directly, because the broker could not be asked. */
export const SOURCE_DIRECT_PROBE = 'direct-probe';

/** Every node was unreachable AND the broker could not be asked — the mesh is genuinely unusable. */
export const MESH_UNREACHABLE_NO_PROBE = 'mesh-unreachable-no-probe';

/** A local lease id, prefixed so nobody can mistake it for a broker lease in a log or a ledger. */
function localLeaseId(id) {
  return `local-${String(id ?? 'child').slice(0, 40)}-${Date.now().toString(36)}`;
}

/** The error code of anything, whether it is a real `BrokerError` or a plain object with a code. */
function codeOf(error) {
  return error?.code ?? error?.cause?.code ?? null;
}

/**
 * Wrap a placer so that a broker that cannot be REACHED stops meaning "no
 * children today".
 *
 * @param {object} config
 * @param {object} config.inner              the broker placer from `createNodePlacer` (required)
 * @param {Function} [config.probeMeshImpl]  injected probe, for tests
 * @param {string[]} [config.nodes]          nodes to probe; default = this package's node table
 * @param {string}   [config.tailnet]
 * @param {number}   [config.probeTimeoutMs]
 * @param {number}   [config.children]
 * @param {string[]} [config.exclude]
 * @param {string|null} [config.thisNode]
 * @param {boolean}  [config.preferRemote]
 * @param {string}   [config.remoteProfile]
 * @param {string}   [config.remoteHome]
 * @param {object}   [config.logger]
 */
export function createFailoverPlacer(config = {}) {
  const inner = config.inner;
  if (inner === undefined || typeof inner.acquire !== 'function') {
    throw new Error('remote-fanout: a failover placer needs an `inner` placer with acquire() — it wraps the broker placer, it does not replace it');
  }
  const logger = config.logger;
  const probe = typeof config.probeMeshImpl === 'function' ? config.probeMeshImpl : probeMesh;
  const nodes = Array.isArray(config.nodes) && config.nodes.length > 0 ? config.nodes : Object.keys(NODES);
  const children = Number.isFinite(config.children) && config.children > 0 ? config.children : 1;
  /**
   * THE MACHINE-POSTURE GATE, SHARED WITH THE BROKER PLACER.
   *
   * This placer has TWO ways to name a node: the inner broker placer (which gates
   * its own answer) and this machine's own probe, which is the whole point of the
   * file. The probe path is a placement too — it turns a node name into an ssh
   * destination and runs a child — so it answers the same question, from the same
   * file, through the same module. Absent an injected table it is re-read on every
   * acquisition, for the reason `placement.js` gives: a cached freeze is a freeze
   * that a later decision does not reach.
   */
  const posture = config.posture;
  const postureLoader = typeof config.postureLoader === 'function' ? config.postureLoader : loadPosture;
  const allowReadOnly = config.allowReadOnly === true;
  /** The last reason the broker could not be asked — carried on every probe placement. */
  let lastBrokerFailure = null;

  function placementFromProbe(decision, { id, childIndex, at, designation }) {
    const node = decision.node;
    const facts = factsForNode(node);
    if (facts === undefined) {
      throw new BrokerError(
        'placement-node-unknown',
        `this dispatcher's own probe named node "${node}", which is not in this package's node table (${nodeNames().join(', ')}) — refusing to dispatch into a lookup miss`,
        { node, known: nodeNames() },
      );
    }
    // THE SAME GATE AS THE BROKER PLACER'S, on the path that does not ask anyone.
    const refused = placementRefusal(node, {
      designations: designation.designations,
      nodes: NODES,
      file: designation.file,
      allowReadOnly,
    });
    if (refused !== null) {
      throw new PostureRefusalError(
        refused.code,
        `${refused.message}\n`
        + `  PLACEMENT MODE : direct probe (the broker could not be asked: ${lastBrokerFailure?.message ?? 'unreachable'}) — this machine`
        + ` ranked every node itself, and the winner is not placeable.\n`
        + `  NOTHING WAS DISPATCHED, and no child ran on "${node}". No lease was taken either: a probe placement holds a LOCAL lease.`,
        refused.detail,
      );
    }
    return {
      source: SOURCE_DIRECT_PROBE,
      id,
      childIndex,
      node,
      ssh: facts.ssh,
      hosts: facts.hosts,
      position: decision.position,
      tier: decision.position > 0 ? 'queued' : 'fits',
      score: decision.freeSlots,
      eligible: decision.ranked.length,
      blockedBy: [],
      lease: localLeaseId(id),
      leaseSource: 'local',
      leaseTtlSec: null,
      expiresAt: null,
      rationale: decision.rationale,
      queue: [],
      placedAt: new Date(at).toISOString(),
      brokerAt: null,
      brokerCallMs: null,
      state: decision.position > 0 ? 'queued' : 'placed',
      transports: decision.transports,
      probe: {
        source: decision.source,
        reached: decision.ranked.map((r) => r.node),
        unreachable: decision.unreachable,
        freeSlots: decision.freeSlots,
        children,
      },
      // The broker is gone; this is the reading that took its place, and the
      // reason it had to. Both travel with the placement, so the ledger can be
      // read back without the engine log.
      brokerFailure: lastBrokerFailure,
      facts: {
        command: facts.command,
        credentialEnvFiles: facts.credentialEnvFiles,
        driver: facts.driver,
        bin: facts.bin,
        profile: config.remoteProfile,
        dshHome: config.remoteHome,
        cwd: facts.cwd,
        shell: facts.shell,
      },
      invocation: invocationForNode(node),
      posture: { ...postureForNode(node, { designations: designation.designations, nodes: NODES }), file: designation.file },
      pressureLine: `pressure was NOT re-evaluated by the direct probe: this placement exists because the broker could not be asked, and the probe's own ranking is the decision (${decision.rationale[decision.rationale.length - 1] ?? 'no rationale'})`,
      note: decision.rationale.join(' | '),
    };
  }

  return {
    kind: 'failover',
    get inner() { return inner; },

    describe() {
      return `broker ${typeof inner.describe === 'function' ? inner.describe() : '(unknown)'} + direct node probe (${nodes.length} node(s))`;
    },
    explain() {
      return 'one placement per child: the broker is asked first and its answer is used as-is; a broker that cannot be REACHED is replaced by this machine reading each node\'s own /mesh/health and ranking the answers itself';
    },

    /** True while the last broker call succeeded or before any was made. */
    get brokerReachable() {
      return lastBrokerFailure === null;
    },

    /** For a reader of the boot log and the ledger. */
    get lastBrokerFailure() {
      return lastBrokerFailure;
    },

    async acquire(options = {}) {
      const { id, childIndex } = options;
      // THE DESIGNATION IS READ FIRST, before the broker is asked and before this
      // machine probes anything. If it cannot be read the whole acquisition
      // refuses: a probe is a placement, and a placement decided without the
      // posture file is a placement decided by guesswork.
      const designation = posture !== undefined ? posture : postureLoader();
      const barred = barredNodeNames({ designations: designation.designations, nodes: NODES, allowReadOnly });
      try {
        const placement = await inner.acquire(options);
        lastBrokerFailure = null;
        return { ...placement, source: placement?.source ?? 'broker' };
      } catch (error) {
        // ONLY "COULD NOT BE ASKED" IS A REASON TO PROBE, and this is the one
        // branch in the file. A live broker whose answer does not parse is a bug
        // in the broker: probing around it would hide that behind a fallback,
        // which is the same class of mistake as silently defaulting to a node.
        if (codeOf(error) !== BROKER_UNREACHABLE) throw error;
        lastBrokerFailure = {
          code: BROKER_UNREACHABLE,
          message: String(error?.message ?? error),
          at: new Date().toISOString(),
        };
        logger?.warn?.(
          `remote-fanout: the placement broker is UNREACHABLE (${lastBrokerFailure.message}) — `
          + `falling back to reading ${nodes.length} node(s) directly, here, now; this placement is recorded as source=${SOURCE_DIRECT_PROBE}`,
        );
      }

      const probed = await probe({ nodes, tailnet: config.tailnet, timeoutMs: config.probeTimeoutMs });
      const decision = chooseFailoverPlacement(probed.observations, {
        // A host whose posture is not writable is offered to the ranking as an
        // exclusion — a preference, never the guarantee. The guarantee is the
        // check on the winner, in `placementFromProbe`.
        exclude: [...new Set([...(Array.isArray(config.exclude) ? config.exclude : []), ...barred])],
        thisNode: config.thisNode ?? null,
        children,
        preferRemote: config.preferRemote === true,
      });

      if (decision.node === null || decision.code === NO_CANDIDATE) {
        throw new BrokerError(
          MESH_UNREACHABLE_NO_PROBE,
          `no node could take this child and the broker could not be asked either. `
          + `Broker: ${lastBrokerFailure?.message ?? 'unreachable'}. `
          + `Direct probe: ${probed.reached.length} of ${nodes.length} node(s) answered (${probed.reached.join(', ') || 'none'}); `
          + `unreachable: ${probed.unreachable.map((u) => `${u.node} (${u.error})`).join(', ') || 'none'}. `
          + `Nothing was dispatched and NO local default was used — a silent default is how a mesh of one machine looks like a mesh of five. `
          + `Fix or start one node and retry, or run the work locally ON PURPOSE (subagent_local) so the fallback is visible in the report.`,
          { brokerFailure: lastBrokerFailure, probe: { reached: probed.reached, unreachable: probed.unreachable, rationale: decision.rationale } },
        );
      }

      const placement = placementFromProbe(decision, { id, childIndex, at: Date.now(), designation });
      logger?.info?.(
        `remote-fanout: child ${id} placed on "${placement.node}" by DIRECT PROBE (broker unreachable) — `
        + `${decision.freeSlots ?? 'unmeasured'} free slot(s), position ${decision.position}, transports ${decision.transports.join('>') || 'none'}`,
      );
      return placement;
    },

    /**
     * With no broker there is no queue to poll. The provider calls this only
     * when `position > 0`; polling every node once per child per interval is
     * exactly the traffic the broker existed to avoid, so a probe placement
     * reports the position it already read and lets the provider's own
     * `queueWaitMs` bound the wait. It never blocks.
     */
    async waitForSlot(placement, options = {}) {
      if (placement?.source === SOURCE_DIRECT_PROBE) {
        return {
          settled: placement.position === 0,
          phase: placement.position === 0 ? 'start-now' : 'probe-queued',
          waitedMs: 0,
          freeSlots: placement.score ?? null,
          note: placement.position === 0
            ? 'placed by direct probe at position 0 — dispatched immediately'
            : 'placed by direct probe; the queue position was read from the node itself and is not re-polled (no broker)',
        };
      }
      if (typeof inner.waitForSlot !== 'function') return { settled: true, phase: 'start-now', waitedMs: 0, note: 'the inner placer has no queue wait' };
      return inner.waitForSlot(placement, options);
    },

    /** A probe placement holds a LOCAL lease: there is no broker to release it to. */
    async release(placement, ok = true) {
      if (placement?.leaseSource === 'local') {
        return { skipped: 'placed by direct probe: the lease was local and there is no broker to release it to' };
      }
      if (typeof inner.release !== 'function') return { skipped: 'the inner placer has no release' };
      return inner.release(placement, ok);
    },

    transportFor(placement) {
      return inner.transportFor(placement);
    },
  };
}
