/**
 * The frozen arithmetic of docs/mesh/71-mesh-program.md §2.2, pinned by test.
 *
 *   node --test test/scoring.test.mjs
 *
 * The first test is the important one: it reproduces the §2.2 example response's own numbers
 * ("score": 9, "9 free slots of 24") from the §2.1 example reading (mem.freeMiB 51000) plus
 * governor.inUse 15. If the two frozen documents ever disagree with this module, that test
 * fails.
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';

import { createBroker } from '../lib/broker.js';
import {
  CORE_SLOT_FRACTION,
  MAX_SLOTS,
  PER_CHILD_DISK_GIB,
  PER_SLOT_MIB,
  RESERVE_MIB,
  FLEET_DISK_FLOOR_GIB,
  PREFERENCE_BONUS,
  SWAP_PENALTY_PCT,
  compareRanking,
  coreSlots,
  diskRequirementGiB,
  effectiveSlots,
  normalizeChildren,
  normalizeExclude,
  normalizeKind,
  normalizePrefer,
  rankingKey,
  slotArithmetic,
  swapPenalty,
} from '../lib/scoring.js';

test('§2.2 example: freeMiB 51000 with governor.inUse 15 gives the spec\'s own "9 free slots of 24"', () => {
  const reading = {
    schema: 1,
    node: 'zabz-tech',
    mem: { totalMiB: 65156, freeMiB: 51000 },
    governor: { budgetSlots: 24, inUse: 15, queued: 0 },
  };
  const arithmetic = slotArithmetic(reading);
  // This node reports totalMiB 65156, so its OWN reserve is max(2 GiB, 12% of 65156) = 7819 MiB,
  // not the laptop's frozen 3885: floor((51000 - 7819) / 160) = floor(269.88) = 269, capped at
  // 24, minus 15 = 9. The score the spec publishes is unchanged, which is why this example can
  // keep pinning the contract while the reserve becomes per-node (docs/mesh/86-authority.md §3).
  assert.equal(arithmetic.reserveMiB, 7819);
  assert.equal(arithmetic.reserveBasis, 'derived');
  assert.equal(arithmetic.beforeCap, 269);
  assert.equal(arithmetic.capped, MAX_SLOTS);
  assert.equal(arithmetic.raw, 9);
  assert.equal(arithmetic.slots, 9, 'the spec example response reports exactly this');
  assert.match(arithmetic.arithmetic, /51000 MiB free/);
  assert.match(arithmetic.arithmetic, new RegExp(`${arithmetic.reserveMiB} MiB reserve`));
  assert.match(arithmetic.arithmetic, new RegExp(`${PER_SLOT_MIB} MiB`));
  assert.match(arithmetic.arithmetic, /maxSlots=24/);
  assert.match(arithmetic.arithmetic, /minus governor\.inUse=15 -> 9/);
});

test('the constants are the governor\'s own derivation, and §2.2 froze them', () => {
  assert.equal(PER_SLOT_MIB, 160);
  assert.equal(RESERVE_MIB, 3885);
  assert.equal(MAX_SLOTS, 24);
  assert.equal(FLEET_DISK_FLOOR_GIB, 20);
});

test('a node with no governor reading assumes inUse 0 and says so', () => {
  const arithmetic = slotArithmetic({ mem: { freeMiB: 17575 }, governor: null, accepts: { oneShot: true } });
  assert.equal(arithmetic.inUse, null);
  assert.equal(arithmetic.inUseAssumed, true);
  assert.equal(arithmetic.beforeCap, 85);
  assert.equal(arithmetic.slots, MAX_SLOTS);
  assert.match(arithmetic.arithmetic, /treated as 0/);
  assert.match(arithmetic.arithmetic, /engine may be down/);
});

test('the budget is capped at maxSlots no matter how much memory is free', () => {
  const arithmetic = slotArithmetic({ mem: { freeMiB: 500_000 }, governor: { inUse: 0 } });
  assert.equal(arithmetic.beforeCap, 3100);
  assert.equal(arithmetic.slots, MAX_SLOTS);
});

test('zero free memory gives 0 slots, floored, not a negative number of slots', () => {
  const arithmetic = slotArithmetic({ mem: { freeMiB: 0 }, governor: { inUse: 0 } });
  assert.equal(arithmetic.beforeCap, -25);
  assert.equal(arithmetic.raw, -25);
  assert.equal(arithmetic.slots, 0);
  assert.equal(arithmetic.floored, true);
  assert.match(arithmetic.arithmetic, /floored at 0 slot\(s\)/);
});

test('a missing reading gives 0 slots and says the reading is missing', () => {
  const arithmetic = slotArithmetic(null);
  assert.equal(arithmetic.known, false);
  assert.equal(arithmetic.slots, 0);
  assert.match(arithmetic.arithmetic, /no mem\.freeMiB reading/);
});

test('the fleet disk requirement is the 20 GiB floor plus the declared worktree', () => {
  assert.equal(diskRequirementGiB({ kind: 'fleet' }).requiredGiB, 20.5, 'one-shot counts as one child, and the per-child term still applies');
  assert.equal(diskRequirementGiB({ kind: 'fleet', worktreeGiB: 2 }).requiredGiB, 22.5);
  assert.equal(diskRequirementGiB({ kind: 'fleet', worktreeGiB: null }).requiredGiB, 20.5);
  assert.equal(diskRequirementGiB({ kind: 'fleet', worktreeGiB: -5 }).requiredGiB, 20.5);
});

test('task normalization accepts the frozen values and repairs the rest', () => {
  assert.equal(normalizeKind('fleet'), 'fleet');
  assert.equal(normalizeKind('oneShot'), 'oneShot');
  assert.equal(normalizeKind('anything-else'), 'oneShot');
  assert.equal(normalizeChildren(6), 6);
  assert.equal(normalizeChildren('6'), 6);
  assert.equal(normalizeChildren(0), 1);
  assert.equal(normalizeChildren(-3), 1);
  assert.equal(normalizeChildren(undefined), 1);
  assert.equal(normalizePrefer('home'), 'home');
  assert.equal(normalizePrefer('office'), 'office');
  assert.equal(normalizePrefer('mars'), null);
  assert.deepEqual(normalizeExclude(['a', 'b', 3, '', null]), ['a', 'b']);
  assert.deepEqual(normalizeExclude('nope'), []);
});

test('ranking: more free slots wins, an unmeasured load never looks idle, ties are stable', () => {
  const task = { prefer: null };
  const candidate = (over) => ({ ...over, task });
  const rich = candidate({ score: 9, load1: 5, index: 1, node: 'b', location: 'office' });
  const poor = candidate({ score: 4, load1: 0.1, index: 0, node: 'a', location: 'home' });
  assert.ok(compareRanking(rankingKey(rich), rankingKey(poor)) < 0, 'score outranks load');

  const unmeasured = candidate({ score: 4, load1: null, index: 0, node: 'a', location: null });
  const measured = candidate({ score: 4, load1: 3, index: 1, node: 'b', location: null });
  assert.ok(compareRanking(rankingKey(measured), rankingKey(unmeasured)) < 0, 'a measured load beats an unknown one');

  const sameA = candidate({ score: 4, load1: 1, index: 0, node: 'a', location: null });
  const sameB = candidate({ score: 4, load1: 1, index: 1, node: 'b', location: null });
  assert.ok(compareRanking(rankingKey(sameA), rankingKey(sameB)) < 0, 'roster order breaks the last tie');
});

test('a preference match is worth a bounded bonus and never overrides a much freer node', () => {
  const task = { prefer: 'home' };
  const home = { score: 4, load1: 1, index: 0, node: 'zabz-yoga', location: 'home', task };
  const office = { score: 4, load1: 1, index: 1, node: 'zabz-tech', location: 'office', task };
  assert.equal(rankingKey(home).preference, PREFERENCE_BONUS);
  assert.equal(rankingKey(office).preference, 0);
  assert.ok(compareRanking(rankingKey(home), rankingKey(office)) < 0, 'equal scores: the preferred location wins');

  const muchFreer = { score: 4 + PREFERENCE_BONUS + 1, load1: 1, index: 1, node: 'zabz-tech', location: 'office', task };
  assert.ok(compareRanking(rankingKey(muchFreer), rankingKey(home)) < 0, 'a node 5+ slots freer wins regardless of preference');
});

// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 1 — the fleet disk floor scales with the fleet
// (owner-approved 2026-09-17; evidence: `zabz-tech-linux` had 20.8 GiB free against a flat
// 20 GiB floor, 0.8 GiB of margin, so one worktree flipped it into a silent overlap)
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 1 the fleet disk floor scales with the fleet: 20 + worktree + 0.5 per child', () => {
  assert.equal(PER_CHILD_DISK_GIB, 0.5);
  assert.equal(diskRequirementGiB({ kind: 'fleet', children: 1 }).requiredGiB, 20.5, 'a 1-child fleet needs 20.5 GiB');
  assert.equal(diskRequirementGiB({ kind: 'fleet', children: 1, worktreeGiB: 2 }).requiredGiB, 22.5, '20 + 2 + 0.5');
  assert.equal(diskRequirementGiB({ kind: 'fleet', children: 6 }).requiredGiB, 23, 'a 6-child fleet needs 23 GiB');
  assert.equal(diskRequirementGiB({ kind: 'fleet', children: 6, worktreeGiB: 2 }).requiredGiB, 25, '20 + 2 + 3');
  assert.equal(diskRequirementGiB({ kind: 'fleet', children: 12 }).requiredGiB, 26, 'a 12-child fleet needs 26 GiB');
});

test('AMENDMENT 1 the real numbers: 20.8 GiB free passes a 1-child fleet and fails a 12-child one', () => {
  // The live measurement that forced this amendment: `zabz-tech-linux` reported
  // disk.freeGiB 20.8 (GET /mesh/capacity, 2026-09-16 23:34Z) - 0.8 GiB above the old flat
  // floor, so a fleet of any size "passed" a gate that only asked about 20 GiB.
  const free = 20.8;
  const one = diskRequirementGiB({ kind: 'fleet', children: 1, worktreeGiB: 0 });
  const twelve = diskRequirementGiB({ kind: 'fleet', children: 12, worktreeGiB: 0 });
  assert.equal(free >= one.requiredGiB, true, `${free} GiB >= ${one.requiredGiB} GiB: a 1-child fleet fits`);
  assert.equal(free >= twelve.requiredGiB, false, `${free} GiB < ${twelve.requiredGiB} GiB: a 12-child fleet does not`);
});

// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 3 — the score is min(memory slots, cores x 0.75), and both terms are printed
// (owner-approved 2026-09-17; evidence: ~1 core per generating agent turn, and this
// laptop's paging threshold of 13-14 concurrent turns on 16 physical cores)
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 3 core slots are 0.75 x PHYSICAL cores, and never more than that', () => {
  assert.equal(CORE_SLOT_FRACTION, 0.75);
  assert.equal(coreSlots({ cpu: { logical: 32, physical: 24 } }).slots, 18);
  assert.equal(coreSlots({ cpu: { logical: 32, physical: 24 } }).basis, 'physical');
  assert.equal(coreSlots({ cpu: { logical: 4, physical: 4 } }).slots, 3);
  assert.equal(coreSlots({ cpu: { logical: 22, physical: 16 } }).slots, 12, 'the 16-core laptop: the measured paging threshold was 13-14');
  assert.equal(coreSlots({ cpu: { logical: 12, physical: 6 } }).slots, 4);
  assert.equal(coreSlots({ cpu: { logical: 12, physical: 1 } }).slots, 0, 'a 1-core box has no room for an agent turn and keeps none of it');
});

test('AMENDMENT 3 cpu.logical is the fallback when physical is absent, and the rationale says which was used', () => {
  const logicalOnly = coreSlots({ cpu: { logical: 8 } });
  assert.equal(logicalOnly.slots, 6);
  assert.equal(logicalOnly.basis, 'logical');
  assert.match(logicalOnly.line, /8 logical/);
  assert.match(logicalOnly.line, /LOOSER ceiling/);

  const none = coreSlots({ cpu: {} });
  assert.equal(none.slots, null);
  assert.match(none.line, /no cpu\.physical or cpu\.logical reading/);

  // No CPU reading at all: the core term does not restrict, the memory term stands alone,
  // and a missing measurement never silently becomes a zero.
  const arithmetic = slotArithmetic({ mem: { freeMiB: 51000 }, governor: { inUse: 15 } });
  assert.equal(arithmetic.memorySlots, 9);
  assert.equal(arithmetic.slots, 9);
  assert.ok(arithmetic.effective.coreLine.includes('no cpu.physical or cpu.logical reading'), 'the missing core reading is named');
});

test('AMENDMENT 3 the effective score is the smaller term, so a small box is not worth what its memory says', () => {
  const small = slotArithmetic({
    cpu: { logical: 2, physical: 2 },
    mem: { freeMiB: 64 * 1024, swapUsedPct: 0 },
    governor: { inUse: 0 },
  });
  assert.equal(small.memorySlots, 24, '64 GiB of free memory claims the full 24 slots');
  assert.equal(small.effective.coreSlots, 1, '2 physical cores x 0.75 = 1');
  assert.equal(small.slots, 1, 'the core term is what binds');
  assert.equal(small.effective.summary, '24 memory slot(s), 1 core slot(s) of 2 physical x 0.75 -> effective 1');

  const big = slotArithmetic({
    cpu: { logical: 32, physical: 24 },
    mem: { freeMiB: 64 * 1024, swapUsedPct: 0 },
    governor: { inUse: 0 },
  });
  assert.equal(big.memorySlots, 24);
  assert.equal(big.slots, 18, '24 memory slots, 18 core slots: memory binds, and 18 is the honest ceiling');

  // The two live shapes this amendment exists for, printed the way the rationale prints them.
  const secratary = slotArithmetic({ cpu: { logical: 4, physical: 4 }, mem: { freeMiB: 16973, swapUsedPct: 99.9 }, governor: { inUse: 0 } });
  assert.equal(secratary.memorySlots, 24);
  assert.equal(secratary.effective.coreSlots, 3);
  const yoga = slotArithmetic({ cpu: { logical: 22, physical: 16 }, mem: { freeMiB: 14818, swapUsedPct: 0 }, governor: { inUse: 1 } });
  assert.equal(yoga.memorySlots, 23);
  assert.equal(yoga.slots, 12);
  assert.match(yoga.effective.summary, /23 memory slot\(s\), 12 core slot\(s\) of 16 physical x 0\.75 -> effective 12/);
});

// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 2 — a swapping node cannot absorb a spike; halve it for RANKING, never refuse
// (owner-approved 2026-09-17; evidence: `secratary` reported swapUsedPct 99.9 - 4,092 of
// 4,095 MiB - so its freeMiB counted memory it must fault back in)
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 2 a node at or above 90% swap has its effective slots halved, and the line says so', () => {
  assert.equal(SWAP_PENALTY_PCT, 90);
  const swapPenaltyResult = swapPenalty(24, { mem: { swapUsedPct: 99.9 } });
  assert.equal(swapPenaltyResult.applied, true);
  assert.equal(swapPenaltyResult.after, 12);
  assert.match(swapPenaltyResult.line, /swap 99\.9% used/);
  assert.match(swapPenaltyResult.line, /24 slot\(s\) halved to 12/);
  assert.match(swapPenaltyResult.line, /never a refusal/);

  assert.equal(swapPenalty(24, { mem: { swapUsedPct: 90 } }).applied, true, '90% is the threshold itself, and it is inclusive');
  assert.equal(swapPenalty(24, { mem: { swapUsedPct: 89.9 } }).applied, false, 'just under the threshold is not penalised');
  assert.equal(swapPenalty(24, { mem: { swapUsedPct: null } }).applied, false, 'a missing swap reading is not a penalty');
  assert.match(swapPenalty(24, { mem: { swapUsedPct: null } }).line, /not measured/);
});

test('AMENDMENT 2 secratary\'s live numbers: 24 memory slots, 3 core slots, halved to 1 by 99.9% swap', () => {
  // The live reading (GET /mesh/capacity from the authority, 2026-09-16 23:34Z):
  // cpu 4 logical / 4 physical, mem.freeMiB 16973, mem.swapUsedPct 99.9, governor.inUse 0.
  const arithmetic = slotArithmetic({
    cpu: { logical: 4, physical: 4 },
    mem: { freeMiB: 16973, swapUsedPct: 99.9 },
    governor: { inUse: 0 },
  });
  assert.equal(arithmetic.memorySlots, 24);
  assert.equal(arithmetic.effective.coreSlots, 3);
  assert.equal(arithmetic.effective.swapApplied, true);
  assert.equal(arithmetic.slots, 1, '3 core slots halved by swap is 1 - the honest worth of a 4-core box that is already swapping');
});

// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 3, second half — a node whose effective slots are 0 is still PLACEABLE
// (queue, never amputate: it must rank last, never be refused)
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 3 a node with 64 GiB free and 0 cores ranks below one with 8 GiB free and 8 cores', () => {
  const memoryOnly = slotArithmetic({
    cpu: { logical: 0, physical: 0 },
    mem: { freeMiB: 64 * 1024, swapUsedPct: 0 },
    governor: { inUse: 0 },
  });
  const coreRich = slotArithmetic({
    cpu: { logical: 8, physical: 8 },
    mem: { freeMiB: 8192, swapUsedPct: 0 },
    governor: { inUse: 0 },
  });
  assert.equal(memoryOnly.memorySlots, 24, '64 GiB of free memory is 24 memory slots');
  assert.equal(memoryOnly.slots, 0, '0 cores is 0 core slots, and the smaller term wins');
  assert.equal(coreRich.memorySlots, 24, '8 GiB is still above the 24-slot cap');
  assert.equal(coreRich.slots, 6, '8 physical cores x 0.75 = 6');

  const task = { prefer: null };
  const a = { score: memoryOnly.slots, load1: 0, index: 0, node: 'fat-and-toothless', location: 'office', task };
  const b = { score: coreRich.slots, load1: 0, index: 1, node: 'small-but-real', location: 'office', task };
  assert.ok(compareRanking(rankingKey(b), rankingKey(a)) < 0, 'the node that can actually run the work wins');
});

test('AMENDMENT 3 effective slots are never negative - 0 is the floor, and 0 slots is a queue not a refusal', () => {
  const zero = slotArithmetic({ cpu: { logical: 1, physical: 1 }, mem: { freeMiB: 0, swapUsedPct: 0 }, governor: { inUse: 0 } });
  assert.equal(zero.memorySlots, 0);
  assert.equal(zero.effective.coreSlots, 0);
  assert.equal(zero.slots, 0);
  assert.ok(zero.slots >= 0, 'a negative count is not a number of slots');
});

// ─────────────────────────────────────────────────────────────────────────────
// PLACEMENT HARDENING (docs/mesh/126-placement-hardening.md)
//
// These exercise the DECISION with an injected capacity reader, so they are
// hermetic: no socket, no port, no clock. They are written against behaviour
// (the node the broker names, the rationale text, the lease ids) and not against
// any new export, so the same file fails on the unfixed broker for the right
// reason rather than on a missing symbol.
// ─────────────────────────────────────────────────────────────────────────────

/** A roster row good enough for `createBroker` (which does not validate - `config.js` does). */
const row = (node, dispatch, index = 0) => ({
  node,
  baseUrl: 'http://127.0.0.1:1',
  fqdn: `${node}.tail93e6e6.ts.net`,
  location: null,
  excluded: false,
  dispatch,
  index,
});

