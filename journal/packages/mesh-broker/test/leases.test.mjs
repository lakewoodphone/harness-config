/**
 * The lease table: the broker's only state.
 *
 *   node --test test/leases.test.mjs
 *
 * The three properties that matter are §2.2's, verbatim: a lease is released by /done, a
 * lease nobody releases is reclaimed at its TTL ("a dead dispatcher cannot wedge the mesh"),
 * and nothing about it is on disk ("it stores nothing it can go stale on").
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { createLeaseTable, DEFAULT_LEASE_TTL_MS } from '../lib/leases.js';

test('a lease is issued, counted on its node, and released by id', () => {
  const table = createLeaseTable({ now: () => 1_000 });
  const lease = table.issue({ node: 'zabz-tech', kind: 'fleet', children: 6, state: 'running' });
  assert.ok(typeof lease.id === 'string' && lease.id.length > 0);
  assert.equal(lease.expiresAt, 1_000 + DEFAULT_LEASE_TTL_MS);
  assert.equal(table.onNode('zabz-tech', 1_000).length, 1);
  assert.equal(table.onNode('zabz-yoga', 1_000).length, 0);
  const released = table.release(lease.id, 1_500);
  assert.equal(released.released, true);
  assert.equal(released.node, 'zabz-tech');
  assert.equal(released.heldMs, 500);
  assert.equal(table.size(), 0);
});

test('a lease nobody releases is reclaimed at its TTL - the dead dispatcher rule', () => {
  let clock = 10_000;
  const table = createLeaseTable({ ttlMs: 5_000, now: () => clock });
  const lease = table.issue({ node: 'zabz-tech', kind: 'oneShot', children: 1 });
  assert.equal(table.live(10_000).length, 1);
  clock = 14_999;
  assert.equal(table.live(clock).length, 1, 'still live one millisecond before the TTL');
  clock = 15_000;
  assert.equal(table.live(clock).length, 0, 'expiry is inclusive: the reservation is gone');
  assert.equal(table.release(lease.id, clock).released, false, 'a lease reclaimed by TTL is simply unknown now');
});

test('running and queued leases are counted separately, because only a running one holds memory', () => {
  const table = createLeaseTable({ now: () => 0 });
  table.issue({ node: 'a', kind: 'oneShot', children: 1, state: 'running' });
  table.issue({ node: 'a', kind: 'oneShot', children: 1, state: 'queued' });
  table.issue({ node: 'a', kind: 'oneShot', children: 1, state: 'queued' });
  const stats = table.stats(0);
  assert.equal(stats.live, 3);
  assert.equal(stats.running, 1);
  assert.equal(stats.queued, 2);
  assert.deepEqual(stats.byNode, { a: 3 });
});

test('live leases come back in arrival order, so "ahead of me" is well defined', () => {
  const table = createLeaseTable({ now: () => 0 });
  const first = table.issue({ node: 'a', kind: 'oneShot', children: 1, at: 100 });
  const second = table.issue({ node: 'a', kind: 'oneShot', children: 1, at: 200 });
  const third = table.issue({ node: 'a', kind: 'oneShot', children: 1, at: 300 });
  assert.deepEqual(table.live(300).map((lease) => lease.id), [first.id, second.id, third.id]);
  assert.deepEqual(table.onNode('a', 300).map((lease) => lease.id), [first.id, second.id, third.id]);
});

test('releasing an unknown lease is reported, never thrown - a fact is not an error', () => {
  const table = createLeaseTable({ now: () => 0 });
  const result = table.release('nope', 0);
  assert.deepEqual(result, { released: false, node: null, state: null, heldMs: null });
});

test('the lease table writes nothing to disk - §2.2 "nothing it can go stale on"', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-broker-leases-'));
  const cwd = process.cwd();
  try {
    process.chdir(dir);
    const table = createLeaseTable({ ttlMs: 10, now: () => 0 });
    table.issue({ node: 'zabz-tech', kind: 'fleet', children: 6 });
    table.issue({ node: 'zabz-yoga', kind: 'oneShot', children: 1, state: 'queued' });
    table.live(1_000);
    assert.deepEqual(readdirSync(dir), [], 'the working directory is still empty');
  } finally {
    process.chdir(cwd);
    rmSync(dir, { recursive: true, force: true });
  }
});
