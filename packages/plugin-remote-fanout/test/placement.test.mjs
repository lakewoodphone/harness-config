import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { BrokerError, BROKER_UNREACHABLE } from '../lib/broker-client.js';
import { resolvePlacementMode } from '../lib/index.js';
import { hostMatchesNode, isHostToken, NODES } from '../lib/nodes.js';
import { createNodePlacer, createPlacementLedger, PLACEMENT_NODE_UNKNOWN } from '../lib/placement.js';

/**
 * A pressure reader double. Every placement test injects one, and it defaults to
 * a machine under NO pressure, so these tests keep asserting what they were
 * written to assert — the broker contract and the node table — rather than
 * whatever this laptop happened to be doing when the suite ran. Pressure's own
 * behaviour is tested in `pressure.test.mjs`, where the numbers are controlled.
 */
function calmPressure(reading = { band: 'ok', why: 'test double: under no pressure', commitToPhysicalPct: 40, commitBytes: 13 * 1024 ** 3, physicalBytes: 33 * 1024 ** 3, availableBytes: 8 * 1024 ** 3, commitAvailableBytes: 20 * 1024 ** 3, commitAvailablePct: 60, agentsRunning: 1, nodeProcesses: 12, toolRunnerProcesses: 2, ageMs: 100, source: 'test double', at: new Date().toISOString() }) {
  return { read: () => reading };
}

/** A broker double that answers /place, /done and /nodes from a script. */
function fakeBroker({ placement, nodes = () => ({ nodes: [] }), done } = {}) {
  const calls = { place: [], done: [], nodes: [] };
  return {
    calls,
    describe: () => 'broker http://localhost:3091 over ssh secratary-ts',
    async place(task) {
      calls.place.push(task);
      if (placement instanceof Error) throw placement;
      return { score: 16, eligible: 4, tier: 'fits', blockedBy: [], queue: [], rationale: ['r'], leaseTtlSec: 900, ...placement };
    },
    async done(lease, ok) {
      calls.done.push({ lease, ok });
      if (done instanceof Error) throw done;
      return done ?? { ok: true, released: true, lease, node: 'zabz-tech', state: 'running', heldMs: 10 };
    },
    async nodes(options) {
      calls.nodes.push(options);
      return nodes(calls.nodes.length);
    },
  };
}

/** A clock the tests own: `sleep` moves `now`, so a bounded wait is deterministic. */
function clock(start = 0) {
  let value = start;
  return {
    now: () => value,
    sleep: async (ms) => { value += ms; },
    advance: (ms) => { value += ms; },
    at: () => value,
  };
}

function ledgerInTempDir(t) {
  const dir = mkdtempSync(path.join(tmpdir(), 'fanout-ledger-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return { dir, ledger: createPlacementLedger({ dir }) };
}

// The exact task the placer asks the broker for on a FIRST placement. `excludeNodes`
// joined the request on 2026-09-30: it is a reroute's explicit "do not send this child
// back to a node that already failed it" list, kept separate from the `exclude`
// preference hint, and empty on a first ask because nothing has failed yet.
const ONESHOT = { kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [], excludeNodes: [] };

// ---------------------------------------------------------------------------
// acquire
// ---------------------------------------------------------------------------

test('acquire() asks the broker once and turns its node name into an ssh destination', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 0, lease: 'L1' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'remote-1' });

  assert.equal(broker.calls.place.length, 1);
  assert.deepEqual(broker.calls.place[0], ONESHOT);
  assert.equal(placement.node, 'zabz-tech');
  assert.equal(placement.ssh, 'desktop-ts');
  assert.deepEqual(placement.hosts, NODES['zabz-tech'].hosts);
  assert.equal(placement.facts.shell, 'powershell');
  assert.match(placement.facts.bin, /@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js$/);
  assert.equal(placement.facts.profile, 'headless');
  // The placement carries the RESOLVED invocation, so a placement that names a
  // node also states how that node will be invoked (docs/mesh/102-linux-dispatch.md).
  assert.equal(placement.invocation.form, 'interpreter');
  assert.equal(placement.state, 'placed');
  assert.equal(ledger.get('remote-1').lease, 'L1');
});

test('a POSIX node with an executor is placed with the executor form on the record', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'zabz-tech-linux', position: 0, lease: 'L2b' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'remote-2b' });
  assert.equal(placement.facts.command, 'dsh');
  assert.deepEqual(placement.facts.credentialEnvFiles, ['/etc/dsh-worker.env']);
  assert.equal(placement.invocation.form, 'executor');
  assert.equal(placement.invocation.command, 'dsh');
  assert.equal(ledger.get('remote-2b').invocation.command, 'dsh');
});