/**
 * A §2.1 document whose EFFECTIVE slots are `floor(physical * 0.75)`: free memory is
 * deliberately far above the 24-slot cap, so `physical` is the only lever the test needs.
 */
function capacityDoc(node, { physical = 16, diskGiB = 100, accepts = { oneShot: true, fleet: true, maxChildren: 12 }, swapUsedPct = 0 } = {}) {
  return {
    schema: 1,
    node,
    mem: { totalMiB: 60000, freeMiB: 100000, swapUsedPct },
    cpu: { logical: physical, physical },
    disk: { freeGiB: diskGiB, workRoot: '/tmp/work' },
    governor: { budgetSlots: 24, inUse: 0, queued: 0 },
    accepts,
  };
}

/** An injected reader driven by a per-node spec, so no network is touched. */
function readerFor(specs) {
  return async ({ node }) => {
    const spec = specs[node.node];
    if (spec === undefined) {
      return { ok: false, state: 'unreachable', error: 'not in this test\'s mesh', errorKind: 'refused', retried: false };
    }
    return {
      ok: true,
      state: spec.state ?? 'ok',
      retryWasFast: spec.retryWasFast === true,
      retried: spec.retried === true,
      doc: spec.doc,
      latencyMs: spec.latencyMs ?? 5,
      elapsedMs: spec.elapsedMs ?? 5,
    };
  };
}

