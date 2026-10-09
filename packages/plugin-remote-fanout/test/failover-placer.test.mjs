import assert from 'node:assert/strict';
import test from 'node:test';

import { BrokerError, BROKER_UNREACHABLE, BROKER_UNPARSABLE } from '../lib/broker-client.js';
import { createFailoverPlacer, MESH_UNREACHABLE_NO_PROBE, SOURCE_DIRECT_PROBE } from '../lib/failover-placer.js';

/**
 * THE ONE BRANCH THIS FILE EXISTS FOR.
 *
 * `createFailoverPlacer` wraps a real broker placer. The property under test is
 * not "does placement work" — `placement.test.mjs` owns that — it is exactly
 * which failures are absorbed and which must propagate:
 *
 *   broker UNREACHABLE  -> probe the nodes and place from the measurement
 *   broker answers BADLY-> the error propagates (a live broker with a bad answer
 *                          is a bug; a fallback would hide it)
 *   nothing reachable   -> one error naming both halves, and NO local default
 *
 * A health document here is a small literal, exactly like the one
 * `GET /mesh/health` returns (measured shape, 2026-10-09).
 */

/** A broker whose `place()` always throws the given error. */
function brokenBroker(error) {
  return {
    kind: 'broker',
    describe: () => 'broker test://broken',
    async place() { throw error; },
    async done() { return { released: true }; },
    async healthz() { return { ok: true }; },
  };
}

/** An inner placer that always succeeds with the given placement. */
function okPlacer(placement) {
  return {
    kind: 'broker',
    describe: () => 'broker test://ok',
    explain: () => 'stub',
    async acquire() { return { source: 'broker', node: 'broker-node', position: 0, lease: 'lease-1', ...placement }; },
    async release() { return { released: true }; },
    async waitForSlot() { return { settled: true, phase: 'start-now', waitedMs: 0 }; },
    transportFor() { return { describe: () => 'transport-stub' }; },
  };
}

function healthDoc(node, overrides = {}) {
  return {
    ok: true,
    service: 'mesh-http',
    node,
    runner: { busy: false, inFlightCount: 0, queueDepth: 0 },
    auth: { secretConfigured: true, secretPath: 'C:/ProgramData/dsh-mesh.env' },
    concurrency: { limit: 6, note: 'test' },
    limits: { maxConcurrent: 6 },
    identityDegraded: false,
    ...overrides,
  };
}

function probeOf(entries) {
  return async () => ({
    observations: entries,
    reached: entries.filter((e) => e.error === null || e.error === undefined).map((e) => e.node),
    unreachable: entries.filter((e) => e.error !== null && e.error !== undefined).map((e) => ({ node: e.node, error: e.error })),
    at: new Date().toISOString(),
  });
}

const unreachableBroker = () => new BrokerError(BROKER_UNREACHABLE, 'ssh: connect to host secratary.tail93e6e6.ts.net port 22: Connection timed out', { route: '/place' });

test('a broker that answers is used as-is, with source kept as broker', async () => {
  const placer = createFailoverPlacer({
    inner: okPlacer({}),
    nodes: ['zabz-tech'],
    probeMeshImpl: probeOf([{ node: 'zabz-tech', health: healthDoc('zabz-tech'), error: null }]),
  });
  const placement = await placer.acquire({ id: 'c1', childIndex: 0 });
  assert.equal(placement.node, 'broker-node');
  assert.equal(placement.source, 'broker');
  assert.equal(placer.brokerReachable, true);
  assert.equal(placer.lastBrokerFailure, null);
});

test('a broker that CANNOT BE REACHED is absorbed: the mesh is read here and one node is chosen', async () => {
  const placer = createFailoverPlacer({
    inner: { ...okPlacer({}), acquire: async () => { throw unreachableBroker(); } },
    nodes: ['secratary', 'zabz-yoga-1', 'zabz-tech'],
    probeMeshImpl: probeOf([
      { node: 'dead', health: null, error: 'timeout' },
      { node: 'zabz-yoga-1', health: healthDoc('zabz-yoga-1', { concurrency: { limit: 3 } }), error: null },
      { node: 'zabz-tech', health: healthDoc('zabz-tech', { concurrency: { limit: 9 } }), error: null },
    ]),
  });

  const placement = await placer.acquire({ id: 'c2', childIndex: 0 });

  assert.equal(placement.source, SOURCE_DIRECT_PROBE);
  assert.equal(placement.node, 'zabz-tech', 'the node with more free slots must win');
  assert.equal(placement.position, 0);
  assert.equal(placement.leaseSource, 'local', 'with no broker the lease is local and must say so');
  assert.equal(placer.brokerReachable, false);
  assert.match(placer.lastBrokerFailure.message, /Connection timed out/);
  assert.equal(placement.brokerFailure.code, BROKER_UNREACHABLE);
  assert.deepEqual(placement.probe.unreachable.map((u) => u.node), ['dead']);
  assert.ok(placement.facts && typeof placement.facts === 'object');
  assert.ok(Array.isArray(placement.rationale) && placement.rationale.length > 0);
  assert.ok(placement.ssh, 'the placement must carry an ssh destination so the ssh transport can use it');
});

