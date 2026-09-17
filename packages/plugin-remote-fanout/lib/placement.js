/**
 * Placement: turn "run a child somewhere" into "run THIS child on THIS node,
 * holding THIS lease", and make every step of that visible.
 *
 * THE DEFECT THIS REPLACES
 * Until now the provider's target was one row in a profile:
 * `target: !!js "process.env.MESH_TARGET_NODE ?? 'desktop-ts'"`. One node, named
 * in a configuration file, for every child of every session in the engine. The
 * owner intends to open ten windows with several agents each — on the order of
 * 55 concurrent agents — and with a fixed target all 55 land on one machine
 * while the other three idle. The row's own comment said it: *"choosing BETWEEN
 * nodes is the broker's decision, not a row's"*. This module is where that
 * decision is actually asked for.
 *
 * ONE PLACEMENT PER CHILD, AND WHY IT IS PER CHILD
 * The broker's `/place` issues a TTL'd lease and counts accepted jobs on the
 * node it names. Placing once per child is what makes that count true: the
 * second child of a fan-out sees the first child's lease, and once the node with
 * the most free slots is no longer the best answer the next child goes
 * elsewhere. A single reservation for a whole fan-out would be one number for
 * many processes and would be wrong the moment one of them died.
 *
 * WHAT PLACEMENT MUST NOT DO
 *   * It must not fall back to a fixed node. A broker that cannot be reached is
 *     a reported `broker-unreachable` error, not a default.
 *   * It must not pretend a queued child is a running one. `position > 0` means
 *     the child has NOT started; the run is not published to `ctx.subagents`
 *     while it waits, so nothing can show it as a running agent, and the wait is
 *     recorded in three places a human can read (the ledger file, the engine
 *     log, and the child's own report when it finally runs).
 *   * It must not invent a placement policy the broker does not have. The broker
 *     ranks candidates and names ONE winner. This module asks per child, once.
 *     It does not round-robin, does not exclude a node because a sibling used
 *     it, and does not second-guess the ranking — see `docs/mesh/92-provider-placement.md`
 *     §5 for what that means for a two-child fan-out, measured.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';

import { BrokerError, BROKER_UNREACHABLE } from './broker-client.js';
import { hostMatchesNode, invocationForNode, isHostToken, NODES, nodeNames } from './nodes.js';
import { createSshTransport, DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_MS } from './ssh-transport.js';

/** The node the broker named is not one this package can turn into a destination. */
export const PLACEMENT_NODE_UNKNOWN = 'placement-node-unknown';

/** Where the engine's placement records live, under the home the engine was started with. */
export function defaultLedgerDir(env = process.env) {
  const home = typeof env.DSH_HOME === 'string' && env.DSH_HOME.trim() !== ''
    ? env.DSH_HOME
    : path.join(homedir(), '.dsh');
  return path.join(home, 'mesh', 'placements');
}

/**
 * The durable record of every placement this engine makes: one small JSON file
 * per child under `<DSH_HOME>/mesh/placements/`, rewritten as the run moves.
 *
 * WHY A FILE AND NOT JUST A LOG LINE
 * In the `web` profile a host-plane plugin's `ctx.logger.info` goes nowhere
 * durable (`docs/mesh/90-provider-mount.md` §8.2, measured). A queue position
 * that only exists in a log nobody keeps is a queue position nobody can see —
 * which is exactly the failure the owner would feel and never find. So the
 * record is a file, rewritten at each transition, readable while the child is
 * still waiting.
 *
 * A ledger failure never fails a child: it is recorded and reported, because a
 * bookkeeping problem must not become a lost turn.
 */
export function createPlacementLedger({ dir = defaultLedgerDir(), logger, fs = { mkdirSync, writeFileSync } } = {}) {
  const records = new Map();
  let broken;

  function write(id, record) {
    const file = path.join(dir, `${id}.json`);
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(file, `${JSON.stringify(record, null, 2)}\n`, 'utf8');
      return { ok: true, file };
    } catch (error) {
      const message = String(error?.message ?? error);
      if (broken !== message) {
        broken = message;
        logger?.warn?.(`remote-fanout: the placement ledger could not be written to ${dir} (${message}); placements continue and are reported in the child's own result`);
      }
      return { ok: false, file, error: message };
    }
  }

  return {
    dir,
    /** Merge `patch` into this run's record and write it. Never throws. */
    record(id, patch) {
      const previous = records.get(id) ?? { id, at: new Date().toISOString() };
      const record = { ...previous, ...patch };
      records.set(id, record);
      return write(id, record);
    },
    /** The record as last written (for tests and for the report). */
    get(id) {
      return records.get(id);
    },
    fileFor(id) {
      return path.join(dir, `${id}.json`);
    },
  };
}