test('acquire() carries the placed node\'s own shell, not the parent platform', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'zabz-tech-linux', position: 0, lease: 'L2' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'remote-2' });
  assert.equal(placement.facts.shell, 'posix');
  assert.equal(placement.facts.cwd, '/home/zabz/code');
});

test('a broker answer naming a node this package cannot dispatch to is refused, not guessed', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'someone-elses-laptop', position: 0, lease: 'L3' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  await assert.rejects(
    () => placer.acquire({ id: 'remote-3' }),
    (error) => {
      assert.equal(error.code, PLACEMENT_NODE_UNKNOWN);
      assert.match(error.message, /refusing to dispatch into a lookup miss/);
      return true;
    },
  );
});

test('a broker that cannot be asked throws, and no node is invented', async () => {
  const broker = fakeBroker({ placement: new BrokerError(BROKER_UNREACHABLE, 'the placement broker could not be reached at secratary-ts:http://localhost:3091/place — ssh exited 255') });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1' });
  await assert.rejects(() => placer.acquire({ id: 'remote-4' }), /could not be reached at secratary-ts/);
});

// ---------------------------------------------------------------------------
// the queue
// ---------------------------------------------------------------------------

test('position 0 does not wait and does not poll', async () => {
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 0, lease: 'L' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1' });
  const placement = await placer.acquire({ id: 'r' });
  const wait = await placer.waitForSlot(placement, {});
  assert.deepEqual(wait, { waited: false, waitedMs: 0, polls: [] });
  assert.equal(broker.calls.nodes.length, 0);
});

test('position > 0 is surfaced with its position, the child waits, and a freed slot ends the wait', async () => {
  const time = clock(0);
  // The node frees up on the third read.
  const broker = fakeBroker({
    placement: { node: 'zabz-yoga-1', position: 3, lease: 'L9', queue: [{ lease: 'a' }, { lease: 'b' }, { lease: 'c' }] },
    nodes: (n) => ({ nodes: [{ node: 'zabz-yoga-1', state: 'ok', freeSlots: n < 3 ? 0 : 1 }] }),
  });
  const events = [];
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', queueWaitMs: 60_000, queuePollMs: 5_000, now: time.now, sleep: time.sleep });
  const placement = await placer.acquire({ id: 'r9' });
  const wait = await placer.waitForSlot(placement, { onWait: (event) => events.push(event) });

  assert.equal(wait.waited, true);
  assert.equal(wait.timedOut, false);
  assert.equal(wait.waitedMs, 15_000);
  assert.equal(wait.polls.length, 3);
  assert.deepEqual(events[0], { phase: 'queued', node: 'zabz-yoga-1', position: 3, queue: [{ lease: 'a' }, { lease: 'b' }, { lease: 'c' }], lease: 'L9' });
  assert.equal(events.at(-1).phase, 'queued-released');
  assert.match(events.at(-1).note, /a free slot appeared after 15000 ms/);
  // The position is in the record before the child is dispatched, which is what
  // makes a waiting child visible while it waits.
  assert.equal(broker.calls.nodes.length, 3);
  assert.equal(broker.calls.nodes.every((options) => options.fresh === true), true);
});

test('a wait that expires says so and dispatches anyway — queue, never amputate', async () => {
  const time = clock(0);
  const broker = fakeBroker({
    placement: { node: 'zabz-tech', position: 11, lease: 'L10' },
    nodes: () => ({ nodes: [{ node: 'zabz-tech', state: 'ok', freeSlots: 0 }] }),
  });
  const events = [];
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', queueWaitMs: 12_000, queuePollMs: 5_000, now: time.now, sleep: time.sleep });
  const placement = await placer.acquire({ id: 'r10' });
  const wait = await placer.waitForSlot(placement, { onWait: (event) => events.push(event) });
  assert.equal(wait.timedOut, true);
  assert.equal(events.at(-1).phase, 'queued-expired');
  assert.match(events.at(-1).note, /no free slot appeared within 12000 ms; dispatching anyway \(queue, never amputate\)/);
});

test('a broker read that fails during the wait is recorded and the wait continues', async () => {
  const time = clock(0);
  let reads = 0;
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 1, lease: 'L11' } });
  broker.nodes = async () => {
    reads += 1;
    if (reads === 1) throw new BrokerError(BROKER_UNREACHABLE, 'ssh exited 255');
    return { nodes: [{ node: 'zabz-tech', state: 'ok', freeSlots: 1 }] };
  };
  const events = [];
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', queueWaitMs: 60_000, queuePollMs: 1_000, now: time.now, sleep: time.sleep });
  const placement = await placer.acquire({ id: 'r11' });
  const wait = await placer.waitForSlot(placement, { onWait: (event) => events.push(event) });
  assert.equal(wait.timedOut, false);
  assert.equal(wait.polls[0].error, BROKER_UNREACHABLE);
  assert.equal(wait.polls.length, 2);
});

