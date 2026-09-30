/**
 * The mesh broker (stream S5 of docs/mesh/71-mesh-program.md).
 *
 * WHAT IT IS
 * A decision service. It reads every node's `GET /mesh/capacity` (§2.1) through that node's
 * gate, with a short timeout, holds the readings in memory for at most 15 s, and answers
 * "where" from those live numbers. It stores no node state it can go stale on, and no verb
 * it exposes ever returns a refusal.
 *
 * WHY IT RE-READS INSTEAD OF BEING TOLD
 * `docs/mesh/66-dsh-remote-capability.md` §4: "DROP the federation, keep the surface ... the
 * placement service reads each candidate node's /healthz directly, over the tailnet, with a
 * bounded timeout; the authority stores only the decision. That removes the heartbeat, the
 * PUBLISH verb, the node-report column-add, and 15 seconds of staleness from every
 * decision." §5 of the program says the same: a heartbeat table of node state is explicitly
 * NOT built, because stale state is how this system has lied to itself before.
 *
 * THE THREE RULES THAT MAKE IT ROBUST, and where each lives in this file
 *  1. IT NEVER REFUSES. There is no `throw` and no error response on the placement path:
 *     every gate failure demotes a node to a later tier instead of emptying the result, and
 *     the last resort is `emergencyPlacement()` - an internal fault still returns a node and
 *     a position > 0 rather than a 5xx. Tiers S1..S6 below ARE that rule, written as code.
 *  2. IT STORES NOTHING IT CAN GO STALE ON. The only mutable state is `readings` (a Map of
 *     measurements with timestamps, 15 s TTL) and `leases` (live reservations with TTLs).
 *     No files, no tables, no last-known-good node state.
 *  3. EVERY DECISION IS EXPLAINABLE. `rationale` is the list of numbers the decision used -
 *     the frozen slot arithmetic verbatim, the disk gate, the load, BOTH score terms, the
 *     transport capability, the disk requirement term by term, whether the node was slow, the
 *     lease counts, the position arithmetic, and why each other candidate lost. A placement
 *     whose rationale is empty is a bug, and test/acceptance.test.mjs asserts it cannot happen.
 *
 * ONE STATE PER NODE, AND THE STATES ARE NOT INTERCHANGEABLE (requirements 3 and 4, 2026-09-17)
 * `ok` / `slow` / `unreachable` / `capacity-unreadable` / `absent`. A busy node is not a dead one,
 * and a node with a broken reader is not an offline machine: each calls for a different response,
 * and conflating them is how a mesh quietly loses a node. See docs/mesh/71-mesh-program.md §2.2
 * for the frozen wording and docs/mesh/76-broker.md §10 for the measurements behind it.
 *
 * A SLOW NODE IS RANKED, NOT REMOVED (fixed 2026-09-17, docs/mesh/98-broker-fixes.md §1). The
 * shipped code removed every `slow` node from the `fits` pool whenever any node answered first
 * time, so a node whose capacity read missed the deadline once received no work at all - measured
 * on the owner's own laptop, which alternates ok/slow/ok, while the desktop filled up. §10.8's
 * words were always "ranked below every node that answered first time and never refused"; the code
 * now does that, and the tiers below are `fits` / `highest-slots` / `transport` / `queued`.
 */

import { capacityUrl, readNodeCapacity, DEFAULT_READ_TIMEOUT_MS, RETRY_READ_TIMEOUT_MS } from './capacity.js';
import { createLeaseTable, DEFAULT_LEASE_TTL_MS } from './leases.js';
import {
  MAX_SLOTS,
  PER_CHILD_DISK_GIB,
  PER_SLOT_MIB,
  RESERVE_MIB,
  FLEET_DISK_FLOOR_GIB,
  PREFERENCE_BONUS,
  compareRanking,
  diskFreeGiB,
  diskRequirementGiB,
  effectiveSlots,
  normalizeChildren,
  normalizeExclude,
  normalizeKind,
  normalizePrefer,
  rankingKey,
  slotArithmetic,
} from './scoring.js';

export const DEFAULT_CACHE_TTL_MS = 15_000;
/** Cap on the response's rationale lines; the chosen node's arithmetic is always inside it. */
export const MAX_RATIONALE_LINES = 32;

const finite = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
/** A GiB number as a reader expects it: 17 GiB, 20.8 GiB, 220.4 GiB - never `17.0 GiB`. */
const gib = (value) => (Number.isInteger(value) ? String(value) : String(Math.round(value * 10) / 10));
const iso = (ms) => new Date(ms).toISOString();
const seconds = (ms) => Math.round(ms / 1000);
const messageOf = (error) => (error instanceof Error ? error.message : String(error));

/**
 * Normalize an untrusted request body into a task. A body that is missing, malformed or
 * nonsensical produces a usable one-shot task and a `note` explaining what was assumed -
 * never an error response (§2.2: "Never a refusal").
 */
export function normalizeTask(body) {
  const notes = [];
  let source = body;
  if (typeof body === 'string') {
    try {
      source = JSON.parse(body);
    } catch (error) {
      source = null;
      notes.push(`the request body was not valid JSON (${messageOf(error)}); assumed kind=oneShot children=1 - the broker never refuses a placement`);
    }
  } else if (body === undefined || body === null) {
    notes.push('the request had no body; assumed kind=oneShot children=1 - the broker never refuses a placement');
  }
  if (source !== null && (typeof source !== 'object' || Array.isArray(source))) {
    notes.push('the request body was not a JSON object; assumed kind=oneShot children=1');
    source = null;
  }
  const rawTask = source !== null && typeof source.task === 'object' && source.task !== null && !Array.isArray(source.task)
    ? source.task
    : null;
  if (rawTask === null) {
    if (source !== null) notes.push('the body had no {"task":{...}} object; assumed kind=oneShot children=1');
  }
  const raw = rawTask ?? {};
  const kind = normalizeKind(raw.kind);
  if (raw.kind !== undefined && raw.kind !== 'fleet' && raw.kind !== 'oneShot') {
    notes.push(`task.kind ${JSON.stringify(raw.kind)} is not "oneShot"|"fleet"; treated as oneShot`);
  }
  const children = normalizeChildren(raw.children);
  if (raw.children !== undefined && children !== raw.children) {
    notes.push(`task.children ${JSON.stringify(raw.children)} is not a positive integer; treated as ${children}`);
  }
  const prefer = normalizePrefer(raw.prefer);
  if (raw.prefer !== undefined && raw.prefer !== null && prefer === null) {
    notes.push(`task.prefer ${JSON.stringify(raw.prefer)} is not "home"|"office"|null; ignored`);
  }
  const exclude = normalizeExclude(raw.exclude);
  if (raw.exclude !== undefined && exclude.length !== (Array.isArray(raw.exclude) ? raw.exclude.length : 0)) {
    notes.push('task.exclude entries that were not non-empty strings were ignored');
  }
  const worktreeGiB = finite(raw.worktreeGiB);
  return { task: { kind, children, prefer, exclude, worktreeGiB }, notes };
}

/**
 * Create the broker. Nothing here is async and nothing touches the network until a call.
 *
 * @param {object} options
 * @param {Array<object>} options.nodes            the roster (see lib/config.js)
 * @param {number} [options.cacheTtlMs]            readings are reused for at most this long (15000)
 * @param {number} [options.readTimeoutMs]         per-node read timeout (1500)
 * @param {number} [options.retryTimeoutMs]        the ONE retry's budget when a read times out (scales from readTimeoutMs: 1500 -> 4000)
 * @param {number} [options.leaseTtlMs]            lease TTL (900000)
 * @param {Function} [options.readCapacity]        injectable reader, for tests
 * @param {() => number} [options.now]             injectable clock, for tests
 */