const place = (broker, task, extra = {}) => broker.place({ task, ...extra });

test('I1 the same requestId twice returns the SAME lease and node; a different requestId issues a new lease', async () => {
  const broker = createBroker({
    nodes: [row('solo', { v1: true, measuredAt: '2026-09-29', evidence: 'measured' })],
    now: () => 1_000,
    readCapacity: readerFor({ solo: { doc: capacityDoc('solo') } }),
  });
  const first = await place(broker, { kind: 'oneShot', children: 1 }, { requestId: 'req-A' });
  const replay = await place(broker, { kind: 'oneShot', children: 1 }, { requestId: 'req-A' });

  assert.equal(replay.lease, first.lease, 'a repeated requestId must NOT issue a second lease');
  assert.equal(replay.node, first.node);
  assert.equal(replay.requestId, 'req-A');
  assert.equal(replay.idempotentReplay, true);
  assert.ok(replay.rationale.some((line) => line.includes('NO second lease was issued')), 'the replay is stated, not silent');
  assert.equal(broker.leases.size(), 1, 'exactly one lease exists after a replay');

  const other = await place(broker, { kind: 'oneShot', children: 1 }, { requestId: 'req-B' });
  assert.notEqual(other.lease, first.lease, 'two different requestIds must still produce two leases');
  assert.equal(other.idempotentReplay, undefined);
  assert.equal(broker.leases.size(), 2);
});

