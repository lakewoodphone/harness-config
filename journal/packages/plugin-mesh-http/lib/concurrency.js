/**
 * How many agent turns this node may run at once — derived from THIS node's own capacity.
 *
 * WHY THIS FILE EXISTS
 * v0.1.0 of the route accepted one run per node because "one generating turn costs ~0.81 GB
 * commit and ~1 core" (`71` §2.2) and a route that accepts unlimited runs is an uncapped fleet.
 * That was the safe direction and it was a hard ceiling of one agent per node. `84-calibration.md`
 * then measured both halves of that sentence and they were wrong in different directions:
 *
 *   * **commit per turn** is **403 MiB** (95 % CI 270-533), not 810 MiB — `84` §3, n = 63 + a
 *     level-mean fit at 402 MiB r² = 0.948, cross-checked by `Available MBytes` at -410 MiB/turn;
 *   * **CPU per turn** is **0.62 logical CPUs** for a model-bound turn and **1.68** for a
 *     tool-heavy one — `84` §4.3 — so "~1 core" is a workload-dependent number, not a constant;
 *   * and the thing that actually degrades first is the engine's **event-loop lag maximum**,
 *     18 ms → 54 ms at 8 tool-heavy turns — `84` §4.1.
 *
 * So the ceiling is computed, here, from the machine, and published with its arithmetic so a
 * reader can check it without reading this source. Every constant below carries the section that
 * measured it; none of them is a preference.
 *
 * THE ARITHMETIC, EXACTLY. `limit = max(1, min(cpu, mem, declared, hard))` where
 *
 *   cpu      = floor(logicalCpus × CPU_BUDGET_FRACTION / CPU_PER_TURN)
 *   mem      = floor((availableMiB − reserveMiB) / COMMIT_PER_TURN_MIB)
 *   declared = the node's own advertised fleet ceiling, from its capacity contract (`72` §2.1),
 *              when the local gate answers; absent otherwise
 *   hard     = HARD_CEILING, the governor's own slot ceiling on this host
 *
 * WORKED EXAMPLES (measured inputs, 2026-09-17; `docs/mesh/93-transport-concurrency.md` §4):
 *
 *   zabz-tech   32 logical, 65,173 MiB total, 53,616 MiB available, declared 12
 *               cpu = floor(32 × 0.42 / 1.68) = 8      (13.4 logical CPUs of budget ÷ 1.68)
 *               mem = floor((53616 − 7821) / 403) = 113
 *               limit = min(8, 113, 12, 24) = **8**     ← the CPU term binds
 *
 *   zabz-yoga-1 22 logical, 32,373 MiB total, ~12,701 MiB available
 *               cpu = floor(22 × 0.42 / 1.68) = 5
 *               limit = min(5, 21, 12, 24) = **5**      ← the CPU term binds
 *
 *   secratary   4 cores
 *               cpu = floor(4 × 0.42 / 1.68) = 1
 *               limit = **1**                            ← the CPU term binds, hard
 *
 * The last row is the one that matters for safety: `84` §6.2 recorded that 8 concurrent turns on
 * the authority's 4 cores is a **2× oversubscription**, and it could not be measured there. This
 * derivation refuses to allow it, on the machine's own numbers, without anyone deciding.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 * It does not read the gate to *derive* anything. The gate's `accepts.maxChildren` is
 * `min(free_slots, 12)` where `12` is `MESH_MAX_CHILDREN`, a **constant** in
 * `scripts/phone-gate.py:939` — so it is used only as a ceiling the node has already published,
 * never as the source of the number. The two *derived* terms (cpu, mem) are computed from
 * quantities this process reads itself, and the response says which term bound.
 *
 * FAIL SOFT, NEVER LOUD. If the capacity contract cannot be read, `declared` is `null` and the
 * limit is the derived `min(cpu, mem)` — still a number, still derived, and the response names the
 * missing input. A node whose gate is down must not stop accepting work.
 */

import { readFileSync } from 'node:fs';
import { get } from 'node:http';
import os from 'node:os';

/**
 * `84` §4.1/§4.3: the largest LOGICAL-CPU occupancy that was measured BENIGN.
 *
 * This fraction is not a preference, it is a reading. On `zabz-tech` (32 logical CPUs) `84`
 * measured 8 tool-heavy turns at **41.5 % mean / 62.9 % max** of all logical processors, with
 * commit at 16 % of its limit, the pagefile flat at 14.1 % in every one of the 83 samples and the
 * disk queue at 0-1 — and the ONE counter that left its benign band was the engine's event-loop
 * lag maximum, 18 ms → 54 ms. 8 resident turns sat at 18.35 %. So 41.5 % is the highest occupancy
 * the program has ever measured without a fleet-sized cost, and this constant is that number.
 *
 * It is deliberately in LOGICAL CPUs because that is the unit `84` §4.3 measured `CPU_PER_TURN`
 * in, and mixing the two units is the error `84` §4.3 and §6.6 warn about ("the logical-processor
 * → physical-core conversion under SMT ... Not measured"). `84`'s own `0.75 × physical cores` is a
 * different, PHYSICAL formulation; on `zabz-tech` it gives 18 and this gives 8, and both sit inside
 * `84`'s measured 14-39 band for "24 cores' worth of turns" — 8 is the conservative end and it is
 * the end anchored in a measurement rather than an extrapolation.
 */