/** A placer for an explicit, hand-set fixed target — the opt-in fallback, never the default. */
export function createFixedPlacer({ transport, remote = {}, targetHosts = [], node, reason = 'MESH_TARGET_NODE was set by hand' } = {}) {
  const hosts = (Array.isArray(targetHosts) ? targetHosts : []).map(String).filter((value) => value !== '');
  const label = node ?? targetHosts[0] ?? 'the configured target';
  return {
    kind: 'fixed',
    describe: () => transport.describe(),
    explain: () => `FIXED TARGET "${label}" — the placement broker was NOT consulted (${reason})`,
    async acquire() {
      return {
        source: 'fixed',
        node: label,
        ssh: undefined,
        hosts,
        position: 0,
        lease: undefined,
        tier: null,
        score: null,
        rationale: [],
        at: new Date().toISOString(),
        facts: {
          command: remote.command,
          credentialEnvFiles: remote.credentialEnvFiles,
          nodeExe: remote.nodeExe,
          dshBin: remote.dshBin,
          profile: remote.profile ?? 'headless',
          dshHome: remote.dshHome,
          cwd: remote.cwd,
          shell: remote.shell === 'posix' ? 'posix' : 'powershell',
        },
      };
    },
    async waitForSlot() {
      return { waited: false, waitedMs: 0, polls: [] };
    },
    transportFor: () => transport,
    async release() {
      return { released: false, skipped: 'no lease: this provider is on a fixed target' };
    },
  };
}

