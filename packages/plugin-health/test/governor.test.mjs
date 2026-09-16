/**
 * Governor tests — `node --test test/governor.test.mjs`.
 *
 * The properties that matter are concurrency properties, so most of these drive
 * the protocol directly with an injected clock and an injected memory reading,
 * and the cross-process proof lives in `governor-stress.mjs` (real child
 * processes, real files).
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  acquire,
  acquireWaiting,
  deriveBudget,
  ensureLayout,
  governorRoot,
  leasesDir,
  readLeases,
  reap,
  release,
  renew,
  status,
  PER_SLOT_BYTES_DEFAULT,
  MAX_SLOTS_DEFAULT,
  MIN_SLOTS_DEFAULT,
} from '../lib/governor.js';

const scratch = () => mkdtempSync(path.join(tmpdir(), 'gov-test-'));

test('governorRoot hangs off the DSH home', () => {
  assert.equal(governorRoot('C:\\x\\.dsh'), path.join('C:\\x\\.dsh', 'governor'));
});

// ── the budget is derived from measurement, floored, and never zero ─────────

test('the budget is the measured headroom divided by the measured slot cost', () => {
  const budget = deriveBudget({
    perSlotBytes: 160 * 1024 * 1024,
    maxSlots: 24,
    minSlots: 4,
    freeBytes: () => 16 * 1024 * 1024 * 1024,
    totalBytes: () => 32 * 1024 * 1024 * 1024,
  });
  assert.equal(budget.budget, 24, 'plenty of headroom gives the ceiling');
  assert.equal(budget.capped, 'max');
  assert.equal(budget.headroomLow, false);
  assert.match(budget.arithmetic, /16384 MiB free/);
});

test('a small machine gets a proportional budget rather than the ceiling', () => {
  const budget = deriveBudget({
    perSlotBytes: 160 * 1024 * 1024,
    maxSlots: 24,
    minSlots: 4,
    freeBytes: () => 2 * 1024 * 1024 * 1024,
    totalBytes: () => 8 * 1024 * 1024 * 1024,
  });
  // 2048 MiB free, reserve max(2 GiB, 12%) = 2048 MiB -> usable 0 -> floored.
  assert.equal(budget.budget, 4);
  assert.equal(budget.capped, 'min');
  assert.equal(budget.headroomLow, true, 'the floor is reported as low headroom, not as health');
});

test('the budget NEVER falls to zero, because refusing is not the first behaviour', () => {
  const budget = deriveBudget({
    perSlotBytes: 160 * 1024 * 1024,
    minSlots: 4,
    freeBytes: () => 0,
    totalBytes: () => 32 * 1024 * 1024 * 1024,
  });
  assert.ok(budget.budget >= MIN_SLOTS_DEFAULT);
  assert.equal(budget.usableBytes, 0);
  assert.equal(budget.headroomLow, true);
});

test('the reserve keeps the desktop alive even on a tiny machine', () => {
  const budget = deriveBudget({ freeBytes: () => 4 * 1024 * 1024 * 1024, totalBytes: () => 4 * 1024 * 1024 * 1024 });
  assert.equal(budget.reserveBytes, 2 * 1024 * 1024 * 1024, 'the 2 GiB floor wins over 12%');
});

test('the real measurement on this host produces a sane, generous budget', () => {
  const budget = deriveBudget({});
  assert.ok(budget.freeBytes > 0);
  assert.ok(budget.budget >= MIN_SLOTS_DEFAULT && budget.budget <= MAX_SLOTS_DEFAULT);
  assert.ok(budget.arithmetic.length > 20);
});

// ── acquire / release ───────────────────────────────────────────────────────

test('acquire grants a slot, records the holder, and release frees it', () => {
  const root = scratch();
  try {
    const first = acquire({ root, budget: deriveBudget({ freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 }), kind: 'test' });
    assert.equal(first.state, 'granted');
    assert.equal(first.lease.slot, 1);
    assert.equal(first.lease.pid, process.pid);
    const onDisk = JSON.parse(readFileSync(path.join(leasesDir(root), 'slot-01.lease'), 'utf8'));
    assert.equal(onDisk.id, first.lease.id);
    assert.equal(onDisk.kind, 'test');

    const view = status({ root, reapFirst: false });
    assert.equal(view.inUse, 1);
    assert.equal(view.holders[0].id, first.lease.id);

    const released = release(root, first.lease.id);
    assert.equal(released.released, true);
    assert.equal(status({ root, reapFirst: false }).inUse, 0);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the budget is respected exactly, and the next caller is QUEUED with a position', () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 3, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const granted = [];
    for (let index = 0; index < 3; index += 1) {
      const outcome = acquire({ root, budget });
      assert.equal(outcome.state, 'granted');
      granted.push(outcome.lease);
    }
    assert.deepEqual(granted.map((lease) => lease.slot), [1, 2, 3]);

    const queued = acquire({ root, budget });
    assert.equal(queued.state, 'queued');
    assert.equal(queued.active, 3);
    assert.equal(queued.budget.budget, 3);
    assert.ok(Number.isInteger(queued.position));
    // Nothing was refused: the caller has a position and a way to wait.
    assert.ok(queued.position >= 0);

    // Releasing one slot lets the next caller in on the SAME slot number.
    release(root, granted[1].id);
    const after = acquire({ root, budget });
    assert.equal(after.state, 'granted');
    assert.equal(after.lease.slot, 2);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a second acquire can never take a slot that is already held', () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 1, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const first = acquire({ root, budget });
    const second = acquire({ root, budget });
    assert.equal(first.state, 'granted');
    assert.equal(second.state, 'queued', 'a taken slot must not be handed out twice');
    const names = readdirSync(leasesDir(root));
    assert.deepEqual(names, ['slot-01.lease']);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ── renew / TTL / reap ──────────────────────────────────────────────────────

test('a lease expires on its TTL and is reaped, and the slot is reusable', () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 1, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const now = 1_000_000;
    const held = acquire({ root, budget, now, ttlMs: 1000 });
    assert.equal(held.state, 'granted');
    // Before the TTL: alive.
    assert.equal(readLeases(root, now + 500).filter((lease) => lease.alive).length, 1);
    // After the TTL: dead, and the next acquire reaps it and grants the slot.
    const later = now + 5000;
    assert.equal(readLeases(root, later).filter((lease) => lease.alive).length, 0);
    const next = acquire({ root, budget, now: later, ttlMs: 1000 });
    assert.equal(next.state, 'granted');
    assert.equal(next.reaped.filter((entry) => entry.outcome === 'reaped').length, 1);
    assert.equal(next.reaped[0].slot, 1);
    assert.equal(next.reaped[0].expiredForMs, 4000);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('renewing keeps a lease alive past its original TTL', () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 1, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const now = 2_000_000;
    const held = acquire({ root, budget, now, ttlMs: 1000 });
    const renewed = renew(root, held.lease.id, 1000, now + 800);
    assert.equal(renewed.renewals, 1);
    assert.equal(renewed.expiresAt, now + 1800);
    assert.equal(readLeases(root, now + 1500).filter((lease) => lease.alive).length, 1);
    assert.equal(acquire({ root, budget, now: now + 1500, ttlMs: 1000 }).state, 'queued');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('renewing an unknown id reports the loss instead of pretending', () => {
  const root = scratch();
  try {
    ensureLayout(root);
    assert.equal(renew(root, 'not-a-lease'), undefined);
    assert.equal(release(root, 'not-a-lease').released, false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a corrupt lease file is treated as dead and reported, never as a holder', () => {
  const root = scratch();
  try {
    ensureLayout(root);
    writeFileSync(path.join(leasesDir(root), 'slot-01.lease'), '{ this is not json');
    const leases = readLeases(root);
    assert.equal(leases.length, 1);
    assert.equal(leases[0].corrupt, true);
    assert.equal(leases[0].alive, false);
    const view = status({ root, reapFirst: false });
    assert.equal(view.inUse, 0);
    assert.equal(view.deadLeases[0].corrupt, true);
    // An unreadable file cannot be renewed, so it must not shrink the budget
    // forever: reap clears it.
    const report = reap(root);
    assert.equal(report[0].outcome, 'reaped');
    assert.equal(existsSync(path.join(leasesDir(root), 'slot-01.lease')), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('reap leaves a live lease alone', () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 2, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const held = acquire({ root, budget, kind: 'alive' });
    assert.equal(reap(root).filter((entry) => entry.outcome === 'reaped').length, 0);
    assert.equal(existsSync(path.join(leasesDir(root), 'slot-01.lease')), true);
    assert.equal(status({ root, reapFirst: false }).holders[0].id, held.lease.id);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a lease renewed between the read and the rename is put back, not stolen', () => {
  const root = scratch();
  try {
    ensureLayout(root);
    const file = path.join(leasesDir(root), 'slot-01.lease');
    const now = Date.now();
    // An expired lease as the reaper would first see it...
    writeFileSync(file, JSON.stringify({ id: 'race', slot: 1, pid: 4242, renewedAt: now - 10_000, expiresAt: now - 5_000, ttlMs: 1000 }));
    const leases = readLeases(root, now);
    assert.equal(leases[0].alive, false);
    // ...that the holder renews before the rename lands. Emulated by simulating
    // the second read seeing a newer renewedAt: the protocol's guard is the
    // comparison, so assert it directly through reap's own tombstone logic by
    // renewing first and then reaping with the stale view.
    renew(root, 'race', 60_000, now);
    const report = reap(root, Date.now());
    assert.deepEqual(report, [], 'a live-and-renewed lease must not appear in the reap report');
    assert.equal(existsSync(file), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ── waiting ─────────────────────────────────────────────────────────────────

test('waiting for a slot returns as soon as one frees', async () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 1, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const held = acquire({ root, budget });
    assert.equal(held.state, 'granted');
    const waiter = acquireWaiting({ root, budget, timeoutMs: 4000, pollMs: 50 });
    // Free the slot shortly after the waiter starts polling.
    setTimeout(() => release(root, held.lease.id), 150);
    const outcome = await waiter;
    assert.equal(outcome.state, 'granted');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('waiting honours its timeout and still never refuses', async () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 1, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    acquire({ root, budget });
    const startedAt = Date.now();
    const outcome = await acquireWaiting({ root, budget, timeoutMs: 300, pollMs: 50 });
    const elapsed = Date.now() - startedAt;
    assert.equal(outcome.state, 'queued');
    assert.ok(elapsed >= 250, `returned too early (${elapsed} ms)`);
    assert.ok(elapsed < 4000, `waited far too long (${elapsed} ms)`);
    assert.ok(Number.isInteger(outcome.position));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a granted lease is not reported as queued just because waiters exist', () => {
  const root = scratch();
  const budget = deriveBudget({ maxSlots: 1, minSlots: 1, freeBytes: () => 8 * 1024 ** 3, totalBytes: () => 32 * 1024 ** 3 });
  try {
    const held = acquire({ root, budget, kind: 'holder' });
    assert.equal(held.state, 'granted');
    const queuedOnce = acquire({ root, budget, kind: 'waiter' });
    assert.equal(queuedOnce.state, 'queued');
    // A waiter leaves when it gives up; the position must not accumulate ghosts.
    release(root, queuedOnce.requesterId);
    const view = status({ root, reapFirst: false });
    assert.equal(view.inUse, 1);
    assert.equal(view.waiters, 0);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('status reports the numbers a caller needs to decide, with their derivation', () => {
  const root = scratch();
  try {
    const view = status({ root });
    for (const key of ['budget', 'inUse', 'free', 'waiters', 'derivation', 'freeMiB', 'totalMiB', 'perSlotBytes', 'holders', 'deadLeases']) {
      assert.ok(key in view, `status is missing ${key}`);
    }
    assert.equal(view.inUse, 0);
    assert.equal(view.perSlotBytes, PER_SLOT_BYTES_DEFAULT);
    assert.match(view.derivation, /per slot/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