test('a broker that answers BADLY is NOT routed around — the error propagates untouched', async () => {
  const bad = new BrokerError(BROKER_UNPARSABLE, 'the broker answered without naming a node', { route: '/place' });
  let probed = false;
  const placer = createFailoverPlacer({
    inner: { ...okPlacer({}), acquire: async () => { throw bad; } },
    nodes: ['zabz-tech'],
    probeMeshImpl: async () => { probed = true; return { observations: [], reached: [], unreachable: [], at: '' }; },
  });

  await assert.rejects(() => placer.acquire({ id: 'c3', childIndex: 0 }), (error) => {
    assert.equal(error.code, BROKER_UNPARSABLE);
    return true;
  });
  assert.equal(probed, false, 'a live broker with a bad answer must not trigger the probe fallback');
});

test('broker gone AND every node unreachable: one error naming both halves, and no local default', async () => {
  const placer = createFailoverPlacer({
    inner: { ...okPlacer({}), acquire: async () => { throw unreachableBroker(); } },
    nodes: ['secratary', 'zabz-tech-linux'],
    probeMeshImpl: probeOf([
      { node: 'secratary', health: null, error: 'timeout' },
      { node: 'zabz-tech-linux', health: null, error: 'timeout' },
    ]),
  });

  await assert.rejects(() => placer.acquire({ id: 'c4', childIndex: 0 }), (error) => {
    assert.equal(error.code, MESH_UNREACHABLE_NO_PROBE);
    assert.match(error.message, /NO local default/i);
    assert.match(error.message, /secratary/);
    assert.match(error.message, /Connection timed out/);
    return true;
  });
});

test('a probe placement reports position > 0 and is not re-polled (there is no broker to poll)', async () => {
  const placer = createFailoverPlacer({
    inner: { ...okPlacer({}), acquire: async () => { throw unreachableBroker(); } },
    nodes: ['zabz-tech'],
    children: 4,
    probeMeshImpl: probeOf([{ node: 'zabz-tech', health: healthDoc('zabz-tech', { concurrency: { limit: 1 } }), error: null }]),
  });

  const placement = await placer.acquire({ id: 'c5', childIndex: 0 });
  assert.equal(placement.node, 'zabz-tech');
  assert.ok(placement.position > 0, 'a node short of slots must QUEUE, never be refused');
  assert.equal(placement.state, 'queued');

  const waited = await placer.waitForSlot(placement);
  assert.equal(waited.settled, false);
  assert.equal(waited.phase, 'probe-queued');
});

test('release on a probe placement is skipped, never thrown, because the lease was local', async () => {
  const placer = createFailoverPlacer({
    inner: { ...okPlacer({}), acquire: async () => { throw unreachableBroker(); } },
    nodes: ['zabz-tech'],
    probeMeshImpl: probeOf([{ node: 'zabz-tech', health: healthDoc('zabz-tech'), error: null }]),
  });

  const placement = await placer.acquire({ id: 'c6', childIndex: 0 });
  const released = await placer.release(placement, true);
  assert.equal(typeof released.skipped, 'string');
  assert.match(released.skipped, /local/i);
});

test('transportFor and describe are delegated to the inner placer, so placement never becomes a second source of truth', async () => {
  const inner = okPlacer({});
  const placer = createFailoverPlacer({ inner, nodes: ['zabz-tech'], probeMeshImpl: probeOf([]) });
  assert.equal(placer.transportFor({ node: 'x' }).describe(), 'transport-stub');
  assert.match(placer.describe(), /broker test:\/\/ok/);
  assert.match(placer.describe(), /direct node probe/);
});

test('a placer with no inner placer is refused at construction, not at dispatch time', () => {
  assert.throws(() => createFailoverPlacer({}), /needs an `inner` placer/);
});