export const LOGICAL_CPU_BUDGET_FRACTION = 0.42;
/** `84` §4.3: the measured cost of the WORST turn class — a tool-heavy turn, 1.68 logical CPUs. */
export const CPU_PER_TURN = 1.68;
/** `84` §3: commit per additional concurrent turn, MiB — the level-mean fit. */
export const COMMIT_PER_TURN_MIB = 403;
/** `84` §1.1/§4.4: the gate's own reserve shape, `max(2 GiB, 12 % of physical)`. */
export const MIN_RESERVE_MIB = 2048;
export const RESERVE_FRACTION = 0.12;
/** The admission governor's ceiling on this host ("clamped 4-24"); never more than this. */
export const HARD_CEILING = 24;

/**
 * The arithmetic above, as a pure function, so a test can pin every branch and the document can
 * quote a table the code produced.
 *
 * @returns {{limit: number, terms: object, inputs: object, sources: object, note: string}}
 */
export function deriveConcurrencyLimit({
  logicalCpus,
  totalMiB,
  availableMiB,
  declaredMax = null,
  cpuBudgetFraction = LOGICAL_CPU_BUDGET_FRACTION,
  cpuPerTurn = CPU_PER_TURN,
  commitPerTurnMiB = COMMIT_PER_TURN_MIB,
  reserveMiB,
  hardCeiling = HARD_CEILING,
  availableSource = 'unknown',
} = {}) {
  const logical = Number.isFinite(logicalCpus) && logicalCpus >= 1 ? Math.floor(logicalCpus) : 1;
  const total = Number.isFinite(totalMiB) && totalMiB > 0 ? totalMiB : null;
  const available = Number.isFinite(availableMiB) && availableMiB > 0 ? availableMiB : null;
  const reserve = Number.isFinite(reserveMiB) && reserveMiB >= 0
    ? reserveMiB
    : (total === null ? MIN_RESERVE_MIB : Math.max(MIN_RESERVE_MIB, Math.round(RESERVE_FRACTION * total)));

  const cpuBudget = logical * cpuBudgetFraction;
  const cpuTerm = Math.max(1, Math.floor(cpuBudget / cpuPerTurn));
  const memTerm = available === null
    ? null
    : Math.max(1, Math.floor((available - reserve) / commitPerTurnMiB));
  const declared = Number.isFinite(declaredMax) && declaredMax >= 1 ? Math.floor(declaredMax) : null;
  const hard = Number.isFinite(hardCeiling) && hardCeiling >= 1 ? Math.floor(hardCeiling) : HARD_CEILING;

  const candidates = [
    ['cpu', cpuTerm],
    ...(memTerm === null ? [] : [['mem', memTerm]]),
    ...(declared === null ? [] : [['declared', declared]]),
    ['hard', hard],
  ];
  const binding = candidates.reduce((lowest, entry) => (entry[1] < lowest[1] ? entry : lowest), candidates[0]);
  const limit = Math.max(1, binding[1]);

  const missing = [];
  if (memTerm === null) missing.push('availableMiB');
  if (declared === null) missing.push('declared (capacity contract not answered)');

  return {
    limit,
    terms: {
      cpu: cpuTerm, mem: memTerm, declared, hard, binding: binding[0],
      cpuBudgetLogicalCpus: Number(cpuBudget.toFixed(2)),
    },
    inputs: {
      logicalCpus: logical,
      totalMiB: total,
      availableMiB: available,
      reserveMiB: reserve,
      cpuBudgetFraction,
      cpuPerTurn,
      commitPerTurnMiB,
      declaredMax: declared,
      hardCeiling: hard,
      availableSource,
    },
    sources: {
      cpuBudgetFraction: '84-calibration.md §4.1/§4.3 (41.5 % of 32 logical CPUs = the largest occupancy measured benign)',
      cpuPerTurn: '84-calibration.md §4.3 (tool-heavy turn = 1.68 logical CPUs; the worst measured class)',
      commitPerTurnMiB: '84-calibration.md §3 (403 MiB/turn, level-mean fit, CI 270-533)',
      reserveMiB: '84-calibration.md §4.4 / phone-gate.py:1110-1149 max(2 GiB, 12 %)',
      declaredMax: 'the node\'s own capacity contract (72-capacity-contract.md §2.1); phone-gate.py:939',
      hardCeiling: 'the admission governor\'s own slot ceiling on this host ("clamped 4-24")',
      availableSource,
    },
    note: `${binding[0]} term binds: ${limit}.`
      + (binding[0] === 'cpu'
        ? ` ${cpuBudget.toFixed(1)} logical CPUs of budget ÷ ${cpuPerTurn} per tool-heavy turn.`
        : '')
      + (missing.length === 0 ? '' : ` Unavailable inputs: ${missing.join(', ')}.`),
  };
}

