/**
 * The frozen scoring of `docs/mesh/71-mesh-program.md` §2.2, written down once.
 *
 *   slots = min(floor((freeMiB - reserveMiB) / 160), maxSlots)   — minus governor.inUse
 *   reserveMiB = 3885      (the governor's own derivation: 12% of 31.6 GB, the number
 *                           docs/mesh/71-mesh-program.md §2.2 froze)
 *   maxSlots   = 24        (packages/plugin-health/lib/governor.js MAX_SLOTS_DEFAULT)
 *   160 MiB                (governor.js PER_SLOT_BYTES_DEFAULT — the measured cost of
 *                           one in-flight shell tool call: runner.js 57 MB + shell 103 MB)
 *
 * A node is eligible iff `slots - children >= 0` OR it has the highest `slots` on the
 * mesh, so a fleet bigger than every node still places, queued rather than refused.
 * A node with `freeGiB < 20 + worktreeGiB + 0.5 * children` is ineligible for `kind=fleet`.
 *
 * THE AMENDMENTS ON TOP OF THE MEMORY TERM. "AMENDMENT n" in this tree means the owner-approved
 * amendment `n` of `docs/mesh/76-broker.md` §10, and all five are written into the frozen
 * contract `docs/mesh/71-mesh-program.md` §2.2 - the docs and this code are the same thing said
 * twice, so a change here that is not there (or the reverse) is drift, and drift is a bug.
 *
 *  1. THE SLOT MODEL IS NOT PURELY MEMORY. `floor((freeMiB - 3885) / 160)` says how many
 *     heavy tool calls fit in the free memory; it says nothing about whether the CPU can
 *     run them. Measured 2026-09-15/16: one actively generating agent turn costs ~1 core
 *     (0.81 GB commit + ~1 core), and this laptop's paging threshold is 13-14 concurrent
 *     turns on 16 physical cores - i.e. floor(physical * 0.75) = 12, the measured number to
 *     within one. So `effective = min(memorySlots, floor(physical * 0.75))`, with a quarter
 *     of the cores left for the OS and the human. Without it the old model rated `secratary`
 *     (4 cores) at 24 slots - a 6x overstatement - and would have rated a 2-vCPU rental the
 *     same, which is a wrong thing to buy elastic capacity on. (§10.3)
 *  2. A SWAPPING NODE CANNOT ABSORB A SPIKE. If `mem.swapUsedPct >= 90` the node's free
 *     memory is memory it must fault back in, so its slots are halved for RANKING. It is a
 *     ranking penalty, never a gate: a node that is merely unattractive is still placeable
 *     when it is the only one left (the owner's rule is queue-never-amputate), and the
 *     halving is printed in the rationale. 90% is a first cut, to revisit once a node under
 *     load has been read.
 *
 * WORKED EXAMPLE THAT PINS THE SPEC (asserted in test/scoring.test.mjs): the §2.1 sample
 * reading has mem.freeMiB = 51000, and §2.2's example response reports `"score": 9` with
 * `"rationale": ["9 free slots of 24", ...]`. floor((51000 - 3885) / 160) = 294, capped at
 * 24, minus governor.inUse 15 = 9. The two documents agree, and this module reproduces
 * exactly that number.
 *
 * WHAT THIS MODULE DELIBERATELY DOES NOT DO
 * It does not read the clock, the filesystem or the network. Every function here is
 * arithmetic over an argument, which is what makes the decision explainable and testable.
 */

/** Measured cost of one in-flight heavy tool call (governor.js:53). */
export const PER_SLOT_MIB = 160;
/** The governor's reserve, frozen by §2.2 (12% of a 31.6 GB machine). */
export const RESERVE_MIB = 3885;
/** The governor's ceiling (governor.js:61). */
export const MAX_SLOTS = 24;
/** §2.2: a node with freeGiB < 20 is ineligible for kind=fleet. */
export const FLEET_DISK_FLOOR_GIB = 20;
/**
 * Disk the fleet itself needs beyond the floor, per child: scratch, logs and worktrees
 * that no caller declared. Half a gigabyte is a conservative allowance; the point of the
 * term is that a fixed 20 GiB floor does not scale with the fleet at all.
 */
