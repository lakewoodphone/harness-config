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
import {
  decidePressure,
  describePressure,
  localNodeName,
  sharedPressureReader,
  HIGH_COMMIT_PHYSICAL_PCT,
  PREFER_REMOTE_DEFAULT,
} from './pressure.js';
import { createSshTransport, DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_MS } from './ssh-transport.js';

/** The node the broker named is not one this package can turn into a destination. */
export const PLACEMENT_NODE_UNKNOWN = 'placement-node-unknown';

/**
 * THE REFUSAL (`docs/mesh/109-pressure-routing.md` §3).
 *
 * The mesh cannot be reached AND this machine is above its critical commit line
 * — no node to put the child on and no room to keep it. Nothing is dispatched,
 * and this error says so in as many words.
 */
export const MESH_UNAVAILABLE_LOCAL_SATURATED = 'mesh-unavailable-local-saturated';

/**
 * The mesh IS reachable and this machine is above its critical commit line, so
 * the child must not run HERE. The message says which node to use instead
 * wherever the broker named one; it never becomes a fallback dispatch.
 */
export const LOCAL_PRESSURE_REFUSED = 'local-pressure-refused';

/** A child could not be placed because this machine has no room for it. */
export class PressureRefusalError extends Error {
  /**
   * @param {string} code `mesh-unavailable-local-saturated` | `local-pressure-refused`
   * @param {string} message the text a caller reports, naming the reading and the alternative
   * @param {object} detail evidence: the reading in full, the decision, the intended node
   */
  constructor(code, message, detail = {}) {
    super(message);
    this.name = 'PressureRefusalError';
    this.code = code;
    this.detail = detail;
  }
}

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
  /**
   * THE `prefer-remote` POLICY, OFF BY DEFAULT (`PREFER_REMOTE_DEFAULT`). When
   * it is on, a placement that would land on THIS machine is released unspent
   * and the ask is repeated with this machine excluded - but only when the
   * broker's own answer shows at least one eligible node other than it. See
   * `alternativeEligibility` in `lib/pressure.js`. A POLICY and not a sensor:
   * nothing here measures whether a human is using the machine, because nothing
   * in this package can.
   */
  preferRemote = PREFER_REMOTE_DEFAULT,
  now = () => Date.now(),
  // ── LOCAL PRESSURE (docs/mesh/109-pressure-routing.md) ────────────────────
  // The reader is injectable so a test can hand the placer a reading, and so a
  // deployment can point it at another snapshot file. Absent, it is the shared
  // one-per-process reader, which reads `plugin-health`'s snapshot off disk and
  // spawns nothing on the normal path.
  pressureReader = sharedPressureReader(),
  /** `undefined` derives it from this machine's own hostname. */
  localNode = undefined,
  /** What the engine's own session census says. Absent = the count is reported null. */
  agentsRunning = () => undefined,
  /**
   * An optional, BOUNDED probe of whether the mesh can be reached at all. It is
   * consulted only on the refusal path, where the answer changes the error the
   * caller sees: "this machine is full and there is nowhere else" is a different
   * instruction to an agent than "this machine is full".
   */
  meshCheck = undefined,
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
  /** This machine's name in the broker's vocabulary — resolved once, at construction. */
  const thisNode = localNode === undefined ? localNodeName() : localNode;
  const readPressure = typeof pressureReader?.read === 'function' ? () => pressureReader.read() : () => undefined;

  /** Decorate a reading with the engine's live agent census, if the caller gave one. */
  function measuredPressure() {
    const reading = readPressure();
    if (reading === undefined) return undefined;
    try {
      const agents = agentsRunning();
      if (Number.isFinite(agents)) reading.agentsRunning = agents;
    } catch {
      // A census that throws must not turn a reading into a throw; the field
      // stays null and the report says so.
    }
    return reading;
  }

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
     *
     * AND BEFORE ASKING, READ THIS MACHINE (docs/mesh/109-pressure-routing.md).
     * A saturated laptop must OFFER its work to the mesh rather than wait to be
     * asked to: the broker places what it is offered, so a dispatcher that
     * offers everything while its own machine is full is the reason the mesh sat
     * idle on 2026-09-17. Three things happen here, in this order:
     *
     *   1. The reading is taken and recorded — always, whatever it says.
     *   2. At or above the high line the local node is added to the broker's
     *      `exclude` hint, so the mesh is asked to take the child. `exclude` is a
     *      soft hint by the broker's own rule (`broker.js`: the caller's
     *      exclusion yields when it is the only option), so this cannot make the
     *      mesh refuse work it would otherwise take.
     *   3. Above the critical line — commit at or above 92 % of physical AND less
     *      than 1.5 GiB physical memory available — a LOCAL placement is refused.
     *      If the broker cannot be reached at all, the refusal happens instead of
     *      the call: mesh unreachable plus machine saturated has no good answer,
     *      and piling the child on is the worst one.
     */
    async acquire({ id, childIndex, excludeNodes = [] } = {}) {
      const at = now();
      // Nodes this dispatch must not be sent to again — a reroute's explicit list. It is
      // SEPARATE from the `exclude` hint on purpose: `exclude` expresses a preference,
      // while `excludeNodes` says "this node already failed this child". Both are SOFT at
      // the broker (see `mesh-broker/lib/broker.js`), so a list naming every node still
      // yields to queue-never-amputate rather than refusing to place at all.
      const rerouteExclude = Array.isArray(excludeNodes)
        ? excludeNodes.filter((name) => typeof name === 'string' && name !== '')
        : [];
      const reading = measuredPressure();
      const localIsDispatchable = thisNode !== undefined && NODES[thisNode] !== undefined;
      // The pre-call verdict has no broker outcome yet, so `brokerReachable` is
      // left unset: at this point the mesh is presumed available, and the
      // refusal for "unreachable AND saturated" is decided in the catch below.
      const preDecision = decidePressure(reading, { localNode: thisNode ?? null });
      const routeAway = preDecision.routeAwayFromLocal === true && localIsDispatchable;
      const askedExclude = routeAway ? [...new Set([...exclude, thisNode])] : exclude;

      /**
       * THE REFUSAL, BEFORE THE BROKER IS ASKED.
       *
       * Above the critical line the local option is not available, and a
       * dispatch that reached the transport would run the child HERE. So it is
       * refused before `POST /place`: no ssh is spent, and — the part that
       * matters — no lease is issued that this process would then strand for its
       * 900 s TTL by not dispatching.
       *
       * The message names the reading, both lines it crossed, and what to do
       * instead. `test/pressure.test.mjs` asserts the broker is never called.
       */
      if (preDecision.refuse === true) {
        let refused = preDecision;
        // One bounded question, answered only because we are already refusing.
        // This is the case the brief asks to decide explicitly, so the decision
        // is stated in the error rather than left implied.
        if (typeof meshCheck === 'function') {
          let reachable;
          let why;
          try {
            reachable = await meshCheck();
          } catch (error) {
            reachable = false;
            why = error?.code ?? 'broker-error';
          }
          if (reachable === false) {
            refused = decidePressure(reading, { localNode: thisNode ?? null, brokerReachable: false, brokerError: why });
          }
        }
        ledger?.record(id, {
          id,
          state: 'pressure-refused',
          code: refused.meshUnavailable ? MESH_UNAVAILABLE_LOCAL_SATURATED : LOCAL_PRESSURE_REFUSED,
          pressure: reading ?? null,
          pressureDecision: { ...refused, localNode: thisNode ?? null, excludedLocalNode: false, excludeSentToBroker: [], placedLocally: false },
          pressureLine: describePressure(reading, refused),
          refusedAt: new Date(at).toISOString(),
        });
        logger?.warn?.(`remote-fanout: child ${id} REFUSED before the broker was asked — ${refused.reason}`);
        throw new PressureRefusalError(
          refused.meshUnavailable ? MESH_UNAVAILABLE_LOCAL_SATURATED : LOCAL_PRESSURE_REFUSED,
          `${refused.reason}; nothing was dispatched and no reservation was taken. Retry when this machine is under its high line`
          + ` (${Math.round(HIGH_COMMIT_PHYSICAL_PCT * 100)} % of physical committed, docs/mesh/109-pressure-routing.md)`,
          { pressure: reading ?? null, decision: refused },
        );
      }

      let placement;
      try {
        placement = await broker.place({ kind: 'oneShot', children, worktreeGiB: 0, prefer, exclude: askedExclude, excludeNodes: rerouteExclude });
      } catch (error) {
        // THE CASE WITH NO GOOD ANSWER, DECIDED EXPLICITLY. The mesh cannot be
        // asked and this machine is over its critical line. Refusing is the
        // answer: the alternative is to dispatch a child this machine has no
        // measured room for, which spends a real model turn to make the engine's
        // own loop lag worse for every window the owner has open. Recorded, then
        // re-thrown as a refusal that names both halves.
        if (preDecision.refuse === true && preDecision.decision === 'refuse-local') {
          const refused = decidePressure(reading, { localNode: thisNode ?? null, brokerReachable: false, brokerError: error?.code ?? 'broker-error' });
          ledger?.record(id, {
            id,
            state: 'pressure-refused',
            code: MESH_UNAVAILABLE_LOCAL_SATURATED,
            pressure: reading ?? null,
            pressureDecision: refused,
            pressureLine: describePressure(reading, refused),
            brokerError: String(error?.message ?? error),
            refusedAt: new Date(at).toISOString(),
          });
          logger?.warn?.(`remote-fanout: child ${id} REFUSED — ${refused.reason}`);
          throw new PressureRefusalError(MESH_UNAVAILABLE_LOCAL_SATURATED, `${refused.reason}; retry when the mesh answers again, or when this machine is under its high line again`, {
            pressure: reading ?? null,
            decision: refused,
            cause: { code: error?.code ?? 'broker-error', message: String(error?.message ?? error) },
          });
        }
        throw error;
      }

      // ── THE prefer-remote POLICY, EVALUATED ON THE BROKER'S OWN ANSWER ─────
      // The policy needs the eligible set, and the only source of it is the
      // answer the broker just gave. So the first ask is exactly the ask this
      // code made before the policy existed (`askedExclude` carries the
      // caller's own hint and nothing else below the high line), and the policy
      // is applied to what came back:
      //
      //   * the broker named another node - the policy is already satisfied, no
      //     second call, and the reason says the exclusion was not needed;
      //   * the broker named THIS machine while its own eligible set held at
      //     least one other node - the local reservation is released UNSPENT
      //     and the ask is repeated with this node excluded, so the child is
      //     offered to the mesh instead of being kept here.
      //
      // When the eligible set cannot be read from the answer (`tier: 'queued'`
      // builds its pool from every placeable node, and a broker reporting no
      // `eligible` cannot say either), nothing is re-asked, the answer stands,
      // and the reason records that the set could not be determined. A reading
      // that could not be made must never change a decision.
      let askedExcludeFinal = askedExclude;
      let supersededLease = null;
      let policyNote = null;
      let policyDecision = null;
      if (preferRemote === true && preDecision.decision === 'ok' && thisNode !== undefined) {
        const firstDecision = decidePressure(reading, {
          localNode: thisNode,
          brokerReachable: true,
          preferRemote: true,
          placement,
        });
        if (firstDecision.routeAwayFromLocal === true && placement.node === thisNode) {
          // Give the reservation back BEFORE the second ask: the broker counts
          // accepted leases on the node it named, and a lease this process will
          // never dispatch would make the next child's ranking wrong for its
          // whole TTL. A release that fails is recorded and NOT raised - the
          // broker reclaims the lease at its TTL anyway.
          try {
            const released = await broker.done(placement.lease, false);
            supersededLease = { lease: placement.lease, node: placement.node, reconsidered: true, released: released?.released ?? null };
          } catch (error) {
            supersededLease = { lease: placement.lease, node: placement.node, reconsidered: true, released: false, error: String(error?.message ?? error) };
            logger?.warn?.(`remote-fanout: the prefer-remote policy could not release the local reservation ${placement.lease} (${error?.code ?? 'broker-error'}: ${String(error?.message ?? error)}); the broker reclaims it at its TTL`);
          }
          askedExcludeFinal = [...new Set([...exclude, thisNode])];
          placement = await broker.place({ kind: 'oneShot', children, worktreeGiB: 0, prefer, exclude: askedExcludeFinal, excludeNodes: rerouteExclude });
          policyDecision = firstDecision;
          policyNote = `prefer-remote: the first answer placed this child on THIS machine while the broker's own eligible set held ${firstDecision.eligible?.alternatives ?? '?'} node(s) other than it; that reservation was released unspent and the local node was excluded from the second ask`;
          logger?.info?.(`remote-fanout: child ${id} ${policyNote}`);
        } else {
          policyNote = `prefer-remote: no exclusion was sent by the policy - ${firstDecision.reason}`;
        }
      }

      const facts = nodes[placement.node];
      if (facts === undefined) {
        throw new BrokerError(
          PLACEMENT_NODE_UNKNOWN,
          `the broker named node "${placement.node}", which is not in this package's node table (${nodeNames().join(', ')}) — refusing to dispatch into a lookup miss`,
          { node: placement.node, known: nodeNames() },
        );
      }

      /**
       * THE BROKER NAMED THIS MACHINE, AND PRESSURE SAYS IT HAS NO ROOM.
       *
       * A refusal here would strand the lease the broker just issued (its TTL is
       * 900 s), so this does not refuse. It dispatches and says so loudly: the
       * disagreement between the reading and the placement is the fact a reader
       * needs, and hiding it — either by silently overriding the broker or by
       * silently obeying it — is the failure this whole seam exists to prevent.
       * The broker's `rationale` explains why it chose what it chose.
       */
      const placedLocally = thisNode !== undefined && placement.node === thisNode;
      // WHAT WAS ACTUALLY SENT, not what was intended: the prefer-remote
      // policy's second ask can add this machine to the exclusion list after
      // the first answer, and the record must say what the broker was told.
      const localExcluded = thisNode !== undefined && askedExcludeFinal.includes(thisNode);
      const placedAgainstPressure = placedLocally && reading !== undefined && reading.band !== 'ok';
      // With a placement in hand the verdict is final: "saturated and
      // unreachable" cannot apply, because it was reached. When the policy
      // acted, the decision it acted on is the one on the record - it was made
      // on the FIRST answer, which is where the eligible set was read.
      const decision = policyDecision ?? decidePressure(reading, {
        localNode: thisNode ?? null,
        brokerReachable: true,
        preferRemote,
        placement,
      });
      const refusal = reading !== undefined && decision.refuse === true && placedLocally;
      const pressureLine = reading === undefined
        ? 'pressure NOT MEASURED — no reading was available, so this placement was decided exactly as it was before the check existed'
        : describePressure(reading, decision);
      const conflict = refusal
        ? `LOCAL PLACEMENT AGAINST PRESSURE — the broker named this machine ("${placement.node}") while the machine is above its critical line; the child runs here anyway (the broker's own rule is refuse-never: it placed, and a refused placement would strand the lease), and this line is the record of the disagreement`
        : placedAgainstPressure
          ? `the broker placed this child on THIS machine ("${placement.node}") while the machine is in the "${reading.band}" band; the local node was offered to the broker as excluded, and it was chosen anyway`
          : supersededLease !== null && placedLocally
            ? `PREFER-REMOTE YIELDED - the policy released the local reservation and asked again with this machine excluded, and the broker named it again ("${placement.node}"): the child runs here anyway, because the broker never refuses a placement, and this line is the record of the override`
            : undefined;

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
        // ── THE PRESSURE DECISION, ON THE RECORD ─────────────────────────────
        // Whatever it decided: the reading, the band, the decision, whether the
        // local node was offered as excluded, whether the broker chose local
        // anyway, and one line a human reads. A change of behaviour that is not
        // in this file did not happen.
        pressure: reading ?? null,
        pressureLine,
        preferRemote,
        pressureDecision: { ...decision, localNode: thisNode ?? null, excludedLocalNode: localExcluded, excludeSentToBroker: askedExcludeFinal, placedLocally },
        excludedLocalNode: localExcluded,
        excludeSentToBroker: askedExcludeFinal,
        placedLocally,
        ...(supersededLease === null ? {} : { supersededLease }),
        ...(policyNote === null ? {} : { preferRemoteNote: policyNote }),
        ...(conflict === undefined ? {} : { pressureConflict: conflict }),
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
      logger?.info?.(`remote-fanout: child ${id} pressure — ${pressureLine}`);
      if (reading !== undefined && (reading.band !== 'ok' || decision.decision !== 'ok')) {
        logger?.info?.(`remote-fanout: child ${id} pressure DECISION — ${decision.decision}: ${decision.reason}`);
      }
      if (conflict !== undefined) logger?.warn?.(`remote-fanout: child ${id} ${conflict}`);
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