/**
 * Available memory in MiB, and WHERE IT CAME FROM.
 *
 * On POSIX this is the quantity `84` §4.4 says to use — commit headroom, `CommitLimit −
 * Committed_AS`, read straight out of `/proc/meminfo` with no dependency. On Windows there is no
 * such file and Node exposes no commit API, so it falls back to `os.freemem()`, which is FREE
 * PHYSICAL, not commit headroom. That difference is published rather than hidden, and it is
 * tolerable here for one measured reason: `84` §5.3 found the memory term is 8× the CPU term on
 * both measured nodes, so it never binds — the CPU term and the declared ceiling are the whole
 * decision.
 */
export function readAvailableMemoryMiB({ platform = process.platform, fs = { readFileSync }, mem = os } = {}) {
  if (platform !== 'win32') {
    try {
      const text = fs.readFileSync('/proc/meminfo', 'utf8');
      const field = (name) => {
        const match = new RegExp(`^${name}:\\s+(\\d+)\\s+kB`, 'm').exec(text);
        return match === null ? null : Number(match[1]) / 1024;
      };
      const commitLimit = field('CommitLimit');
      const committed = field('Committed_AS');
      if (commitLimit !== null && committed !== null) {
        return { availableMiB: commitLimit - committed, source: '/proc/meminfo CommitLimit - Committed_AS (commit headroom)' };
      }
    } catch { /* no /proc on this platform: fall through to the portable reading */ }
  }
  return { availableMiB: mem.freemem() / (1024 * 1024), source: 'os.freemem() (free physical, not commit headroom)' };
}

/** The local, always-available half of the inputs. */
export function readLocalInputs({ cpus = os.cpus(), platform = process.platform, mem = os, fs = { readFileSync } } = {}) {
  const available = readAvailableMemoryMiB({ platform, fs, mem });
  return {
    logicalCpus: Array.isArray(cpus) ? cpus.length : 1,
    totalMiB: mem.totalmem() / (1024 * 1024),
    availableMiB: available.availableMiB,
    availableSource: available.source,
  };
}

/**
 * Fetch one JSON document from loopback with a hard timeout. No dependency, never throws.
 *
 * `agent: false` and `connection: close` are not politeness: this call is made from inside an
 * engine that must be able to exit, and a keep-alive socket parked in the global agent's pool is a
 * handle that keeps the event loop alive. A test suite that never exits is how that defect was
 * found here.
 *
 * @returns {Promise<object|null>}
 */
export function fetchJsonOnce({ url, timeoutMs = 4000, httpGet = get }) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => { if (!settled) { settled = true; resolve(value); } };
    try {
      const req = httpGet(url, { agent: false, headers: { connection: 'close' } }, (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          return done(null);
        }
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => {
          try { done(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { done(null); }
        });
        res.on('error', () => done(null));
      });
      req.on('error', () => done(null));
      req.setTimeout(timeoutMs, () => { try { req.destroy(); } catch { /* already gone */ } done(null); });
    } catch {
      done(null);
    }
  });
}

/**
 * The node's own published capacity contract, cached and single-flight.
 *
 * Every request that arrives over the route has ALREADY come through this gate, so this is a
 * loopback read of a document that was just produced for the caller. It is cached (default 30 s)
 * because `/mesh/health` is polled and a capacity read per poll is a subprocess per poll; it is
 * single-flight because N concurrent dispatches must not each start their own; and it fails soft
 * because a node whose gate is briefly down must keep accepting work.
 */
export function createDeclaredCapacityReader({
  url = 'http://127.0.0.1:3086/mesh/capacity',
  ttlMs = 30000,
  timeoutMs = 4000,
  nowMs = () => Date.now(),
  fetchJson = fetchJsonOnce,
} = {}) {
  let cache = null;
  let at = 0;
  let pending = null;
  let lastError = null;
  return {
    async read() {
      if (url === null || url === undefined || url === '') return { value: null, error: 'disabled', at: null };
      const now = nowMs();
      if (cache !== null && now - at < ttlMs) return { value: cache, error: lastError, at };
      if (pending === null) {
        pending = (async () => {
          const doc = await fetchJson({ url, timeoutMs });
          return doc;
        })().finally(() => { pending = null; });
      }
      const doc = await pending;
      at = nowMs();
      if (doc === null || typeof doc !== 'object' || doc.schema !== 1) {
        lastError = doc === null ? 'capacity contract did not answer' : `unexpected schema ${doc.schema}`;
        return { value: cache, error: lastError, at: cache === null ? null : at };
      }
      cache = doc;
      lastError = null;
      return { value: cache, error: null, at };
    },
  };
}

/** Pull the declared ceiling out of a schema-1 capacity object, or `null`. */
export function declaredMaxChildren(capacity) {
  const value = capacity?.accepts?.maxChildren;
  if (capacity?.accepts?.fleet === false) return 0;
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : null;
}