test('I4 a node that missed the read deadline (a cold-start miss) is not ranked below a node that cannot take the work', async () => {
  const broker = createBroker({
    nodes: [
      // A: the measured zabz-tech shape - plenty of slots, but the FLEET disk gate fails, so it
      // is only reachable through the `queued` arena. Its first read missed the deadline and the
      // retry answered fast: a COLD-START miss, which must NOT demote it.
      row('cold-but-capable', { v1: true, measuredAt: '2026-09-29', evidence: 'measured' }, 0),
      // B: cannot take the work at all - the gate declares accepts.fleet=false.
      row('cannot-take-fleets', { v1: true, measuredAt: '2026-09-29', evidence: 'measured' }, 1),
    ],
    now: () => 0,
    readCapacity: readerFor({
      'cold-but-capable': { state: 'slow', retryWasFast: true, retried: true, latencyMs: 120, elapsedMs: 1887, doc: capacityDoc('cold-but-capable', { physical: 16, diskGiB: 5, accepts: { oneShot: true, fleet: true, maxChildren: 12 } }) },
      'cannot-take-fleets': { doc: capacityDoc('cannot-take-fleets', { physical: 8, diskGiB: 100, accepts: { oneShot: true, fleet: false, maxChildren: 12, reason: 'no governor lease directory on this node' } }) },
    }),
  });
  const response = await place(broker, { kind: 'fleet', children: 1 });
  assert.equal(response.node, 'cold-but-capable', 'a cold-start latency miss is not a reason to lose to a node that cannot take the work');
  assert.equal(response.blockedBy.includes('accepts'), false);
  assert.ok(response.rationale.some((line) => line.startsWith('cold-but-capable: ') && line.includes('COLD-START')), `the cold miss is named as the non-reason it is: ${response.rationale.join(' | ')}`);
});