export const PER_CHILD_DISK_GIB = 0.5;
/**
 * Cores one actively generating agent turn costs, as a fraction of the node's PHYSICAL
 * cores: a quarter of them are left for the OS and the human at the keyboard.
 * Measured: this laptop pages at 13-14 concurrent turns on 16 physical cores, and
 * floor(16 * 0.75) = 12 is that number to within one (2026-09-15/16).
 */
export const CORE_SLOT_FRACTION = 0.75;
/** Above this `mem.swapUsedPct` a node's free memory is memory it must fault back in. */
export const SWAP_PENALTY_PCT = 90;
/**
 * How much a `prefer` match is worth when ranking nodes, in slots-equivalent.
 *
 * NOT frozen by §2.2 — it is a dev decision recorded in docs/mesh/76-broker.md: a
 * preference must be worth something (otherwise the field is decoration) and must not be
 * worth everything (otherwise "prefer home" runs work on a saturated laptop while a
 * 20-slot desktop sits idle). 4 means a node 5+ slots freer wins regardless of preference.
 * The number appears in the rationale, so it is auditable rather than hidden.
 */
export const PREFERENCE_BONUS = 4;

const finiteNumber = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** `governor.inUse` when the gate measured one, else null (`governor` is null when the engine is down). */
export function governorInUse(reading) {
  const inUse = finiteNumber(reading?.governor?.inUse);
  return inUse === null || inUse < 0 ? null : inUse;
}

/** `mem.freeMiB` — the OS's own free-memory number, which §2.1 says is always measured. */
export function freeMiB(reading) {
  return finiteNumber(reading?.mem?.freeMiB);
}

/** `mem.swapUsedPct`, or null when the gate did not report one. */
export function swapUsedPct(reading) {
  const pct = finiteNumber(reading?.mem?.swapUsedPct);
  return pct === null || pct < 0 ? null : pct;
}

/**
 * `cpu.physical`, or null when the gate did not report one.
 *
 * An EXPLICIT 0 is a measurement ("this box has no free core to give") and is returned as 0;
 * only an absent or null field is "not measured". The two must not be collapsed: a node the
 * caller cannot see must be ranked as unmeasured, and a node measured at 0 cores must be
 * ranked as 0 - the whole point of the core term.
 */
export function physicalCores(reading) {
  const raw = reading?.cpu?.physical;
  if (raw === undefined || raw === null) return null;
  const physical = finiteNumber(raw);
  return physical === null || physical < 0 ? null : physical;
}

/** `cpu.logical` — the FALLBACK when physical is absent, never the first choice. */
export function logicalCpus(reading) {
  const raw = reading?.cpu?.logical;
  if (raw === undefined || raw === null) return null;
  const logical = finiteNumber(raw);
  return logical === null || logical < 0 ? null : logical;
}

/**
 * The read that froze the core term, as one comparison a reader can check.
 *
 * MEASURED 2026-09-15/16: this laptop (16 physical cores) starts paging at 13-14
 * concurrent generating turns. `floor(16 * 0.75)` = 12, the same as the measured threshold
 * to within one, so a quarter of the cores is what is held back for the OS and the human.
 * Change this function and the whole fleet's ranking changes; it is here so the change is
 * visible in one place and printed in the rationale.
 */
export function coreSlots(reading) {
  const physical = physicalCores(reading);
  const logical = logicalCpus(reading);
  const basis = physical !== null ? 'physical' : (logical !== null ? 'logical' : null);
  const cores = physical !== null ? physical : logical;
  const slots = cores === null ? null : Math.floor(cores * CORE_SLOT_FRACTION);
  const line = cores === null
    ? 'no cpu.physical or cpu.logical reading, so the core term is unknown and the memory term stands alone (a missing measurement is not a restriction)'
    : `${slots} core slot(s) of ${cores} ${basis}`
      + `${physical === null ? ' (cpu.physical was not reported, so cpu.logical is used and that is a LOOSER ceiling)' : ''}`
      + ` x ${CORE_SLOT_FRACTION}`;
  return { slots, cores, basis, physical, logical, line };
}

/**
 * The swap penalty: a node whose swap is at or above `SWAP_PENALTY_PCT` has its slots
 * halved for ranking. Never a refusal - the caller still places there when nothing better
 * exists - and `applied` is what the rationale prints.
 */