// ---------------------------------------------------------------------------
// release, and the ledger
// ---------------------------------------------------------------------------

test('release() gives the lease back and reports what the broker said', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 0, lease: 'L12' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'r12' });
  const released = await placer.release(placement, true);
  assert.deepEqual(broker.calls.done, [{ lease: 'L12', ok: true }]);
  assert.equal(released.released, true);
});

test('a lease that will not release is reported, never thrown: the broker reclaims it at its TTL', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({
    placement: { node: 'zabz-tech', position: 0, lease: 'L13' },
    done: new BrokerError(BROKER_UNREACHABLE, 'ssh exited 255'),
  });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'r13' });
  const released = await placer.release(placement, false);
  assert.equal(released.ok, false);
  assert.equal(released.code, BROKER_UNREACHABLE);
});

test('the ledger writes one file per placement, carrying the position the broker gave', async (t) => {
  const { dir, ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'zabz-yoga-1', position: 2, lease: 'L14' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'remote-abc' });
  assert.equal(placement.position, 2);
  ledger.record('remote-abc', { state: 'dispatching', waitedMs: 5000 });
  const written = JSON.parse(readFileSync(path.join(dir, 'remote-abc.json'), 'utf8'));
  assert.equal(written.node, 'zabz-yoga-1');
  assert.equal(written.position, 2);
  assert.equal(written.lease, 'L14');
  assert.equal(written.state, 'dispatching');
  assert.equal(written.waitedMs, 5000);
});

test('a ledger that cannot be written is reported and never breaks the placement', async (t) => {
  const warnings = [];
  const ledger = createPlacementLedger({
    dir: path.join(tmpdir(), 'fanout-ledger-that-does-not-exist', 'nope'),
    logger: { warn: (line) => warnings.push(line) },
    fs: { mkdirSync: () => { throw new Error('EACCES'); }, writeFileSync: () => {} },
  });
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 0, lease: 'L15' } });
  const placer = createNodePlacer({ broker, pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger });
  const placement = await placer.acquire({ id: 'r15' });
  assert.equal(placement.node, 'zabz-tech');
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /the placement ledger could not be written/);
});

// ---------------------------------------------------------------------------
// nodes.js
// ---------------------------------------------------------------------------

test('hostMatchesNode answers for the node the broker named, and a lookup miss never widens it', () => {
  assert.equal(hostMatchesNode('ZABZ-TECH', 'zabz-tech'), true);
  assert.equal(hostMatchesNode('zabz-yoga-1.tail93e6e6.ts.net', 'zabz-yoga-1'), true);
  assert.equal(hostMatchesNode('ZABZ-YOGA', 'zabz-tech'), false);
  assert.equal(hostMatchesNode('anything', 'a-node-nobody-configured'), false);
});

test('isHostToken rejects the placeholder a report writes when a child never ran', () => {
  assert.equal(isHostToken('zabz-tech'), true);
  assert.equal(isHostToken('(not'), false);
  assert.equal(isHostToken(''), false);
});

// ---------------------------------------------------------------------------
// the mode rule: the broker is the automatic path, fixed is opt-in
// ---------------------------------------------------------------------------

test('placement mode defaults to broker, and fixed only when a human asked for it', () => {
  // Nothing configured: ask the broker. This is the line that closes the defect.
  assert.equal(resolvePlacementMode({}, {}), 'broker');
  // A row that merely names a target does NOT select fixed mode.
  assert.equal(resolvePlacementMode({ target: 'desktop-ts' }, {}), 'broker');
  // A hand-set MESH_TARGET_NODE is the opt-in fallback, and it is logged as such.
  assert.equal(resolvePlacementMode({}, { MESH_TARGET_NODE: 'desktop-ts' }), 'fixed');
  // An explicit choice in the row or the environment wins over both.
  assert.equal(resolvePlacementMode({ placement: 'fixed' }, {}), 'fixed');
  assert.equal(resolvePlacementMode({}, { MESH_PLACEMENT: 'fixed' }), 'fixed');
  assert.equal(resolvePlacementMode({}, { MESH_PLACEMENT: 'broker', MESH_TARGET_NODE: 'desktop-ts' }), 'broker');
  assert.equal(resolvePlacementMode({ placement: 'broker' }, { MESH_TARGET_NODE: 'desktop-ts' }), 'broker');
});