/** The placer that asks the live broker. */
export function createNodePlacer({
  broker,
  nodes = NODES,
  logger,
  ledger,
  remoteProfile = 'headless',
  remoteHome,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  maxOutputBytes = DEFAULT_MAX_OUTPUT_BYTES,
  sshExe = 'ssh',
  sshArgs = [],
  queueWaitMs = 120_000,
  queuePollMs = 5_000,
  children = 1,
  prefer = null,
  exclude = [],
  now = () => Date.now(),
  // NOT unref'd, deliberately, and this was measured: a queue wait is often the
  // only thing a process has left to wait for, and an unref'd timer lets Node
  // exit out of the middle of the wait. Measured 2026-09-17 in
  // `bin/mesh-placement-proof.mjs`: the child was placed at position 1, the
  // "QUEUED at position 1" line was logged, and then the process ended with
  // "Detected unsettled top-level await" — a wait that never dispatched, which
  // is the exact silent-wait failure this feature exists to remove.
  sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); }),
  createTransport = createSshTransport,
} = {}) {
  if (broker === undefined || typeof broker.place !== 'function') {
    throw new Error('remote-fanout: a node placer needs a broker client with place()');
  }
  const transports = new Map();
  const wait = Number.isFinite(queueWaitMs) && queueWaitMs >= 0 ? queueWaitMs : 120_000;
  const poll = Number.isFinite(queuePollMs) && queuePollMs > 0 ? queuePollMs : 5_000;

  function transportFor(placement) {
    if (transports.has(placement.node)) return transports.get(placement.node);
    const transport = createTransport({
      sshExe,
      sshArgs,
      target: placement.ssh,
      timeoutMs,
      maxOutputBytes,
    });
    transports.set(placement.node, transport);
    return transport;
  }

  return {
    kind: 'broker',
    describe: () => broker.describe?.() ?? 'broker',
    explain: () => `placed by ${broker.describe?.() ?? 'the broker'} — one placement per child`,

    /**
     * Ask where the child should run. Throws `BrokerError` when the broker
     * cannot be asked; never returns a default node.
     */
    async acquire({ id, childIndex } = {}) {
      const at = now();
      const placement = await broker.place({ kind: 'oneShot', children, worktreeGiB: 0, prefer, exclude });
      const facts = nodes[placement.node];
      if (facts === undefined) {
        throw new BrokerError(
          PLACEMENT_NODE_UNKNOWN,
          `the broker named node "${placement.node}", which is not in this package's node table (${nodeNames().join(', ')}) — refusing to dispatch into a lookup miss`,
          { node: placement.node, known: nodeNames() },
        );
      }
      const record = {
        source: 'broker',
        id,
        childIndex,
        node: placement.node,
        ssh: facts.ssh,
        hosts: facts.hosts,
        position: placement.position,
        tier: placement.tier,
        score: placement.score,
        eligible: placement.eligible,
        blockedBy: placement.blockedBy,
        lease: placement.lease,
        leaseTtlSec: placement.leaseTtlSec,
        expiresAt: placement.expiresAt,
        rationale: placement.rationale,
        queue: placement.queue,
        placedAt: new Date(at).toISOString(),
        brokerAt: placement.at,
        brokerCallMs: placement.ms,
        state: placement.position > 0 ? 'queued' : 'placed',
        facts: {
          command: facts.command,
          credentialEnvFiles: facts.credentialEnvFiles,
          driver: facts.driver,
          bin: facts.bin,
          profile: remoteProfile,
          dshHome: remoteHome,
          cwd: facts.cwd,
          shell: facts.shell,
        },
        // WHICH INVOCATION THIS PLACEMENT WILL USE, on the record, before the
        // dispatch. A placement that names a node is not a placement that can
        // run on it, and the difference used to be invisible until a child died
        // (docs/mesh/102-linux-dispatch.md §1).
        invocation: invocationForNode(placement.node),
        nodeVerified: facts.verified,
      };
      ledger?.record(id, record);
      logger?.info?.(
        `remote-fanout: child ${id} placed on "${placement.node}" (${facts.ssh}) by the broker — `
        + `position ${placement.position}, score ${placement.score ?? '?'}, tier ${placement.tier ?? '?'}, lease ${placement.lease}`,
      );
      return record;
    },

    /**
     * Wait for a queued placement to become startable. The wait is BOUNDED, and
     * when the bound expires the child is dispatched anyway: the broker's own
     * rule is queue, never amputate, and a caller that gave up on a queued child
     * would be refusing work the mesh never refused.
     *
     * The wait is observable at every step: `onWait` is called with the queue
     * position the moment it is known, and with each poll's reading of the node.
     */
    async waitForSlot(placement, { signal, onWait } = {}) {
      const started = now();
      if (!(placement.position > 0)) return { waited: false, waitedMs: 0, polls: [] };
      onWait?.({ phase: 'queued', node: placement.node, position: placement.position, queue: placement.queue, lease: placement.lease });
      const deadline = started + wait;
      const polls = [];
      let freed;
      let lastError;
      while (now() < deadline) {
        if (signal?.aborted) break;
        const remaining = deadline - now();
        await sleep(Math.min(poll, Math.max(1, remaining)));
        if (signal?.aborted) break;
        let report;
        try {
          report = await broker.nodes({ fresh: true });
        } catch (error) {
          lastError = { code: error?.code ?? 'broker-error', message: String(error?.message ?? error) };
          polls.push({ at: new Date(now()).toISOString(), error: lastError.code });
          onWait?.({ phase: 'queued-poll', node: placement.node, error: lastError.code, waitedMs: now() - started });
          continue;
        }
        const row = report.nodes.find((candidate) => candidate.node === placement.node);
        const freeSlots = Number.isFinite(row?.freeSlots) ? row.freeSlots : null;
        const observation = {
          at: new Date(now()).toISOString(),
          node: placement.node,
          state: row?.state ?? 'unknown',
          freeSlots,
          brokerLeases: row?.brokerLeases ?? null,
          waitedMs: now() - started,
        };
        polls.push(observation);
        onWait?.({ phase: 'queued-poll', ...observation });
        if (freeSlots !== null && freeSlots >= children) {
          freed = observation;
          break;
        }
      }
      const waitedMs = now() - started;
      const result = {
        waited: true,
        waitedMs,
        polls,
        freedAt: freed?.at ?? null,
        timedOut: freed === undefined,
        aborted: signal?.aborted === true,
        lastError: lastError ?? null,
      };
      onWait?.({
        phase: freed === undefined ? 'queued-expired' : 'queued-released',
        node: placement.node,
        position: placement.position,
        waitedMs,
        startedAt: freed?.at ?? null,
        note: freed === undefined
          ? `no free slot appeared within ${wait} ms; dispatching anyway (queue, never amputate)`
          : `a free slot appeared after ${waitedMs} ms`,
      });
      return result;
    },

    transportFor,
    async release(placement, ok) {
      if (placement?.lease === undefined || placement.lease === null || placement.lease === '') {
        return { released: false, skipped: 'the placement carried no lease' };
      }
      try {
        const answer = await broker.done(placement.lease, ok !== false);
        logger?.info?.(`remote-fanout: lease ${placement.lease} on "${placement.node}" released (${JSON.stringify(answer?.released ?? answer)})`);
        return { ok: true, ...answer };
      } catch (error) {
        logger?.warn?.(`remote-fanout: the lease ${placement.lease} on "${placement.node}" could not be released (${error?.code ?? 'broker-error'}: ${String(error?.message ?? error)}); the broker reclaims it at its TTL`);
        return { ok: false, code: error?.code ?? 'broker-error', error: String(error?.message ?? error) };
      }
    },
  };
}

export { BrokerError, BROKER_UNREACHABLE, hostMatchesNode, isHostToken };