export function swapPenalty(memorySlots, reading) {
  const pct = swapUsedPct(reading);
  const applied = pct !== null && pct >= SWAP_PENALTY_PCT;
  const before = Math.max(0, memorySlots);
  const after = applied ? Math.floor(before / 2) : before;
  const line = applied
    ? `swap ${pct}% used (>= ${SWAP_PENALTY_PCT}%): free memory is memory that must be faulted back in, so ${before} slot(s) halved to ${after} - a ranking penalty, never a refusal`
    : pct === null
      ? 'mem.swapUsedPct not measured, so no swap penalty applies (a missing measurement is not a restriction)'
      : `swap ${pct}% used (< ${SWAP_PENALTY_PCT}%), so no swap penalty applies`;
  return { applied, pct, before, after, line };
}

/**
 * THE SCORE: both terms, and the swap penalty, as the numbers that were actually used.
 *
 * `effective = floor(min(memorySlots, coreSlots) / 2 when swapping else min(...))`
 *
 * The returned lines are the rationale lines for the two terms, so a small node's true
 * worth is printed rather than implied: `24 memory slot(s), 3 core slot(s) of 4 physical
 * x 0.75 -> effective 3` is the whole answer to "is this 2-vCPU rental worth renting?".
 *
 * @param {{memorySlots?:number, slots?:number, reading?:object|null}} arithmetic
 */
export function effectiveSlots(arithmetic) {
  const memorySlots = Math.max(0, arithmetic?.memorySlots ?? arithmetic?.slots ?? 0);
  const core = coreSlots(arithmetic?.reading);
  const coreSlotsValue = core.slots === null ? memorySlots : Math.max(0, core.slots);
  const min = Math.min(memorySlots, coreSlotsValue);
  const penalty = swapPenalty(min, arithmetic?.reading);
  const effective = penalty.after;
  const memoryLine = `${memorySlots} memory slot(s)`;
  const coreLine = core.line;
  const summary = `${memoryLine}, ${coreLine} -> effective ${effective}`
    + (penalty.applied ? ` (after the swap halving from ${min})` : '');
  return {
    memorySlots,
    coreSlots: core.slots,
    coreBasis: core.basis,
    coreCores: core.cores,
    min,
    swapApplied: penalty.applied,
    swapUsedPct: penalty.pct,
    effective,
    memoryLine,
    coreLine,
    swapLine: penalty.line,
    summary,
  };
}

/** GB/TB-free on the work volume, or null when the gate did not report it. */
export function diskFreeGiB(reading) {
  return finiteNumber(reading?.disk?.freeGiB);
}

/**
 * The slot arithmetic, as the numbers that were actually used.
 *
 * `slots` is the EFFECTIVE count: the memory term, capped by the core term, then halved if
 * the node is swapping (see `effectiveSlots()`). `memorySlots` is the memory term alone,
 * which is the number §2.2's worked example pins - the two agree whenever the core term is
 * not the binding one, which is exactly the intent.
 *
 * @param {object|null} reading a §2.1 capacity document, or null when there is none
 * @returns {{freeMiB:number|null, inUse:number|null, inUseAssumed:boolean, beforeCap:number|null,
 *            capped:number|null, raw:number, memorySlots:number, slots:number, effective:object,
 *            floored:boolean, known:boolean, arithmetic:string, line:string}}
 */