test('I5 an unmeasured-transport node loses to a measured-working node even with more slots', async () => {
  const broker = createBroker({
    nodes: [
      row('measured-working', { v1: true, measuredAt: '2026-09-29', evidence: 'a child completed' }, 0),
      row('never-measured', { v1: null, measuredAt: null, evidence: null }, 1),
    ],
    now: () => 0,
    readCapacity: readerFor({
      'measured-working': { doc: capacityDoc('measured-working', { physical: 8 }) },
      'never-measured': { doc: capacityDoc('never-measured', { physical: 16 }) },
    }),
  });
  const response = await place(broker, { kind: 'oneShot', children: 1 });
  assert.equal(response.node, 'measured-working', 'measured-working outranks unmeasured even with fewer slots');
  assert.ok(response.rationale.some((line) => line.startsWith('never-measured: ') && line.includes('transport v1 unmeasured')), `the loser is named as unmeasured: ${response.rationale.join(' | ')}`);
});

test('I6 the per-node fleet cap blocks another fleet and the rationale says so', async () => {
  const broker = createBroker({
    nodes: [row('fleet-node', { v1: true, measuredAt: '2026-09-29', evidence: 'measured' })],
    now: () => 0,
    readCapacity: readerFor({ 'fleet-node': { doc: capacityDoc('fleet-node', { physical: 16, accepts: { oneShot: true, fleet: true, maxChildren: 12 } }) } }),
  });
  const firstFour = [];
  for (let index = 0; index < 4; index += 1) {
    firstFour.push(await place(broker, { kind: 'fleet', children: 1 }));
  }
  assert.equal(firstFour.every((response) => response.position === 0), true, 'the first four fleets fit and start');

  const fifth = await place(broker, { kind: 'fleet', children: 1 });
  assert.equal(fifth.node, 'fleet-node', 'the cap queues, it never amputates');
  assert.ok(fifth.position > 0, 'the fifth concurrent fleet lease is queued, not started');
  assert.equal(fifth.blockedBy.includes('fleet-cap'), true, `blockedBy names the cap: ${JSON.stringify(fifth.blockedBy)}`);
  assert.ok(fifth.rationale.some((line) => line.includes('fleet concurrency cap')), `the cap is legible in the rationale: ${fifth.rationale.join(' | ')}`);
});