export function createBroker(options = {}) {
  const nodes = Array.isArray(options.nodes) ? options.nodes : [];
  if (nodes.length === 0) {
    throw new Error('mesh-broker: a roster with at least one node is required (see lib/config.js)');
  }
  const cacheTtlMs = Number.isFinite(options.cacheTtlMs) && options.cacheTtlMs > 0 ? options.cacheTtlMs : DEFAULT_CACHE_TTL_MS;
  const readTimeoutMs = Number.isFinite(options.readTimeoutMs) && options.readTimeoutMs > 0 ? options.readTimeoutMs : DEFAULT_READ_TIMEOUT_MS;
  // A timeout gets ONE retry, at a longer budget, so "busy" and "gone" stop looking alike.
  // The budget scales from the caller's own deadline unless they name one, so a tight bound
  // stays tight: 1500 -> 4000 (the shipping pair, 4000 being the measured Mac Mini latency),
  // 300 -> 1200 (the tests).
  const retryTimeoutMs = Number.isFinite(options.retryTimeoutMs) && options.retryTimeoutMs > 0
    ? options.retryTimeoutMs
    : Math.min(RETRY_READ_TIMEOUT_MS, Math.max(1000, Math.round(readTimeoutMs * 4)));
  const leaseTtlMs = Number.isFinite(options.leaseTtlMs) && options.leaseTtlMs > 0 ? options.leaseTtlMs : DEFAULT_LEASE_TTL_MS;
  const now = typeof options.now === 'function' ? options.now : () => Date.now();
  const readCapacity = typeof options.readCapacity === 'function' ? options.readCapacity : readNodeCapacity;
  const leases = createLeaseTable({ ttlMs: leaseTtlMs, now });
  const startedAt = now();

  /** @type {Map<string, {at:number, ok:boolean, doc:any|null, error:string|null, status:number|null, latencyMs:number|null, url:string, attempts:number, lastOkAt:number|null, reportedNode:string|null, note:string|null}>} */
  const readings = new Map();
  /** @type {Map<string, Promise<object>>} single-flight, so 30 concurrent calls cost 1 read per node */
  const inflight = new Map();
  let reads = 0;
  let readFailures = 0;
  /**
   * When the broker first saw each configured-but-unread node, and whether it has EVER
   * answered. Nothing is stored about a node that works; this exists only so a node that is
   * configured and has never answered can be reported as `absent` with an honest age rather
   * than called `unreachable`, which would be a false claim about reachability.
   *
   * APPROVED 2026-09-17 (amendment 5) as the §2.2 `absent` state. It is inert on the current
   * four-node roster, where every node has answered; it exists for the elastic tier, whose
   * roster rows will be configured before they are provisioned. The `volatile` marker and the
   * provisioner that would use them are NOT built (docs/mesh/76-broker.md §10.7).
   */
  const baselines = new Map();

  function ageOf(entry, at) {
    return entry === undefined ? null : Math.max(0, Math.round((at - entry.at) / 1000));
  }

  /** First sighting of a node's CURRENT configuration (a changed baseUrl is a different node). */
  function baselineOf(node, at) {
    const signature = `${node.baseUrl}|${node.fqdn ?? ''}`;
    let baseline = baselines.get(node.node);
    if (baseline === undefined || baseline.signature !== signature) {
      baseline = { configuredAt: at, everAnswered: false, signature };
      baselines.set(node.node, baseline);
    }
    return baseline;
  }

  /**
   * A node is ABSENT when it is in the roster, its configuration is known, and it has NEVER
   * ANSWERED - not on this read and not on any read since the broker started. That is a
   * different fact from unreachable: a failed attempt says the network did not deliver, and an
   * absence says the node has no network history at all, which is what a configured-but-not-yet
   * -provisioned row looks like. The distinction is the whole point: calling such a node
   * "unreachable" is a false claim about reachability.
   */
  function isAbsent(node) {
    return node.volatile === true && baselineOf(node, now()).everAnswered === false;
  }

  /** Read one node, unless the same node is already being read by another caller. */
  function readOne(node) {
    const existing = inflight.get(node.node);
    if (existing !== undefined) return existing;
    const promise = (async () => {
      const previous = readings.get(node.node);
      let result;
      try {
        result = await readCapacity({ node, timeoutMs: readTimeoutMs, retryTimeoutMs });
      } catch (error) {
        result = { ok: false, error: `the capacity reader threw: ${messageOf(error)}` };
      }
      reads += 1;
      const at = now();
      const ok = result?.ok === true;
      if (!ok) readFailures += 1;
      if (ok) {
        const baseline = baselineOf(node, at);
        baseline.everAnswered = true;
      }
      const entry = {
        at,
        ok,
        // A capacity-unreadable node keeps the DOCUMENT it sent, so /nodes can show what the
        // broken reader actually produced. Any other failure keeps the last document that
        // parsed, which is what `staleReading` is for.
        doc: ok
          ? result.doc
          : (result?.state === 'capacity-unreadable' && result.doc !== null && result.doc !== undefined
            ? result.doc
            : (previous?.doc ?? null)),
        error: ok ? null : (result?.error ?? 'unknown error'),
        /** `timeout`/`refused`/`dns`/`reset`/`never-answers`/`other` - the KIND of failure. */
        errorKind: ok ? null : (result?.errorKind ?? 'other'),
        /** `ok`/`slow`/`capacity-unreadable`/`unreachable`/`absent` - what the broker will say. */
        state: ok ? (result?.state ?? 'ok') : (result?.state ?? 'unreachable'),
        /** The retry pairing: whether a first timeout was followed by a longer second attempt. */
        retried: result?.retried === true,
        retryWasFast: result?.retryWasFast === true,
        firstLatencyMs: Number.isFinite(result?.firstLatencyMs) ? result.firstLatencyMs : null,
        elapsedMs: Number.isFinite(result?.elapsedMs) ? result.elapsedMs : null,
        reason: ok ? null : (result?.reason ?? null),
        status: result?.status ?? null,
        latencyMs: Number.isFinite(result?.latencyMs) ? result.latencyMs : null,
        url: result?.url ?? capacityUrl(node),
        attempts: (previous?.attempts ?? 0) + 1,
        lastOkAt: ok ? at : (previous?.lastOkAt ?? null),
        reportedNode: ok ? (result.doc?.node ?? null) : (previous?.reportedNode ?? null),
        note: result?.note ?? null,
      };
      readings.set(node.node, entry);
      return entry;
    })();
    inflight.set(node.node, promise);
    return promise.finally(() => inflight.delete(node.node));
  }

  /** Re-read every node whose reading is older than the cache TTL, in parallel. Never throws. */
  async function refresh({ fresh = false } = {}) {
    const at = now();
    const pending = nodes.filter((node) => {
      const cached = readings.get(node.node);
      return fresh || cached === undefined || at - cached.at >= cacheTtlMs;
    });
    if (pending.length > 0) {
      await Promise.all(pending.map((node) => readOne(node).catch(() => undefined)));
    }
    return now();
  }

  /**
   * Every number the decision is allowed to use, for one node.
   *
   * Note the deliberate asymmetry for an unreachable node: `accepts` is treated as UNKNOWN
   * (not as a refusal) because §2.1 says a missing measurement is not a restriction, but the
   * disk gate is treated as NOT PASSED, because a node we cannot see must never be told to
   * start a fleet. Either way it can only ever end up queued, never "start now".
   */
  function evaluate(node, task, at) {
    const entry = readings.get(node.node);
    const reachable = entry !== undefined && entry.ok === true;
    // Amendment 5: a node that has NEVER answered is `absent`, not `unreachable`. It carries
    // no latency and no reading, it is excluded from the ranking, and its age is measured from
    // when its configuration was seen rather than from a last reading that never happened.
    const absent = isAbsent(node);
    const baseline = baselineOf(node, at);
    // ONE STATE, NAMED (requirements 3 and 4). These are mutually exclusive and ordered, and
    // each says something different about the far side:
    //   absent              - configured, never answered since the broker started
    //   capacity-unreadable - answered, but what it sent is not a usable §2.1 document
    //   unreachable         - nothing answered: refused, DNS failure, or both attempts timed out
    //   slow               - it timed out once and answered on the longer second attempt
    //   ok                 - a normal reading
    // A slow node is ranked lower; an unreadable one and an unreachable one are not ranked at
    // all, but they are reported as the different facts they are.
    const state = reachable
      ? (entry?.state === 'slow' ? 'slow' : 'ok')
      : absent
        ? 'absent'
        : entry === undefined
          ? 'unread'
          : entry.state === 'capacity-unreadable'
            ? 'capacity-unreadable'
            : 'unreachable';
    const slow = reachable && entry?.state === 'slow';
    const doc = reachable ? entry.doc : null;
    const arith = slotArithmetic(doc);
    // The score is the EFFECTIVE slot count: the memory term capped by the core term, then
    // halved if the node is swapping. `arith.slots` already carries that (see scoring.js),
    // and it is recomputed once more here so the terms are named where the decision is made.
    const effective = effectiveSlots(arith);
    const onNode = leases.onNode(node.node, at);
    const running = onNode.filter((lease) => lease.state === 'running').length;
    const queued = onNode.filter((lease) => lease.state === 'queued').length;
    /**
     * ── THE PER-NODE CHILDREN CAP (measured, 2026-09-18) ──────────────────────
     * The machine's own slot arithmetic says what it could compute; it says nothing
     * about how many children it should carry at once. A five-child fan-out was placed
     * entirely on one node, its sshd handshake stretched from ~1.5 s to 8 s against a
     * 10 s dispatch timeout, and one child was lost to a `Connection timed out` — the
     * load that broke it was the fleet we had just sent.
     *
     * So capacity is the MINIMUM of what the machine reports and what its roster row
     * allows, and the fact that the cap bound is named separately from the arithmetic
     * bound. A reader must be able to tell "this node is full of children" from "this
     * node has no memory left", because the first is our own scheduling and the second
     * is the machine.
     */
    const machineSlots = Math.max(0, arith.slots - running);
    const rowCap = Number.isInteger(node.maxChildren) && node.maxChildren > 0 ? node.maxChildren : null;
    const capSlots = rowCap === null ? machineSlots : Math.max(0, rowCap - onNode.length);
    const cappedByChildrenCap = capSlots < machineSlots;
    const freeSlots = cappedByChildrenCap ? capSlots : machineSlots;
    const disk = diskFreeGiB(doc);
    const requirement = diskRequirementGiB(task);
    const accepts = reachable ? (doc?.accepts ?? null) : null;
    // Two different kinds of exclusion, deliberately not the same thing:
    //   * the roster's own `excluded: true` is the OPERATOR's switch - it is hard, and no
    //     placement will land there;
    //   * `task.exclude` is the CALLER's hint - it is soft, because the caller's list must
    //     yield to "never refuse" when it names every node.
    const excludedByConfig = node.excluded === true;
    const excludedByCaller = task.exclude.includes(node.node);
    const excludes = excludedByConfig || excludedByCaller;

    let acceptsOk = true;
    let acceptsReason = null;
    if (reachable && accepts !== null) {
      const flag = task.kind === 'fleet' ? accepts.fleet : accepts.oneShot;
      if (flag === false) {
        acceptsOk = false;
        acceptsReason = `accepts.${task.kind === 'fleet' ? 'fleet' : 'oneShot'}=false (${accepts.reason ?? 'no reason given'})`;
      }
      const maxChildren = finite(accepts.maxChildren);
      if (acceptsOk && task.kind === 'fleet' && maxChildren !== null && maxChildren < task.children) {
        acceptsOk = false;
        acceptsReason = `accepts.maxChildren=${maxChildren} < ${task.children} child(ren)`;
      }
    }
    const diskGateApplies = task.kind === 'fleet';
    const diskOk = !diskGateApplies || (disk !== null && disk >= requirement.requiredGiB);
    const fits = reachable && freeSlots - task.children >= 0;

    // AMENDMENT 4: the v1 transport capability, from the roster, not measured here.
    // Three states, and the two negative ones are not the same fact:
    //   true  - the roster says `ssh <node> dsh --profile headless` has been MEASURED to work;
    //   false - measured NOT to work (measured live 2026-09-16: a process launched by
    //           zabz-yoga's sshd cannot traverse ~/.dsh/profiles/node_modules, so the profile
    //           tree fails to load). A placed job there is worse than a queued one;
    //   null  - never measured. Ranked below a measured-working node but never refused, and
    //           named as "unmeasured" so nobody reads it as either answer.
    // This is a RANKING fact, never a gate: `dispatchOk: false` must still be placeable when
    // it is the only candidate, because the owner's rule is queue-never-amputate.
    const dispatch = node.dispatch ?? { v1: null, measuredAt: null, evidence: null };
    const dispatchOk = dispatch.v1 !== false;

    return {
      node: node.node,
      index: node.index,
      fqdn: node.fqdn,
      location: node.location,
      reachable,
      // An ABSENT node is not unreachable: it has no network history to be either. Calling it
      // unreachable was the false claim this amendment exists to remove.
      unreachable: state === 'unreachable',
      state,
      slow,
      capacityUnreadable: state === 'capacity-unreadable',
      capacityReason: state === 'capacity-unreadable' ? (entry?.error ?? 'the capacity document could not be read') : null,
      elapsedMs: entry?.elapsedMs ?? null,
      firstLatencyMs: entry?.firstLatencyMs ?? null,
      absent,
      absentAgeSec: absent ? Math.max(0, Math.round((at - baseline.configuredAt) / 1000)) : null,
      absentReason: absent
        ? `roster node "${node.node}" is configured and has never answered at all (neither reachable nor unreachable: it has no network history to be either)`
        : null,
      entry,
      doc,
      ageSec: ageOf(entry, at),
      lastReadingAgeSec: entry?.lastOkAt === null || entry?.lastOkAt === undefined ? null : seconds(at - entry.lastOkAt),
      reason: reachable ? null : (entry?.error ?? 'never read'),
      arith,
      effective,
      slots: arith.slots,
      memorySlots: arith.memorySlots,
      coreSlots: effective.coreSlots,
      coreSlotsBasis: effective.coreBasis,
      swapApplied: effective.swapApplied,
      swapUsedPct: effective.swapUsedPct,
      freeSlots,
      running,
      queued,
      liveLeases: running + queued,
      // The cap, and WHICH bound produced freeSlots. Named separately so a reader can
      // tell "full of children" (our scheduling) from "out of memory" (the machine).
      maxChildren: rowCap,
      machineSlots,
      cappedByChildrenCap,
      onNode,
      disk,
      requirement,
      diskOk,
      acceptsOk,
      acceptsReason,
      dispatch,
      dispatchOk,
      excluded: excludes,
      excludedByConfig,
      excludedByCaller,
      fits,
      load1: finite(doc?.cpu?.load1),
      logical: finite(doc?.cpu?.logical),
      loopsRunning: finite(doc?.agents?.loopsRunning),
      workRoot: typeof doc?.disk?.workRoot === 'string' ? doc.disk.workRoot : null,
      score: freeSlots,
    };
  }

  /**
   * The disk line: the requirement, the arithmetic that produced it, and the verdict.
   *
   * The requirement is not the flat floor any more (AMENDMENT 1): `requiredGiB = 20 +
   * worktreeGiB + 0.5 * children`, printed term by term so a node that fails by 0.8 GiB
   * says so instead of looking like it passed.
   */
  function diskLine(candidate, task) {
    const { node, requirement } = candidate;
    if (task.kind !== 'fleet') {
      const where = candidate.workRoot === null ? '' : ` on ${candidate.workRoot}`;
      return candidate.disk === null
        ? `${node}: no disk.freeGiB reading (kind=oneShot has no disk gate in §2.2, so this does not block)`
        : `${node}: disk ${gib(candidate.disk)} GiB free${where} (kind=oneShot: §2.2 gates fleets only)`;
    }
    const formula = `${FLEET_DISK_FLOOR_GIB} GiB fleet floor + ${requirement.worktreeGiB} GiB declared worktree `
      + `+ ${PER_CHILD_DISK_GIB} GiB/child x ${requirement.children} child(ren)`;
    if (candidate.disk === null) {
      return `${node}: no disk.freeGiB reading, so the ${requirement.requiredGiB} GiB fleet requirement `
        + `(${formula}) cannot be shown to pass`;
    }
    const where = candidate.workRoot === null ? '' : ` on ${candidate.workRoot}`;
    const verdict = candidate.diskOk ? 'passes' : 'FAILS';
    return `${node}: disk ${gib(candidate.disk)} GiB free${where} vs ${requirement.requiredGiB} GiB required `
      + `(${formula}) -> gate ${verdict}`;
  }

  /**
   * The two terms of the score, in the chosen node's own numbers, and the swap halving when
   * it applied. One line, because the point of the amendment is that a reader can see WHY a
   * node scored what it scored: a 2-vCPU rental that reports 24 memory slots must print
   * "24 memory slot(s), 1 core slot(s) of 2 physical x 0.75 -> effective 1".
   */
  function coreTermLine(candidate) {
    return `${candidate.node}: ${candidate.effective.memoryLine}, ${candidate.effective.coreLine} -> effective ${candidate.effective.effective}`;
  }

  /** The swap line, printed only when it changed the ranking. */
  function swapLine(candidate) {
    return candidate.effective.swapApplied ? `${candidate.node}: ${candidate.effective.swapLine}` : null;
  }

  /**
   * The chosen node's classification, on its own line, ALWAYS - `ok` as well as `slow`.
   *
   * WHY. The classification is the single fact that decides where a node sits in the ranking, and
   * the defect fixed 2026-09-17 was invisible precisely because a node's `slow` state only ever
   * appeared inside a sentence about timing: a reader of `rationale` could see `tier=fits` and
   * "chosen zabz-tech" without ever learning that a whole node had been dropped from the pool for
   * being slow. `SLOW` is also printed by `slowLine()` when it applies; this line is the one a
   * caller can match on (`tier=` + `classification=`), and it names the rule that was applied to
   * it rather than leaving the reader to infer one from the numbers.
   */
  function classificationLine(candidate) {
    const rule = candidate.slow
      ? 'ranked below every node that answered first time and above nothing, placeable via its own tier - never removed from the pool and never refused'
      : 'a normal reading: it is ranked on capacity, and no faster node is preferred over it for answering faster than it did';
    return `${candidate.node}: classification=${candidate.state} - ${rule}`;
  }

  /**
   * The slow line: a node that missed the deadline once and answered on the longer second
   * attempt. Printed so "busy" is never read as "gone" - MEASURED 2026-09-16 23:31:18Z, the
   * broker used to say `zabz-yoga: unreachable (timed out after 1500 ms)` while that laptop's
   * own gate was answering in 89-232 ms and it was simply running the acceptance harness.
   */
  function slowLine(candidate) {
    if (!candidate.slow) return null;
    const kind = candidate.entry?.retryWasFast
      ? 'the node missed the deadline on a COLD first read and answered immediately on the second attempt (a miss to re-check, not proof of congestion)'
      : 'the node was STILL slow on the second attempt';
    return `${candidate.node}: SLOW - the first read missed the ${Math.round(readTimeoutMs)} ms deadline`
      + `${candidate.firstLatencyMs === null ? '' : ` (${candidate.firstLatencyMs} ms)`}, the second answered in `
      + `${candidate.entry?.latencyMs ?? 'unknown'} ms for ${candidate.elapsedMs ?? 'unknown'} ms door-to-door; `
      + `${kind} -> ranked below every node that answered first time, never refused`;
  }

  /**
   * The transport line: what the roster says about `ssh <node> dsh --profile headless`, which
   * is v1 and the only transport that exists today.
   *
   * "measured broken" and "never measured" are different facts and they are printed
   * differently - a broker that rendered both as "false" would be inventing a measurement,
   * and one that rendered both as a blank would be hiding one.
   */
  function transportLine(candidate) {
    const { node, dispatch } = candidate;
    const evidence = dispatch.evidence === null ? '' : `: ${dispatch.evidence}`;
    const when = dispatch.measuredAt === null ? '' : ` (measured ${dispatch.measuredAt})`;
    if (dispatch.v1 === true) {
      return `${node}: transport v1 (ssh --profile headless) MEASURED to work${when}${evidence} - work dispatched here can actually run`;
    }
    if (dispatch.v1 === false) {
      return `${node}: transport v1 (ssh --profile headless) MEASURED BROKEN${when}${evidence} - ranked below every node that can take the work, never refused`;
    }
    return `${node}: transport v1 (ssh --profile headless) UNMEASURED - not a claim that it works and not a claim that it does not; ranked below a node measured to work, above one measured broken`;
  }

  function otherLine(candidate, task) {
    if (candidate.absent) {
      return `${candidate.node}: absent - ${candidate.absentReason}; configured ${candidate.absentAgeSec} s ago, excluded from the ranking (it is not unreachable, it has never been reachable)`;
    }
    if (candidate.capacityUnreadable) {
      return `${candidate.node}: CAPACITY-UNREADABLE - the node answered but its capacity document could not be read (${candidate.capacityReason}) - a broken reader, not an offline machine; not ranked`;
    }
    if (!candidate.reachable) {
      const stale = candidate.lastReadingAgeSec === null ? '' : `, last good reading ${candidate.lastReadingAgeSec} s old`;
      return `${candidate.node}: unreachable (last attempt ${candidate.ageSec} s ago${stale}: ${candidate.reason}) - reported, never dropped, never faked`;
    }
    const bits = [
      `${candidate.freeSlots} free slot(s) of ${MAX_SLOTS}`,
      candidate.effective.summary,
      `${candidate.freeSlots - task.children} after ${task.children} child(ren)`,
    ];
    // WHEN OUR OWN CAP IS WHAT LIMITS A NODE, SAY SO. Otherwise a reader sees "0 free
    // slots" and concludes the machine is exhausted, when in fact it is carrying as many
    // children as its row allows and would take more if the row said so.
    if (candidate.cappedByChildrenCap) {
      bits.push(`limited by this row's children cap (${candidate.maxChildren} at once; ${candidate.machineSlots - candidate.freeSlots} slot(s) still unused on the machine)`);
    }
    if (candidate.slow) bits.push(`SLOW (${candidate.elapsedMs ?? '?'} ms door-to-door, first attempt missed the deadline): ${candidate.entry?.retryWasFast ? 'a cold-start miss, not proof of congestion' : 'still slow on the second attempt'}`);
    if (candidate.swapApplied) bits.push(`swap ${candidate.swapUsedPct}% used: effective slots halved`);
    if (!candidate.dispatchOk) bits.push('transport v1 MEASURED BROKEN');
    else if (candidate.dispatch.v1 === null) bits.push('transport v1 unmeasured');
    if (candidate.excluded) bits.push('excluded by the caller');
    if (!candidate.diskOk && task.kind === 'fleet') bits.push(`disk ${gib(candidate.disk ?? -1)} GiB < ${candidate.requirement.requiredGiB} GiB required`);
    if (!candidate.acceptsOk) bits.push(candidate.acceptsReason);
    return `${candidate.node}: ${bits.join(', ')}`;
  }

  function tierLine(tier, chosen, task, context) {
    switch (tier) {
      case 'highest-slots':
        return `no node can start this now (every candidate's free slots - ${task.children} < 0); `
          + `${chosen.node} has the highest measured slots on the mesh (${chosen.slots}) -> placed there, QUEUED rather than refused `
          + '(the frozen "a fleet bigger than every node still places" rule, §2.2)'
          + (chosen.slow ? ' - and it is SLOW, which is a ranking fact and not a reason to leave it out' : '');
      case 'transport':
        return `no node that can take v1 work can start this now; ${chosen.node} is the best of the candidates that cannot `
          + `(transport.v1=${chosen.dispatch.v1 === false ? 'false' : 'unmeasured'}), chosen despite transport=unavailable `
          + 'because nothing else is eligible -> placed there, QUEUED rather than refused (queue, never amputate)';
      case 'slow':
        // Kept so a persisted `tier` from an older response still reads; the ladder above no longer
        // PRODUCES it, because a slow node is a candidate in the tier it belongs to and the line
        // that matters now says `classification=slow` (docs/mesh/98-broker-fixes.md §1).
        return `every node that can start this is SLOW (each missed the ${Math.round(readTimeoutMs)} ms deadline at least once and answered on the longer second attempt); `
          + `${chosen.node} is the best of them (${chosen.elapsedMs ?? 'unknown'} ms door-to-door, state=${chosen.state}) -> placed there, `
          + 'QUEUED rather than refused (a slow node is ranked lower, never amputated; the next read of a warm node returns it to full rank)';
      case 'queued': {
        const why = [];
        if (!chosen.reachable) why.push('it is unreachable, so its capacity is unknown');
        if (!chosen.diskOk && task.kind === 'fleet') {
          why.push(`its ${chosen.disk === null ? 'unmeasured' : `${Math.round(chosen.disk)} GiB`} free is under the ${chosen.requirement.requiredGiB} GiB fleet requirement`);
        }
        if (!chosen.acceptsOk) why.push(chosen.acceptsReason);
        if (chosen.excludedByCaller) why.push('the caller excluded it');
        const everyNodeExcluded = context.excludedCount === context.total;
        return `no node can start this now (${why.join('; ') || 'no free slots anywhere'}); ${chosen.node} is the best candidate `
          + `(${chosen.reachable ? `measured, ${chosen.slots} slot(s)` : 'unreachable'}${everyNodeExcluded ? ', and the caller excluded every node' : ''}) `
          + '-> placed there, QUEUED rather than refused (the broker never refuses a placement)';
      }
      default:
        return null;
    }
  }

  function positionLine(chosen, task, position, startNow, blockedBy) {
    if (startNow) {
      return `position 0: ${chosen.freeSlots} free slot(s) - ${task.children} child(ren) = ${chosen.freeSlots - task.children} >= 0 on a reachable node -> start now`;
    }
    // The arithmetic is printed as measured, and the reason for queueing is printed as a
    // separate fact. An earlier version of this line assumed "not starting" always meant
    // "freeSlots < children" and printed `21 < 0` when a caller had excluded the only node
    // that fit - caught live on the authority 2026-09-16, and the reason it is now derived
    // from blockedBy rather than assumed.
    const difference = chosen.freeSlots - task.children;
    const fits = difference >= 0;
    const why = blockedBy.length > 0 ? blockedBy.join(', ') : 'no blocker recorded';
    const minimum = chosen.liveLeases === 0
      ? '; no accepted job is ahead yet, so the position is the minimum of 1 - a job that cannot start is queued, not refused'
      : '';
    return `position ${position}: ${chosen.freeSlots} free slot(s) - ${task.children} child(ren) = ${difference} `
      + `${fits ? '(it would fit)' : '(< 0, it does not fit)'}, queued because ${why}; `
      + `${chosen.liveLeases} accepted job(s) ahead on ${chosen.node}${minimum}`;
  }

  /** Choose a node and issue its lease. Synchronous on purpose: the decision and the reservation cannot interleave. */
  function decide({ task, notes, at }) {
    const all = nodes.map((node) => evaluate(node, task, at));
    // Amendment 5: an `absent` node is not a placement target and is not counted as a
    // candidate - there is nothing to rank and nothing to queue behind. It is still reported
    // by GET /nodes, with its age measured from when it was configured. When EVERY node is
    // absent there is nothing to exclude, and the never-refuse rule still has to produce a
    // placement, so the whole roster is the pool.
    const present = all.filter((candidate) => !candidate.absent);
    const candidates = present.length > 0 ? present : all;
    const absentCount = all.length - present.length;
    // A node switched off in the roster is not a placement target at all; a node the CALLER
    // excluded still is, because a caller who excludes everything has made a mistake that
    // must not become a refusal.
    const placeable = candidates.filter((candidate) => !candidate.excludedByConfig);
    const arena = placeable.length > 0 ? placeable : candidates;
    const base = arena.filter((candidate) => !candidate.excludedByCaller && candidate.acceptsOk);
    const withDisk = base.filter((candidate) => candidate.diskOk);
    const unreachableCount = candidates.filter((candidate) => candidate.unreachable).length;
    const excludedCount = candidates.filter((candidate) => candidate.excludedByCaller).length;
    const configExcluded = candidates.length - placeable.length;
    const head = `chosen from ${candidates.length} configured node(s): ${unreachableCount} unreachable, `
      + `${excludedCount} excluded by the caller, ${configExcluded} switched off in the roster`
      + (absentCount > 0 ? `, ${absentCount} absent (configured, never answered, not ranked)` : '');

    let tier;
    let pool;
    // AMENDMENT 4: a node the roster records as UNABLE to take v1 work is not in the pool below
    // while any node that can take it is. If no node can take it at all, the pool falls back to
    // every eligible node, so the choice is still a placement - it is just a visible one, said in
    // as many words in the rationale.
    //
    // A SLOW NODE IS RANKED, NOT REMOVED (defect fixed 2026-09-17, requirement 3 / §10.8).
    //   The shipped code narrowed the pool with `preferred = dispatchable.filter(c => !c.slow)`
    //   and used it whenever it was non-empty, so a node whose capacity read missed the deadline
    //   once and then answered was dropped from the `fits` pool ENTIRELY. Measured consequence
    //   (docs/mesh/92-provider-placement.md §5.2-§5.3): the owner's own laptop alternates
    //   ok/slow/ok on consecutive fresh reads, so it received no children at all while the
    //   desktop answered quickly - including when it had MORE free slots than the winner. Eight
    //   concurrent children landed on the desktop; a two-child split never happened.
    //   The contract is "ranked below every node that answered first time and never refused"
    //   (71-mesh-program.md §2.2, 76-broker.md §10.8), and being ranked below is not the same as
    //   being removed. So the pool is every node that can take the work, and `compareFallback`
    //   below puts `ok` before `slow` (after reachability and transport). A slow node wins exactly
    //   when the nodes that answered first time cannot take the job - which is the case that used
    //   to become a needless queue: §5.3 measured the desktop at 11 free slots and the laptop at
    //   12, and the fleet went to the desktop.
    const eligible = withDisk;
    const dispatchable = eligible.filter((candidate) => candidate.dispatchOk);
    const canStart = (candidate) => candidate.fits;
    if (dispatchable.some(canStart)) {
      tier = 'fits';
      pool = dispatchable.filter(canStart);
    } else if (dispatchable.length > 0) {
      // Nothing that can take the work has room for this job right now (frozen §2.2: "a fleet
      // bigger than every node still places"). The pool is every node that can take v1 work -
      // slow ones included, because "cannot start now" is a queue and a node that missed one
      // deadline is not a safer thing to queue on than a node that answered late.
      tier = 'highest-slots';
      const highest = Math.max(...dispatchable.map((candidate) => candidate.slots));
      pool = dispatchable.filter((candidate) => candidate.slots === highest);
    } else if (eligible.some(canStart)) {
      // Nothing eligible can take v1 work, but something could run it if the transport were
      // not the problem. Queued rather than refused, and the transport is named.
      tier = 'transport';
      pool = eligible.filter((candidate) => candidate.fits);
    } else if (eligible.length > 0) {
      tier = 'transport';
      const highest = Math.max(...eligible.map((candidate) => candidate.slots));
      pool = eligible.filter((candidate) => candidate.slots === highest);
    } else {
      // Nothing can start now. This is still a placement, not a refusal: the pool is every
      // node the caller did not exclude, and the ranking changes shape - a node we can
      // MEASURE beats a node we cannot, and among measured nodes more slots wins. That order
      // is not cosmetic: measured live on 2026-09-16, the alternative (preferring any node
      // that merely permits the work over a reachable one that declares a restriction) put a
      // dead laptop ahead of the one node actually answering. Reachability first is also what
      // "never faked" means at the ranking layer.
      tier = 'queued';
      pool = arena;
    }

    /**
     * The order every tier is ranked by, in one place. Ordered by how much each fact tells the
     * caller about whether the work can actually run there, and never a gate: every candidate in
     * `pool` is placeable and the first one wins.
     *
     *   1. reachable                    - a node we can measure beats one we cannot;
     *   2. can take v1 work             - a node measured to accept `ssh <node> dsh --profile
     *                                     headless` beats one measured not to, and an unmeasured
     *                                     one (`null`) sits between the two facts;
     *   3. NOT slow                     - a node that answered first time beats one that missed the
     *                                     deadline once and answered on the longer second attempt
     *                                     (the defect fixed 2026-09-17: it used to be excluded
     *                                     outright, so a slow node was unplaceable while any fast
     *                                     node existed - see the note above the tier ladder);
     *   4. fits now                     - a node with room for THIS job beats one that will queue it.
     *                                     This is the last of the three facts that decide the tier,
     *                                     and it can only split candidates inside `highest-slots`
     *                                     (inside `fits` every candidate already fits); it never
     *                                     overrides `slow`, so a slow node is never skipped over in
     *                                     favour of a fast one that must queue the job;
     *   5. more effective slots, then load, then roster order.
     */
    const compareFallback = (a, b) => {
      const ra = a.candidate.reachable ? 1 : 0;
      const rb = b.candidate.reachable ? 1 : 0;
      if (ra !== rb) return rb - ra;
      // A node measured to be unable to take v1 work ranks below one that can or might.
      // `null` (unmeasured) sits between the two: it may work, and it is not a measured
      // refusal, but it is not a measurement either.
      const va = a.candidate.dispatchOk ? 1 : 0;
      const vb = b.candidate.dispatchOk ? 1 : 0;
      if (va !== vb) return vb - va;
      // A SLOW node ranks below a fast one and above nothing: it is still a placement target.
      const sa = a.candidate.slow ? 1 : 0;
      const sb = b.candidate.slow ? 1 : 0;
      if (sa !== sb) return sa - sb;
      // Room for this job before slots: the queue this removes is a real one, and a node that can
      // start the work now is a better answer than one that cannot, whatever their raw sizes.
      const fa = a.candidate.fits ? 1 : 0;
      const fb = b.candidate.fits ? 1 : 0;
      if (fa !== fb) return fb - fa;
      if (a.candidate.slots !== b.candidate.slots) return b.candidate.slots - a.candidate.slots;
      return compareRanking(a.key, b.key);
    };
    const ranked = pool
      .map((candidate) => ({ candidate, key: rankingKey({ ...candidate, task }) }))
      .sort(compareFallback);
    const chosen = ranked[0].candidate;
    const startNow = tier === 'fits' && chosen.fits;
    const position = startNow ? 0 : (chosen.liveLeases > 0 ? chosen.liveLeases : 1);
    const lease = leases.issue({
      node: chosen.node,
      kind: task.kind,
      children: task.children,
      state: startNow ? 'running' : 'queued',
      at,
      ttlMs: leaseTtlMs,
    });

    const lines = [];
    const blockedBy = startNow ? [] : [
      ...(chosen.reachable ? [] : ['unreachable']),
      ...(chosen.diskOk || task.kind !== 'fleet' ? [] : ['disk']),
      ...(chosen.acceptsOk ? [] : ['accepts']),
      ...(chosen.dispatchOk ? [] : ['transport']),
      ...(chosen.excludedByCaller ? ['caller-excluded'] : []),
      ...(chosen.freeSlots - task.children >= 0 ? [] : ['no-free-slots']),
    ];
    lines.push(`${head}; tier=${tier}; chosen ${chosen.node}`);
    lines.push(`${chosen.node}: ${chosen.arith.line}`);
    lines.push(`${chosen.node}: ${chosen.freeSlots} free slot(s) of ${MAX_SLOTS} `
      + `(slots ${chosen.arith.slots} = ${chosen.arith.raw} raw - see above, minus ${chosen.running} broker lease(s) running here; ${chosen.queued} queued)`);
    // ── WHERE "0 FREE SLOTS" CAME FROM ────────────────────────────────────────
    // The line above derives free slots from the MACHINE's arithmetic. When this node's
    // roster row caps how many children it may carry, the machine may still have room and
    // the honest answer is different: our own scheduling bound it, not the box. A reader
    // who sees "0 free slots" must not conclude the machine is exhausted (P332: five
    // children on one node, its sshd to 8 s, one child lost).
    if (chosen.cappedByChildrenCap) {
      lines.push(`${chosen.node}: capacity is capped by its ROSTER ROW at ${chosen.maxChildren} concurrent child(ren), not by the machine - `
        + `${chosen.machineSlots} slot(s) of machine capacity are left unused here, and the row is the reason a further child queues`);
    }
    if (!chosen.reachable) {
      lines.push(`${chosen.node}: UNREACHABLE (last attempt ${chosen.ageSec} s ago: ${chosen.reason}) - no live measurement, so it is treated as 0 free slot(s) and the answer is a queue position, not a claim that it will start`);
    }
    lines.push(diskLine(chosen, task));
    lines.push(`${chosen.node}: load1 ${chosen.load1 ?? 'not measured'} on ${chosen.logical ?? 'unknown'} logical cpu(s), ${chosen.loopsRunning ?? 'unknown'} agent loop(s) running`);
    // AMENDMENT 3: the two terms of the score, printed. The memory term alone is what the
    // old model ranked on, and it overstates a small box by up to 6x - which is the number
    // an elastic-capacity purchase would be made on.
    lines.push(coreTermLine(chosen));
    const swap = swapLine(chosen);
    if (swap !== null) lines.push(swap);
    const classification = classificationLine(chosen);
    if (classification !== null) lines.push(classification);
    const slow = slowLine(chosen);
    if (slow !== null) lines.push(slow);
    lines.push(transportLine(chosen));
    lines.push(`${chosen.node}: ${chosen.freeSlots} free slot(s) - ${task.children} child(ren) = ${chosen.freeSlots - task.children} `
      + `${chosen.freeSlots - task.children >= 0 ? '>= 0 -> fits now' : '< 0 -> does not fit now'}`);
    if (!chosen.acceptsOk) lines.push(`${chosen.node}: ${chosen.acceptsReason}`);
    const explain = tierLine(tier, chosen, task, { excludedCount, total: candidates.length });
    if (explain !== null) lines.push(explain);
    lines.push(positionLine(chosen, task, position, startNow, blockedBy));
    if (task.prefer !== null && chosen.location === task.prefer) {
      lines.push(`preference "${task.prefer}" matched ${chosen.node}'s location; worth +${PREFERENCE_BONUS} slot(s) in the ranking, not in the score`);
    } else if (task.prefer !== null) {
      lines.push(`preference "${task.prefer}" did not match ${chosen.node} (location ${chosen.location ?? 'unknown'}); no bonus applied`);
    }
    for (const note of notes) lines.push(`note: ${note}`);
    const others = ranked.slice(1).map((entry) => entry.candidate)
      .concat(candidates.filter((candidate) => !pool.includes(candidate)));
    const room = Math.max(0, MAX_RATIONALE_LINES - lines.length - 1);
    for (const other of others.slice(0, room)) lines.push(otherLine(other, task));
    if (others.length > room) {
      lines.push(`+${others.length - room} more candidate(s) not listed here; every one of them is in GET /nodes with its own numbers`);
    }
    lines.push(`lease ${lease.id} (opaque, ${lease.state}) expires ${iso(lease.expiresAt)}; ttl ${seconds(leaseTtlMs)} s, `
      + 'reclaimed by the broker at expiry so a dead dispatcher cannot wedge the mesh');

    return {
      node: chosen.node,
      position,
      lease: lease.id,
      score: chosen.score,
      eligible: pool.length,
      rationale: lines,
      queue: position === 0 ? [] : chosen.onNode.map((entry) => ({
        lease: entry.id,
        node: entry.node,
        kind: entry.kind,
        children: entry.children,
        state: entry.state,
        waitsMs: Math.max(0, at - entry.issuedAt),
      })),
      at: iso(at),
      kind: task.kind,
      children: task.children,
      considered: candidates.length,
      unreachable: unreachableCount,
      excluded: excludedCount,
      absent: absentCount,
      tier,
      /** Why this placement is a queue position and not a start. Empty when position is 0. */
      blockedBy,
      expiresAt: iso(lease.expiresAt),
      leaseTtlSec: seconds(leaseTtlMs),
    };
  }

  /**
   * The last resort: an internal fault must still produce a placement. §2.2's rule is
   * absolute - "There is no code path that returns an error instead of a placement" - so
   * even a bug in the arithmetic above answers with a node and a queue position.
   */
  function emergencyPlacement({ task, notes, at, error }) {
    const node = nodes[0];
    const lease = leases.issue({
      node: node.node,
      kind: task.kind,
      children: task.children,
      state: 'queued',
      at,
      ttlMs: leaseTtlMs,
    });
    return {
      node: node.node,
      position: 1,
      lease: lease.id,
      score: 0,
      eligible: nodes.length,
      rationale: [
        `internal fault while scoring (${messageOf(error)}); placed on ${node.node} with position 1 rather than returning an error - the broker never refuses a placement`,
        ...notes.map((note) => `note: ${note}`),
        `lease ${lease.id} (opaque, queued) expires ${iso(lease.expiresAt)}; ttl ${seconds(leaseTtlMs)} s`,
      ],
      queue: [],
      at: iso(at),
      kind: task.kind,
      children: task.children,
      considered: nodes.length,
      unreachable: null,
      excluded: null,
      tier: 'internal-fault',
      blockedBy: ['internal-fault'],
      expiresAt: iso(lease.expiresAt),
      leaseTtlSec: seconds(leaseTtlMs),
    };
  }

  /** `POST /place`. Async only because it may need to read; the decision itself is synchronous. */
  async function place(body) {
    const { task, notes } = normalizeTask(body);
    const at = now();
    await refresh({ fresh: false }).catch(() => undefined);
    const decisionAt = now();
    try {
      return decide({ task, notes, at: decisionAt });
    } catch (error) {
      return emergencyPlacement({ task, notes, at: decisionAt, error });
    }
  }

  /** `POST /done`. Always answers 200; an unknown lease is a fact, not an error. */
  function done(body) {
    let source = body;
    if (typeof body === 'string') {
      try {
        source = JSON.parse(body);
      } catch {
        source = null;
      }
    }
    const leaseId = source !== null && typeof source === 'object' && typeof source.lease === 'string' && source.lease.length > 0
      ? source.lease
      : null;
    const at = now();
    if (leaseId === null) {
      return { ok: false, released: false, lease: null, node: null, reason: 'the body had no non-empty "lease" string', at: iso(at) };
    }
    const result = leases.release(leaseId, at);
    return {
      ok: result.released,
      released: result.released,
      lease: leaseId,
      node: result.node,
      state: result.state,
      heldMs: result.heldMs,
      reason: result.released ? null : 'unknown or already-expired lease (a lease is reclaimed by the broker at its TTL, so this is not an error)',
      at: iso(at),
      leases: leases.stats(at),
    };
  }

  /** One node, as `GET /nodes` reports it: the last reading, its age, and the numbers derived from it. */
  function nodeView(node, at) {
    const entry = readings.get(node.node);
    const reachable = entry !== undefined && entry.ok === true;
    const absent = isAbsent(node);
    const baseline = baselineOf(node, at);
    // The same closed set as `evaluate`: absent / capacity-unreadable / unreachable / slow / ok.
    // `capacity-unreadable` is the state a node whose READER is broken gets - it answered, so it
    // is not unreachable, and it is excluded from the ranking so an unmeasured budget is never
    // treated as a big one.
    const state = reachable
      ? (entry?.state === 'slow' ? 'slow' : 'ok')
      : absent
        ? 'absent'
        : entry === undefined
          ? 'unread'
          : entry.state === 'capacity-unreadable'
            ? 'capacity-unreadable'
            : 'unreachable';
    const doc = reachable ? entry.doc : null;
    const arith = slotArithmetic(doc);
    const effective = effectiveSlots(arith);
    const dispatch = node.dispatch ?? { v1: null, measuredAt: null, evidence: null };
    const onNode = leases.onNode(node.node, at);
    const running = onNode.filter((lease) => lease.state === 'running').length;
    const view = {
      node: node.node,
      fqdn: node.fqdn,
      location: node.location,
      baseUrl: node.baseUrl,
      url: capacityUrl(node),
      state,
      unreachable: state === 'unreachable',
      absent,
      capacityUnreadable: state === 'capacity-unreadable',
      absentSince: absent ? iso(baseline.configuredAt) : null,
      ageSec: absent ? Math.max(0, Math.round((at - baseline.configuredAt) / 1000)) : ageOf(entry, at),
      attempts: entry?.attempts ?? 0,
      latencyMs: entry?.latencyMs ?? null,
      retried: entry?.retried === true,
      firstLatencyMs: entry?.firstLatencyMs ?? null,
      elapsedMs: entry?.elapsedMs ?? null,
      // ── THE PER-NODE CHILDREN CAP, READABLE FROM THE SURFACE ────────────────
      // `maxChildren` is how many children this row may carry AT ONCE, and
      // `childrenCapReached` says whether it is what limits this node right now.
      // An operator asking "why did my fleet queue when the machine looks idle?"
      // must be able to answer it from GET /nodes without reading nodes.json.
      maxChildren: Number.isInteger(node.maxChildren) && node.maxChildren > 0 ? node.maxChildren : null,
      childrenRunning: running,
      childrenCapReached: Number.isInteger(node.maxChildren) && node.maxChildren > 0 && running >= node.maxChildren,
    };
    if (absent) {
      view.note = 'configured in the roster and never answered: this is the ABSENT state, not unreachable - the node has no network history to be either, and it is excluded from the ranking. Measured by this broker, not a claim about the far side.';
    }
    if (state === 'slow') {
      view.note = `the first read missed the ${Math.round(readTimeoutMs)} ms deadline and the longer second attempt answered (${view.elapsedMs} ms door-to-door, first attempt ${view.firstLatencyMs} ms, retry ${view.latencyMs} ms): ${entry?.retryWasFast ? 'a cold-start miss rather than proof of congestion, and the next read of a warm node comes back ok at full rank' : 'still slow on the second attempt'}. It is ranked below every node that answered first time and is never refused.`;
    }
    if (state === 'capacity-unreadable') {
      view.note = 'the node ANSWERED but its capacity document could not be read, so its budget is unknown and it is excluded from the ranking: this is a broken reader, not an offline machine. The reason it gave is in `reason`.';
    }
    if (reachable) {
      view.reading = doc;
      view.reportedNode = entry.reportedNode;
      view.warning = entry.note;
      view.lastReadingAt = entry.lastOkAt === null ? null : iso(entry.lastOkAt);
    } else {
      view.reason = state === 'capacity-unreadable' ? (entry?.reason ?? entry?.error ?? 'the capacity document could not be read') : (entry?.error ?? 'never read');
      view.lastReadingAt = entry?.lastOkAt === null || entry?.lastOkAt === undefined ? null : iso(entry.lastOkAt);
      view.lastReadingAgeSec = entry?.lastOkAt === null || entry?.lastOkAt === undefined ? null : seconds(at - entry.lastOkAt);
      if (entry?.doc !== null && entry?.doc !== undefined && state !== 'capacity-unreadable') {
        view.staleReading = { doc: entry.doc, ageSec: seconds(at - entry.at), note: 'this is the last reading that succeeded; it is NOT current' };
      }
      if (state === 'capacity-unreadable' && entry?.doc !== null && entry?.doc !== undefined) {
        view.unreadableReading = { doc: entry.doc, ageSec: seconds(at - entry.at), note: 'the document this node sent; it is not a usable §2.1 capacity document' };
      }
    }
    view.slots = arith.slots;
    view.memorySlots = arith.memorySlots;
    view.coreSlots = effective.coreSlots;
    view.coreSlotsBasis = effective.coreBasis;
    view.swapApplied = effective.swapApplied;
    view.swapUsedPct = effective.swapUsedPct;
    view.effectiveSlots = effective.effective;
    view.slotsKnown = arith.known;
    view.freeSlots = Math.max(0, arith.slots - running);
    view.slotArithmetic = arith.arithmetic;
    view.scoreTerms = { memorySlots: arith.memorySlots, coreSlots: effective.coreSlots, coreSlotsBasis: effective.coreBasis, swapApplied: effective.swapApplied, effectiveSlots: effective.effective, reserveMiB: arith.reserveMiB, reserveBasis: arith.reserveBasis };
    // AMENDMENT 4: the roster's per-node transport capability, reported as the three-state
    // fact it is (`true`/`false`/`null` = unmeasured).
    view.transport = { v1: dispatch.v1, measuredAt: dispatch.measuredAt, evidence: dispatch.evidence };
    view.brokerLeases = { running, queued: onNode.length - running };
    return view;
  }

  /** `GET /nodes`. `fresh` forces a re-read; otherwise cached ≤ cacheTtlMs. */
  async function nodesReport({ fresh = false } = {}) {
    await refresh({ fresh }).catch(() => undefined);
    const at = now();
    return {
      schema: 1,
      at: iso(at),
      cacheTtlSec: seconds(cacheTtlMs),
      readTimeoutMs,
      leaseTtlSec: seconds(leaseTtlMs),
      reads,
      readFailures,
      nodes: nodes.map((node) => nodeView(node, at)),
      leases: leases.stats(at),
    };
  }

  function status() {
    const at = now();
    return {
      schema: 1,
      at: iso(at),
      startedAt: iso(startedAt),
      uptimeSec: seconds(at - startedAt),
      nodes: nodes.length,
      reads,
      readFailures,
      cacheTtlSec: seconds(cacheTtlMs),
      readTimeoutMs,
      leaseTtlSec: seconds(leaseTtlMs),
      leases: leases.stats(at),
    };
  }

  return {
    place,
    done,
    nodes: nodesReport,
    status,
    /** Exposed for tests and for /nodes; not a state store. */
    readings,
    leases,
    /**
     * The reserve is NOT one number any more, and this field deliberately does not pretend to
     * be one: it is derived per node from that node's own `mem.totalMiB` (`scoring.js`
     * `reserveMiB()`), and the per-node result rides on every `/nodes` row in `scoreTerms`.
     * `fallbackMiB` is the frozen literal, used only for a node that reports no total memory.
     * (Was `reserveMiB: 3885`; nothing read it, and a scalar here said the opposite of what the
     * broker does — see docs/mesh/86-authority.md §3.)
     */
    reserveRule: {
      rule: "max(2048 MiB, 12% of the node's own mem.totalMiB) - the governor's own derivation (governor.js:126), applied per node",
      perNode: true,
      fallbackMiB: RESERVE_MIB,
    },
    config: { nodes, cacheTtlMs, readTimeoutMs, retryTimeoutMs, leaseTtlMs, perSlotMiB: PER_SLOT_MIB, maxSlots: MAX_SLOTS },
  };
}