export function slotArithmetic(reading) {
  const free = freeMiB(reading);
  const inUse = governorInUse(reading);
  const assumedInUse = inUse === null ? 0 : inUse;
  const beforeCap = free === null ? null : Math.floor((free - RESERVE_MIB) / PER_SLOT_MIB);
  const capped = beforeCap === null ? null : Math.min(beforeCap, MAX_SLOTS);
  const raw = (capped === null ? 0 : capped) - assumedInUse;
  const memorySlots = Math.max(0, raw);
  const effective = effectiveSlots({ memorySlots, reading });
  const slots = effective.effective;
  const parts = [];
  if (free === null) {
    parts.push('no mem.freeMiB reading');
  } else {
    parts.push(`floor((${Math.round(free)} MiB free - ${RESERVE_MIB} MiB reserve) / ${PER_SLOT_MIB} MiB) = ${beforeCap} slot(s)`);
    parts.push(`capped at maxSlots=${MAX_SLOTS} -> ${capped}`);
  }
  parts.push(inUse === null
    ? 'no governor reading, so governor.inUse is treated as 0 (the engine may be down; a missing measurement is not a restriction)'
    : `minus governor.inUse=${inUse} -> ${raw}`);
  if (raw < 0) parts.push('floored at 0 slot(s) - a negative count is not a number of slots');
  const arithmetic = parts.join(', ');
  return {
    // The reading this arithmetic came from, so `effectiveSlots(arith)` re-derives the core
    // term and the swap penalty from the same document instead of losing them.
    reading,
    freeMiB: free,
    inUse,
    inUseAssumed: inUse === null,
    beforeCap,
    capped,
    raw,
    memorySlots,
    slots,
    effective,
    floored: raw < 0,
    known: free !== null,
    arithmetic,
    line: `${slots} slot(s) of at most ${MAX_SLOTS}: ${arithmetic}`,
  };
}

/**
 * §2.2's disk floor, scaled with the fleet, plus the caller's declared worktree.
 *
 * AMENDMENT 1 (owner-approved 2026-09-17): the floor alone does not scale with the fleet.
 * `requiredGiB = 20 + worktreeGiB + 0.5 * children` - one-shot needs the floor, a 6-child
 * fleet needs 23, a 12-child fleet needs 26. Measured reason: `zabz-tech-linux` had 20.8
 * GiB free against a flat 20 GiB floor, 0.8 GiB of margin, so one worktree flipped a node
 * into a silent overlap and the broker never said so. Half a gigabyte per child is the
 * conservative allowance for the scratch and logs a child writes that the caller has not
 * declared.
 */
export function diskRequirementGiB(task) {
  const worktree = finiteNumber(task?.worktreeGiB);
  const extra = worktree !== null && worktree > 0 ? worktree : 0;
  const children = normalizeChildren(task?.children);
  const perChild = PER_CHILD_DISK_GIB * children;
  return {
    requiredGiB: FLEET_DISK_FLOOR_GIB + extra + perChild,
    floorGiB: FLEET_DISK_FLOOR_GIB,
    worktreeGiB: extra,
    children,
    perChildGiB: perChild,
    perChildAllowanceGiB: PER_CHILD_DISK_GIB,
  };
}

/** `children` normalized to a positive integer; a one-shot run is one turn. */
export function normalizeChildren(value) {
  if (Number.isInteger(value) && value > 0) return value;
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed >= 1) return Math.floor(parsed);
  return 1;
}

/** `kind` normalized to one of the two frozen values. */
export function normalizeKind(value) {
  return value === 'fleet' ? 'fleet' : 'oneShot';
}

/** `prefer` normalized to home|office|null. */
export function normalizePrefer(value) {
  return value === 'home' || value === 'office' ? value : null;
}

/** `exclude` normalized to a list of non-empty strings. */
export function normalizeExclude(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((entry) => typeof entry === 'string' && entry.length > 0);
}

/**
 * Rank key for one candidate: free slots, a bounded preference bonus, then cheapness of
 * interference. Returned as a comparable tuple so the sort order is readable.
 */
export function rankingKey(candidate) {
  const preference = candidate.task?.prefer !== null && candidate.task?.prefer !== undefined
    && candidate.location === candidate.task.prefer
    ? PREFERENCE_BONUS
    : 0;
  const load = finiteNumber(candidate.load1);
  return {
    preference,
    score: candidate.score,
    // Lower load wins; an unmeasured load sorts last rather than first, because
    // "no reading" must never look like "idle".
    load: load === null ? Number.POSITIVE_INFINITY : load,
    order: candidate.index,
    name: candidate.node,
  };
}

/** Compare two `rankingKey()` tuples: the node that should win comes first. */
export function compareRanking(a, b) {
  if (a.score !== b.score) return b.score - a.score;
  if (a.preference !== b.preference) return b.preference - a.preference;
  if (a.load !== b.load) return a.load - b.load;
  if (a.order !== b.order) return a.order - b.order;
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}