test('I7 a caller-excluded node ranks below a node the caller did not exclude, in the queued fallback', async () => {
  const broker = createBroker({
    nodes: [
      row('local-and-excluded', { v1: true, measuredAt: '2026-09-29', evidence: 'measured' }, 0),
      row('remote-and-allowed', { v1: true, measuredAt: '2026-09-29', evidence: 'measured' }, 1),
    ],
    now: () => 0,
    readCapacity: readerFor({
      // Neither can take a fleet (accepts.fleet=false), so both are in the `queued` arena and
      // the ordering term is what decides. The excluded node has MORE slots; the caller's
      // exclusion must still win, because that is the caller's expressed preference.
      'local-and-excluded': { doc: capacityDoc('local-and-excluded', { physical: 16, accepts: { oneShot: true, fleet: false, maxChildren: 12 } }) },
      'remote-and-allowed': { doc: capacityDoc('remote-and-allowed', { physical: 8, accepts: { oneShot: true, fleet: false, maxChildren: 12 } }) },
    }),
  });
  const response = await place(broker, { kind: 'fleet', children: 1, exclude: ['local-and-excluded'] });
  assert.equal(response.node, 'remote-and-allowed', 'the caller\'s exclusion orders the result instead of being a comment');
  assert.equal(response.excluded >= 1, true);
  assert.ok(response.rationale.some((line) => line.startsWith('local-and-excluded: ') && line.includes('excluded by the caller')), `the excluded node still explains itself: ${response.rationale.join(' | ')}`);
});

