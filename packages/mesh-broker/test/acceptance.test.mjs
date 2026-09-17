/**
 * The acceptance tests for stream S5, written as the commands docs/mesh/71-mesh-program.md §4
 * item 2 and item 6 describe.
 *
 *   node --test test/acceptance.test.mjs
 *
 * Everything here goes over a real HTTP socket to a real broker listening on port 0, talking
 * to stub gates that serve the §2.1 schema. Stream S1 is still adding `/mesh/capacity` to the
 * real gate, so the stub is what makes this runnable today; the broker's client code is the
 * same code path either way (`lib/capacity.js` → node:http).
 *
 * §4 item 2 — "Placement decides": it names a node; `rationale` contains the slot arithmetic
 *   that chose it; forcing that node's capacity to 0 names a different node; with ALL nodes
 *   low it still names one and returns position > 0, never an error.
 * §4 item 6 — "Queue, never amputate": 30 concurrent placements against a mesh with 5 slots;
 *   every caller gets a node and a position, at least one position is > 0, zero non-200.
 *
 * The "no fixed port, unique temp path" rules are honoured: every listener binds 127.0.0.1:0
 * and every temp path comes from mkdtempSync.
 */

import { strict as assert } from 'node:assert';
import http from 'node:http';
import test from 'node:test';

import { createBroker } from '../lib/broker.js';
import { createBrokerServer, listen } from '../lib/server.js';
import { freeMiBForSlots, startStubGate } from '../lib/stub-gate.js';
import { getNodes, postDone, postPlace, requestJson, sleep } from './http-client.mjs';

/**
 * Start a mesh: one stub gate per stub node, one broker, one real listener on port 0.
 *
 * @param {{nodes: Array<object>, broker?: object}} options
 *   each node spec: { node, location?, stub?: boolean, baseUrl? (when stub === false), ...stub overrides }
 */
async function startMesh({ nodes: specs, broker: brokerOptions = {} }) {
  const stubs = [];
  const nodes = [];
  for (const [index, spec] of specs.entries()) {
    if (spec.stub === false) {
      nodes.push({
        node: spec.node,
        baseUrl: spec.baseUrl,
        fqdn: spec.fqdn ?? null,
        location: spec.location ?? null,
        excluded: spec.excluded === true,
        dispatch: spec.dispatch,
        volatile: spec.volatile === true,
        index,
      });
      continue;
    }
    const stub = await startStubGate({ ...spec, node: spec.node });
    stubs.push(stub);
    nodes.push({
      node: spec.node,
      baseUrl: stub.url,
      fqdn: spec.fqdn ?? null,
      location: spec.location ?? null,
      excluded: spec.excluded === true,
      dispatch: spec.dispatch,
      index,
    });
  }
  const broker = createBroker({ nodes, ...brokerOptions });
  const server = createBrokerServer({ broker });
  const bound = await listen(server, { host: '127.0.0.1', port: 0 });
  return {
    nodes,
    stubs,
    broker,
    server,
    url: bound.url,
    close: async () => {
      await new Promise((resolve) => server.close(() => resolve()));
      for (const stub of stubs) await stub.close();
    },
  };
}

/** A port with nothing listening on it: start a stub, then close it. */
async function closedPortUrl() {
  const stub = await startStubGate({ node: 'gone' });
  const url = stub.url;
  await stub.close();
  return url;
}

/** The assertions every placement response must satisfy, whatever else happened. */
function assertPlacementShape(json, status) {
  assert.equal(status, 200, `every placement is HTTP 200, got ${status}`);
  assert.equal(Object.hasOwn(json, 'error'), false, 'a placement response never carries an error');
  assert.equal(typeof json.node, 'string');
  assert.ok(json.node.length > 0, 'a node was named');
  assert.equal(Number.isInteger(json.position), true, `position must be an integer, got ${JSON.stringify(json.position)}`);
  assert.ok(json.position >= 0, 'position is 0 or a queue depth, never negative');
  assert.ok(Array.isArray(json.rationale) && json.rationale.length > 0, 'rationale is non-empty - an unexplained placement is a bug');
  assert.ok(Array.isArray(json.queue), 'queue is always a list');
  assert.equal(typeof json.lease, 'string');
  assert.ok(json.lease.length > 0, 'a lease is always issued');
}

// ─────────────────────────────────────────────────────────────────────────────
// §4 item 2 — placement decides
// ─────────────────────────────────────────────────────────────────────────────

test('§4.2 a healthy mesh places a 6-child fleet and the rationale carries the slot arithmetic', async () => {
  const mesh = await startMesh({
    nodes: [
      // The real shapes: 24 physical / 32 logical (the office desktop) and 16 physical / 22
      // logical (the laptop). The core term is NOT the binding one here, so this test still
      // pins the memory arithmetic and the outcome the program documents.
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(30), inUse: 0, diskGiB: 236, load1: 0.42, logical: 32, physical: 24 },
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(10), inUse: 0, diskGiB: 40, load1: 0.1, logical: 22, physical: 16 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'fleet', children: 6, worktreeGiB: 2 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech', 'the node with more free slots wins');
    assert.equal(json.position, 0, 'it fits, so it starts now');
    assert.equal(json.score, 18, 'freeMiBForSlots(30) caps at maxSlots 24, and 24 physical cores cap it at 18');
    assert.equal(json.eligible, 2);
    assert.equal(json.tier, 'fits');

    const text = json.rationale.join('\n');
    // The slot arithmetic, verbatim and complete.
    assert.ok(text.includes('3885 MiB reserve'), 'the frozen reserve appears in the rationale');
    assert.ok(text.includes('160 MiB'), 'the per-slot cost appears in the rationale');
    assert.ok(text.includes('maxSlots=24'), 'the cap appears in the rationale');
    assert.ok(/free slot\(s\) of 24/.test(text), 'the free-slot count appears in the rationale');
    assert.ok(/6 child\(ren\)/.test(text), 'the child count appears in the rationale');
    assert.ok(text.includes('position 0'), 'the position arithmetic appears in the rationale');
    assert.ok(json.rationale[0].includes('zabz-tech'), 'the first line names the chosen node');
    assert.ok(json.rationale.some((line) => line.startsWith('zabz-yoga-1: ')), 'the losing candidate is explained, not hidden');
  } finally {
    await mesh.close();
  }
});

test('§4.2 forcing the chosen node to 0 slots names a different node next time', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(20), inUse: 0, logical: 32, physical: 24 },
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(5), inUse: 0, logical: 22, physical: 16 },
    ],
    // A short cache TTL so the test can change a node's capacity and see it; the shipping
    // default is 15 s and is exercised in the cache test below.
    broker: { cacheTtlMs: 30 },
  });
  try {
    const first = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(first.json, first.status);
    assert.equal(first.json.node, 'zabz-tech');

    mesh.stubs[0].setCapacity({ freeMiB: 0, inUse: 0 });
    assert.equal(mesh.stubs[0].capacity.mem.freeMiB, 0);
    await sleep(60);

    const second = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(second.json, second.status);
    assert.notEqual(second.json.node, first.json.node, 'the zeroed node is not chosen again');
    assert.equal(second.json.node, 'zabz-yoga-1');
    assert.ok(second.json.rationale.some((line) => line.includes('zabz-tech') && line.includes('0 free slot(s)')), 'the zeroed node is explained');

    const report = await getNodes(mesh.url, '?fresh=1');
    const zeroed = report.json.nodes.find((node) => node.node === 'zabz-tech');
    assert.equal(zeroed.unreachable, false, 'a node that answers with 0 slots is reachable, not unreachable');
    assert.equal(zeroed.slots, 0);
    assert.equal(zeroed.freeSlots, 0);
  } finally {
    await mesh.close();
  }
});

test('§4.2 with EVERY node at zero slots it still names a node, and position > 0, HTTP 200', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: 0, inUse: 0 },
      { node: 'zabz-yoga', location: 'home', freeMiB: 0, inUse: 0 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'fleet', children: 6, worktreeGiB: 2 });
    assertPlacementShape(json, status);
    assert.ok(json.position > 0, `a network with no free slot must queue, got position ${json.position}`);
    assert.equal(json.tier, 'highest-slots', 'the frozen "a fleet bigger than every node still places" rule');
    const text = json.rationale.join('\n');
    assert.ok(text.includes('3885 MiB reserve'), 'the arithmetic is still in the rationale');
    assert.ok(/highest measured slots/.test(text), 'the rule that placed it is named');
    assert.ok(/QUEUED rather than refused/.test(text));
  } finally {
    await mesh.close();
  }
});

test('§2.2 a fleet bigger than every node still places, queued, rather than being refused', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(3), inUse: 0 },
      { node: 'zabz-yoga', location: 'home', freeMiB: freeMiBForSlots(3), inUse: 0 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'fleet', children: 6, worktreeGiB: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.score, 3);
    assert.ok(json.position > 0, 'a 6-child fleet cannot start on 3 slots, so it queues');
    assert.equal(json.eligible, 2, 'both nodes are equally eligible at the same slot count');
    assert.ok(json.rationale.some((line) => /highest measured slots/.test(line)));
  } finally {
    await mesh.close();
  }
});

test('the fleet disk gate: a node under the scaled floor is not chosen for a fleet', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(30), inUse: 0, diskGiB: 17, logical: 32, physical: 24 },
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(4), inUse: 0, diskGiB: 236, logical: 22, physical: 16 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'fleet', children: 2, worktreeGiB: 0 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-yoga-1', 'the roomier-in-slots node is refused by the disk gate alone');
    assert.ok(
      json.rationale.some((line) => line.includes('zabz-tech') && line.includes('17 GiB') && line.includes('21 GiB required')),
      'the disk failure is explained on the losing node, with the scaled requirement',
    );
    const oneShot = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.equal(oneShot.json.node, 'zabz-tech', 'kind=oneShot has no disk gate, so the roomier node wins again');
  } finally {
    await mesh.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 3 — the two terms are printed in the rationale, which is newer than the tests
// above and is the whole point of the change: a small node's true worth must be visible.
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 3 the rationale prints both score terms, so a small box is not read as a big one', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(30), inUse: 0, diskGiB: 236, logical: 32, physical: 24 },
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(10), inUse: 0, diskGiB: 60, logical: 22, physical: 16 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech');
    const text = json.rationale.join('\n');
    assert.ok(
      text.includes('zabz-tech: 24 memory slot(s), 18 core slot(s) of 24 physical x 0.75 -> effective 18'),
      `the chosen node's two terms are printed verbatim: ${text}`,
    );
    assert.ok(
      json.rationale.some((line) => line.startsWith('zabz-yoga-1: ') && line.includes('10 memory slot(s), 12 core slot(s) of 16 physical x 0.75 -> effective 10')),
      `the losing node prints its own two terms too: ${text}`,
    );
  } finally {
    await mesh.close();
  }
});

test("AMENDMENT 2 a node at 99.9% swap reports the halving in its rationale and is still placeable", async () => {
  // secratary's live numbers: 4 physical cores, ~17 GiB free, swap 99.9% used.
  const mesh = await startMesh({
    nodes: [
      { node: 'secratary', location: 'office', freeMiB: 16973, inUse: 0, logical: 4, physical: 4, swapUsedPct: 99.9 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'secratary', 'a swapping node is halved, never refused - it is the only candidate');
    assert.equal(json.score, 1, '24 memory slots, 3 core slots, halved by swap to 1');
    assert.equal(json.position, 0, 'one slot is still a slot: it starts now');
    const text = json.rationale.join('\n');
    assert.ok(text.includes('swap 99.9% used'), 'the swap reading is printed');
    assert.ok(text.includes('3 slot(s) halved to 1'), 'the halving arithmetic is printed');
    assert.ok(text.includes('ranking penalty, never a refusal'), 'and it says which kind of change it is');
  } finally {
    await mesh.close();
  }
});

test('AMENDMENT 1 the real 20.8 GiB node: a 1-child fleet places there, a 12-child fleet does not', async () => {
  const node = () => ({ node: 'zabz-tech-linux', location: 'office', freeMiB: 10220, inUse: 0, diskGiB: 20.8, logical: 12, physical: 6, swapUsedPct: 15.3 });
  const oneChild = await startMesh({ nodes: [node()] });
  try {
    const { status, json } = await postPlace(oneChild.url, { kind: 'fleet', children: 1, worktreeGiB: 0 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech-linux', '20.8 GiB clears the 20.5 GiB a 1-child fleet needs');
    const text = json.rationale.join('\n');
    assert.ok(text.includes('20.8 GiB free'), `the live number is printed: ${text}`);
    assert.ok(text.includes('20.5 GiB required'), 'and the requirement it is measured against');
    assert.ok(text.includes('0.5 GiB/child x 1 child(ren)'), 'with the per-child term named explicitly');
    assert.ok(text.includes('gate passes'));
  } finally {
    await oneChild.close();
  }

  const twelve = await startMesh({ nodes: [node()] });
  try {
    const { status, json } = await postPlace(twelve.url, { kind: 'fleet', children: 12, worktreeGiB: 0 });
    assertPlacementShape(json, status);
    const text = json.rationale.join('\n');
    assert.ok(text.includes('26 GiB required'), `a 12-child fleet needs 26 GiB: ${text}`);
    assert.ok(text.includes('0.5 GiB/child x 12 child(ren)'));
    assert.ok(text.includes('gate FAILS'), 'and the gate that the old flat 20 GiB floor let through now fails');
    assert.ok(json.position > 0, 'with nothing eligible it queues rather than starting a fleet it cannot hold');
  } finally {
    await twelve.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 4 — a node measured unable to take v1 work is ranked below one that can,
// named in the rationale, and still placeable when it is all there is
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 4 a node measured unable to accept v1 work ranks below one that can, and says why', async () => {
  const mesh = await startMesh({
    nodes: [
      // The live shapes, 2026-09-16: the laptop dispatches but cannot be dispatched INTO;
      // the desktop takes v1 work. The laptop has FEWER slots, so slot count alone would
      // already pick the desktop - this must hold when it has MORE, which is the next test.
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(5), inUse: 0, diskGiB: 60, logical: 22, physical: 16, dispatch: { v1: false, measuredAt: '2026-09-16', evidence: 'sshd cannot traverse the profile symlinks; the plugin tree fails to load' } },
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(9), inUse: 0, diskGiB: 220, logical: 32, physical: 24, dispatch: { v1: true, measuredAt: '2026-09-16', evidence: 'three child turns completed over ssh' } },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech', 'the node that can take the work wins');
    assert.equal(json.blockedBy.includes('transport'), false, 'and it is not a transport placement');
    const text = json.rationale.join('\n');
    assert.ok(text.includes('transport v1 (ssh --profile headless) MEASURED to work'), 'the winner says its transport is proven');
    assert.ok(
      json.rationale.some((line) => line.startsWith('zabz-yoga-1: ') && line.includes('transport v1 MEASURED BROKEN')),
      'the loser says exactly which fact moved it down',
    );
  } finally {
    await mesh.close();
  }
});

test('AMENDMENT 4 a v1-unusable node with MORE slots still loses to a usable one with fewer', async () => {
  // This is the bug S6 measured: at 23:24Z the broker placed a 3-child fleet on zabz-yoga
  // with score=22, beating zabz-tech - correctly by its own arithmetic, and uselessly,
  // because that node cannot accept the work. Slot count must not outrank the transport.
  const mesh = await startMesh({
    nodes: [
      // The live shape: 23 memory slots but only 12 core slots (16 physical x 0.75), and
      // every other node measured as unable to take the work. Slot count alone would pick
      // this node - which is exactly the placement S6 measured failing.
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(23), inUse: 0, diskGiB: 60, logical: 22, physical: 16, dispatch: { v1: false, measuredAt: '2026-09-16', evidence: 'plugin tree failed to load' } },
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(10), inUse: 0, diskGiB: 220, logical: 32, physical: 8, dispatch: { v1: true, measuredAt: '2026-09-16', evidence: 'three child turns completed over ssh' } },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    const laptop = json.rationale.find((line) => line.startsWith('zabz-yoga-1: '));
    assert.ok(laptop.includes('12 free slot(s)'), `12 free of its 12 effective slots, still more than the desktop's 6: ${laptop}`);
    assert.equal(json.node, 'zabz-tech', 'and it still loses, because a placement it cannot run is worse than a queue');
  } finally {
    await mesh.close();
  }
});

test('AMENDMENT 4 when the only candidate cannot take v1 work it is still placed, and the rationale says so in as many words', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-yoga-1', location: 'home', freeMiB: freeMiBForSlots(23), inUse: 0, diskGiB: 60, logical: 22, physical: 16, dispatch: { v1: false, measuredAt: '2026-09-16', evidence: 'plugin tree failed to load' } },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-yoga-1', 'queue, never amputate: it is placed rather than refused');
    assert.equal(json.tier, 'transport', 'and the tier names the reason');
    assert.ok(json.blockedBy.includes('transport'), `blockedBy carries it too, got ${JSON.stringify(json.blockedBy)}`);
    const text = json.rationale.join('\n');
    assert.ok(text.includes('chosen despite transport=unavailable because nothing else is eligible'), `the silent-wrong-choice bug, fixed in words: ${text}`);
    assert.ok(text.includes('QUEUED rather than refused'));
  } finally {
    await mesh.close();
  }
});

test('AMENDMENT 4 an unmeasured transport is neither "works" nor "broken": it is named as unmeasured', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'secratary', location: 'office', freeMiB: freeMiBForSlots(9), inUse: 0, diskGiB: 184, logical: 4, physical: 4, dispatch: { v1: null, measuredAt: null, evidence: null } },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'secratary');
    const text = json.rationale.join('\n');
    assert.ok(text.includes('transport v1 (ssh --profile headless) UNMEASURED'), 'the third state is printed as itself');
    assert.ok(text.includes('not a claim that it works and not a claim that it does not'));
  } finally {
    await mesh.close();
  }
});



// ─────────────────────────────────────────────────────────────────────────────
// AMENDMENT 5 — the `absent` state: configured, never answered, NOT unreachable
// (approved 2026-09-17. A volatile node that has never been provisioned is neither
// reachable nor unreachable, and calling it unreachable is the same false claim about
// reachability the broker already refused once, in the mem.freeMiB:null case.)
// ─────────────────────────────────────────────────────────────────────────────

test('AMENDMENT 5 a configured node that has never been read is ABSENT, not unreachable, and is not ranked', async () => {
  const dead = await closedPortUrl();
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(9), inUse: 0, diskGiB: 220, logical: 32, physical: 24 },
      { node: 'cpx41-elastic-1', location: 'office', stub: false, baseUrl: dead, volatile: true },
    ],
    // A long cache TTL so the one failed read inside this test is the only one: a node that
    // has NEVER ANSWERED is absent whether the broker has tried zero times or five.
    broker: { cacheTtlMs: 3_600_000 },
  });
  try {
    const report = await getNodes(mesh.url);
    const elastic = report.json.nodes.find((node) => node.node === 'cpx41-elastic-1');
    const laptop = report.json.nodes.find((node) => node.node === 'zabz-tech');
    assert.equal(laptop.absent, false, 'a node with a reading is not absent');
    assert.equal(elastic.absent, true, 'a defined roster node that has never answered is ABSENT');
    assert.equal(elastic.unreachable, false, 'and it is NOT unreachable - that would be a false claim about the network');
    assert.equal(typeof elastic.ageSec, 'number', 'its age is the time since it was configured');
    assert.equal(elastic.absentSince === null, false, 'and the moment of configuration is named');
    assert.equal(Object.hasOwn(elastic, 'reading'), false, 'it is given no reading');
    assert.match(elastic.note, /ABSENT state, not unreachable/);

    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech', 'an absent node is excluded from the ranking');
    assert.equal(json.considered, 1, 'and from the candidate count');
    assert.equal(json.absent, 1, 'while being counted as absent on the response');
    assert.ok(json.rationale[0].includes('1 absent'), 'the absence is in the decision line');
  } finally {
    await mesh.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// §4 item 6 — queue, never amputate
// ─────────────────────────────────────────────────────────────────────────────

test('§4.6 30 concurrent placements against a mesh with 5 slots: every caller gets a node and a position, at least one > 0, zero non-200', async () => {
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(5), inUse: 0 }],
  });
  try {
    const responses = await Promise.all(
      Array.from({ length: 30 }, () => postPlace(mesh.url, { kind: 'oneShot', children: 1 })),
    );
    assert.equal(responses.length, 30);

    const nonOk = responses.filter((response) => response.status !== 200);
    assert.equal(nonOk.length, 0, `zero non-200 responses, saw ${JSON.stringify(nonOk.map((r) => r.status))}`);

    const placements = responses.map((response) => response.json);
    for (const placement of placements) assertPlacementShape(placement, 200);

    const positions = placements.map((placement) => placement.position);
    assert.equal(placements.every((placement) => placement.node === 'zabz-tech'), true, 'every caller got a node name');
    assert.ok(positions.some((position) => position > 0), `at least one caller queued, positions were ${JSON.stringify(positions)}`);
    assert.equal(positions.filter((position) => position === 0).length, 5, 'exactly the 5 slots start now');
    assert.equal(positions.filter((position) => position > 0).length, 25, 'the other 25 queue');
    assert.equal(placements.every((placement) => placement.rationale.length > 0), true);

    const status = await requestJson(`${mesh.url}/healthz`);
    assert.equal(status.json.leases.running, 5);
    assert.equal(status.json.leases.queued, 25);
  } finally {
    await mesh.close();
  }
});

test('/done releases the reservation, and a lease nobody releases is reclaimed at its TTL', async () => {
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(1), inUse: 0 }],
    broker: { leaseTtlMs: 400 },
  });
  try {
    const first = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.equal(first.json.position, 0);
    const second = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.ok(second.json.position > 0, 'one slot, one holder, so the second caller queues');

    const released = await postDone(mesh.url, { lease: first.json.lease, ok: true });
    assert.equal(released.status, 200);
    assert.equal(released.json.released, true);
    assert.equal(released.json.node, 'zabz-tech');

    const third = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.equal(third.json.position, 0, 'the released slot is available again');

    // No /done at all: the dead-dispatcher case. The TTL reclaims it.
    const fourth = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.ok(fourth.json.position > 0, 'the third caller holds the only slot, so the fourth queues');
    await sleep(500);
    const fifth = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.equal(fifth.json.position, 0, 'the expired lease was reclaimed by the broker itself, with no /done at all');
    const status = await requestJson(`${mesh.url}/healthz`);
    assert.equal(status.json.leases.running, 1, 'exactly the live lease remains');

    const unknown = await postDone(mesh.url, { lease: 'no-such-lease' });
    assert.equal(unknown.status, 200, 'releasing an unknown lease is a fact, not an error');
    assert.equal(unknown.json.released, false);
    assert.match(unknown.json.reason, /unknown or already-expired lease/);
  } finally {
    await mesh.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// never refuse, never fake, never drop
// ─────────────────────────────────────────────────────────────────────────────

test('every node unreachable: the placement still names a node with position > 0, and /nodes reports each one with an age', async () => {
  const deadOne = await closedPortUrl();
  const deadTwo = await closedPortUrl();
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', stub: false, baseUrl: deadOne },
      { node: 'zabz-yoga', location: 'home', stub: false, baseUrl: deadTwo },
    ],
  });
  try {
    const report = await getNodes(mesh.url);
    assert.equal(report.status, 200);
    assert.equal(report.json.nodes.length, 2, 'a node that does not answer is reported, never dropped');
    for (const node of report.json.nodes) {
      assert.equal(node.unreachable, true);
      assert.equal(typeof node.ageSec, 'number', 'an unreachable node carries its age');
      assert.ok(node.ageSec >= 0);
      assert.equal(typeof node.reason, 'string');
      assert.ok(node.reason.length > 0, 'an unreachable node carries the reason it could not be read');
      assert.equal(Object.hasOwn(node, 'reading'), false, 'and it is not given a fabricated reading');
      assert.equal(node.slots, 0);
    }

    const { status, json } = await postPlace(mesh.url, { kind: 'fleet', children: 6 });
    assertPlacementShape(json, status);
    assert.ok(json.position > 0, 'a mesh nobody can be measured on queues rather than refusing');
    assert.equal(json.unreachable, 2);
    const text = json.rationale.join('\n');
    assert.ok(/UNREACHABLE/.test(text), 'the chosen node is called unreachable to the caller face');
    assert.ok(/never dropped, never faked/.test(text));
  } finally {
    await mesh.close();
  }
});

test('§2.1 down-state (engine down, governor null) still places and says inUse was assumed', async () => {
  const mesh = await startMesh({
    nodes: [{ node: 'secratary', location: 'office', engineDown: true, freeMiB: 17575, logical: 4, physical: 4 }],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'secratary');
    assert.equal(json.position, 0);
    assert.equal(json.score, 3, '24 memory slots on 4 physical cores is 3 core slots, and the smaller term is the score');
    assert.ok(json.rationale.some((line) => line.includes('treated as 0')), 'the missing governor is named, not hidden');
    assert.ok(json.rationale.some((line) => line.includes('3 core slot(s) of 4 physical x 0.75')), 'the core term is printed even when the engine is down');
  } finally {
    await mesh.close();
  }
});

test('a node that answers with mem.freeMiB null is REACHABLE with unknown slots, not "unreachable"', async () => {
  // §2.1: "Every field is measured or absent." Stream S1's own checker allows a null
  // mem.freeMiB (scripts/mesh-capacity-probe.ps1), so a broker that called such a node
  // unreachable would be making a false statement about reachability.
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-yoga', location: 'home', freeMiB: null, engineDown: true }],
  });
  try {
    const report = await getNodes(mesh.url);
    assert.equal(report.json.nodes[0].unreachable, false, 'it answered, so it is reachable');
    assert.equal(report.json.nodes[0].slotsKnown, false);
    assert.equal(report.json.nodes[0].slots, 0);
    assert.equal(report.json.nodes[0].reading.mem.freeMiB, null);
    assert.match(report.json.nodes[0].warning, /free memory/);

    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-yoga');
    assert.ok(json.position > 0, 'slots are unknown, so it queues rather than claiming a start');
    assert.ok(json.rationale.some((line) => line.includes('no mem.freeMiB reading')));
  } finally {
    await mesh.close();
  }
});

test('a malformed body still returns a placement, with the assumption written into the rationale', async () => {
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(24), inUse: 0 }],
  });
  try {
    const garbage = await requestJson(`${mesh.url}/place`, { method: 'POST', body: 'not json at all' });
    assertPlacementShape(garbage.json, garbage.status);
    assert.ok(garbage.json.rationale.some((line) => line.includes('not valid JSON')), 'the parse failure is in the rationale');
    assert.ok(garbage.json.rationale.some((line) => line.includes('never refuses')));

    const emptyTask = await requestJson(`${mesh.url}/place`, { method: 'POST', body: {} });
    assertPlacementShape(emptyTask.json, emptyTask.status);
    assert.equal(emptyTask.json.kind, 'oneShot');
    assert.equal(emptyTask.json.children, 1);

    const nonsenseKind = await postPlace(mesh.url, { kind: 'spaceship', children: -4, prefer: 'mars', exclude: 'nope' });
    assertPlacementShape(nonsenseKind.json, nonsenseKind.status);
    assert.ok(nonsenseKind.json.rationale.some((line) => line.includes('not "oneShot"|"fleet"')));
  } finally {
    await mesh.close();
  }
});

test('excluding every node is a caller mistake, not a refusal', async () => {
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(9), inUse: 0 },
      { node: 'zabz-yoga', location: 'home', freeMiB: freeMiBForSlots(9), inUse: 0 },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1, exclude: ['zabz-tech', 'zabz-yoga'] });
    assertPlacementShape(json, status);
    assert.equal(json.tier, 'queued');
    assert.ok(json.blockedBy.includes('caller-excluded'), `blockedBy explains why it queued, got ${JSON.stringify(json.blockedBy)}`);
    assert.ok(['zabz-tech', 'zabz-yoga'].includes(json.node));
    assert.ok(json.rationale.some((line) => line.includes('never refuses')));
    assert.ok(json.rationale.some((line) => line.includes('the caller excluded every node')));
    // The arithmetic must not lie about the reason. Measured live on the authority
    // 2026-09-16: an earlier version printed "21 < 0" here, when the node had 22 free slots
    // and the queue was the caller's own exclusion.
    const positionLine = json.rationale.find((line) => line.startsWith('position '));
    assert.ok(positionLine.includes('=< 0') === false && positionLine.includes('< 0') === false, `no false arithmetic: ${positionLine}`);
    assert.ok(positionLine.includes('(it would fit)'), `the fit is stated: ${positionLine}`);
    assert.ok(positionLine.includes('queued because caller-excluded'), `the real blocker is stated: ${positionLine}`);
  } finally {
    await mesh.close();
  }
});

test('when nothing can start, a node we can measure beats one we cannot', async () => {
  // Measured live on the authority 2026-09-16: the first version of this ranking put an
  // unreachable laptop ahead of the one node that was actually answering, because that node
  // declared `accepts.fleet: false`. Reachability first is the fix, and this is its test.
  const dead = await closedPortUrl();
  const mesh = await startMesh({
    nodes: [
      {
        node: 'zabz-tech-linux',
        location: 'office',
        freeMiB: freeMiBForSlots(24),
        inUse: 0,
        acceptsFleet: false,
        maxChildren: 0,
        acceptsReason: 'no governor lease directory on this node, so fleets are not placed here',
      },
      { node: 'zabz-yoga', location: 'home', stub: false, baseUrl: dead },
    ],
  });
  try {
    const { status, json } = await postPlace(mesh.url, { kind: 'fleet', children: 6 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech-linux', 'the measured node is chosen over the unreachable one');
    assert.equal(json.tier, 'queued');
    assert.ok(json.position > 0);
    assert.ok(json.blockedBy.includes('accepts'), `blockedBy names the restriction, got ${JSON.stringify(json.blockedBy)}`);
    const text = json.rationale.join('\n');
    assert.ok(text.includes('accepts.fleet=false'), 'the restriction is quoted, not hidden');
    assert.ok(text.includes('QUEUED rather than refused'));
  } finally {
    await mesh.close();
  }
});

test('an internal fault still returns a placement rather than an error (tier internal-fault)', async () => {
  const good = { node: 'zabz-tech', baseUrl: 'http://127.0.0.1:1', fqdn: null, location: 'office', excluded: false, index: 0 };
  const poisoned = new Proxy({}, {
    get() {
      throw new Error('simulated fault inside the scoring path');
    },
  });
  const broker = createBroker({ nodes: [good, poisoned] });
  const placement = await broker.place({ task: { kind: 'fleet', children: 6 } });
  assert.equal(placement.tier, 'internal-fault');
  assert.equal(placement.node, 'zabz-tech');
  assert.ok(placement.position > 0, 'an internal fault queues, it does not refuse');
  assert.ok(placement.rationale[0].includes('never refuses'));
  assert.ok(placement.rationale[0].includes('simulated fault'));
});

test('a node that accepts the connection and never answers is unreachable within the hard timeout', async () => {
  // The live run on the authority measured a 3031 ms read against a 1500 ms timeout, because
  // `request.setTimeout()` only counts from socket assignment. This is the regression test
  // for the hard wall-clock deadline that fixed it.
  //
  // Since requirement 3 (2026-09-17) a TIMEOUT gets one longer retry, so a node that never
  // answers at all costs `readTimeoutMs + retryTimeoutMs`. Both are scaled down and named here
  // so this test still asserts a real bound rather than a slow one: 300 + 600 = 900 ms, inside
  // the 2000 ms allowance below.
  const sockets = new Set();
  const blackHole = http.createServer((request) => {
    request.on('data', () => {});
    request.on('error', () => {});
  });
  blackHole.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  await new Promise((resolve) => blackHole.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${blackHole.address().port}`;
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-tech', location: 'office', stub: false, baseUrl: url }],
    broker: { readTimeoutMs: 300, retryTimeoutMs: 600 },
  });
  try {
    const startedAt = Date.now();
    const report = await getNodes(mesh.url);
    const elapsed = Date.now() - startedAt;
    assert.equal(report.status, 200);
    assert.equal(report.json.nodes[0].unreachable, true, 'BOTH attempts timed out, so it is unreachable, not slow');
    assert.equal(report.json.nodes[0].state, 'unreachable');
    assert.equal(report.json.nodes[0].retried, true, 'the retry is recorded, so the distinction is auditable');
    assert.match(report.json.nodes[0].reason, /timed out after 600 ms/, 'the sentence quotes the attempt that ended it');
    assert.ok(elapsed < 2000, `300 ms + a 600 ms retry must not take ${elapsed} ms`);

    const placed = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(placed.json, placed.status);
    assert.ok(placed.json.position > 0, 'a node nobody can measure queues rather than refusing');
  } finally {
    await mesh.close();
    for (const socket of sockets) socket.destroy();
    if (typeof blackHole.closeAllConnections === 'function') blackHole.closeAllConnections();
    await new Promise((resolve) => blackHole.close(() => resolve()));
  }
});

test('REQUIREMENT 3 a node that misses the deadline once and answers on the retry is SLOW, not unreachable', async () => {
  // MEASURED 2026-09-16 23:31:18Z: the deployed broker said `zabz-yoga: unreachable (timed out
  // after 1500 ms)` while that laptop's own gate was answering in 89-232 ms and it was simply
  // running the acceptance harness. "Busy" and "gone" call for different actions - a slow node
  // should be ranked lower, a dead one avoided - so the broker now makes two attempts and says
  // which happened.
  //
  // The server below accepts the first request and never answers it, then answers on the retry
  // after a real delay: the retry is slow too, which is the "congested" reading of the state.
  let requests = 0;
  const slowServer = http.createServer((request, response) => {
    requests += 1;
    if (requests === 1) return; // accepted, never answered: the first attempt times out
    const body = JSON.stringify({
      schema: 1,
      node: 'zabz-yoga-1',
      fqdn: 'zabz-yoga-1.tail93e6e6.ts.net',
      at: new Date().toISOString(),
      cpu: { logical: 22, physical: 16, load1: null },
      mem: { totalMiB: 32373, freeMiB: 14818, swapUsedPct: 0 },
      disk: { workRoot: 'C:/Users/ezabz/code', freeGiB: 64.1 },
      agents: { loopsRunning: 7 },
      governor: { budgetSlots: 24, inUse: 0, queued: 0 },
      accepts: { oneShot: true, fleet: true, maxChildren: 12, reason: null },
    });
    // 700 ms on the retry: past `max(400, 1200/3)` = 400 ms, so this is a genuinely slow node.
    setTimeout(() => {
      response.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
      response.end(body);
    }, 700);
  });
  await new Promise((resolve) => slowServer.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${slowServer.address().port}`;
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-yoga-1', location: 'home', stub: false, baseUrl: url },
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(9), inUse: 0, diskGiB: 220, logical: 32, physical: 24 },
    ],
    broker: { readTimeoutMs: 300, retryTimeoutMs: 1200 },
  });
  try {
    const report = await getNodes(mesh.url);
    const yoga = report.json.nodes.find((node) => node.node === 'zabz-yoga-1');
    assert.equal(yoga.unreachable, false, 'it ANSWERED, so it is not unreachable');
    assert.equal(yoga.state, 'slow', 'it missed the deadline once and answered on the retry: SLOW');
    assert.equal(yoga.retried, true);
    assert.equal(typeof yoga.elapsedMs, 'number');
    assert.equal(yoga.slotsKnown, true, 'its capacity is real, not zero: a slow node is still a node');
    assert.equal(yoga.slots, 12, '16 physical cores x 0.75 = 12');
    assert.match(yoga.note, /still slow on the second attempt/);
    assert.ok(yoga.elapsedMs >= 1000, `the read really was slow: ${yoga.elapsedMs} ms`);
    assert.ok(yoga.latencyMs >= 400, `and the retry itself was slow: ${yoga.latencyMs} ms`);

    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech', 'the node that answered first time wins, even with fewer effective slots');
    const slowLine = json.rationale.find((line) => line.startsWith('zabz-yoga-1: ') && line.includes('SLOW'));
    assert.ok(slowLine !== undefined, `the slow node is explained, not hidden: ${json.rationale.join(' | ')}`);
    assert.ok(slowLine.includes('still slow on the second attempt'));
  } finally {
    await mesh.close();
    if (typeof slowServer.closeAllConnections === 'function') slowServer.closeAllConnections();
    await new Promise((resolve) => slowServer.close(() => resolve()));
  }
});

test('REQUIREMENT 3 a COLD first read that the retry fixes fast is still reported slow once, then recovers to ok', async () => {
  // MEASURED on the authority 23:58Z: the broker's first GET to `zabz-yoga-1` missed the 1500 ms
  // deadline and the retry answered in 455 ms, while three direct curl reads of that same gate
  // from that same machine took 0.15-0.32 s each. Nothing was busy - the first read paid a
  // one-off cold cost (resolution + TLS handshake, and no connection is reused).
  //
  // An earlier version of this code tried to hide that case by requiring the retry to be slow
  // too. It was wrong: the read DID miss the deadline, and hiding a miss is the confident-wrong-
  // number failure this project exists to prevent. So the miss is reported ONCE, with its
  // numbers - and this test pins the part that makes it acceptable: the next read of the same
  // warm node is `ok` at full rank, so the cost of the false alarm is one read and one tier.
  let requests = 0;
  const coldServer = http.createServer((request, response) => {
    requests += 1;
    if (requests === 1) return; // the cold attempt times out
    const body = JSON.stringify({
      schema: 1,
      node: 'zabz-yoga-1',
      at: new Date().toISOString(),
      cpu: { logical: 22, physical: 16, load1: null },
      mem: { totalMiB: 32373, freeMiB: 14818, swapUsedPct: 0 },
      disk: { workRoot: 'C:/Users/ezabz/code', freeGiB: 64.1 },
      governor: { budgetSlots: 24, inUse: 0, queued: 0 },
      accepts: { oneShot: true, fleet: true, maxChildren: 12, reason: null },
    });
    response.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
    response.end(body);
  });
  await new Promise((resolve) => coldServer.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${coldServer.address().port}`;
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-yoga-1', location: 'home', stub: false, baseUrl: url }],
    broker: { readTimeoutMs: 300, retryTimeoutMs: 1200, cacheTtlMs: 30 },
  });
  try {
    const first = await getNodes(mesh.url);
    const cold = first.json.nodes[0];
    assert.equal(cold.retried, true, 'the first attempt did miss the deadline');
    assert.equal(cold.state, 'slow', 'so this read is reported slow, with its numbers');
    assert.equal(cold.unreachable, false, 'but the node is NOT unreachable - it answered');
    assert.equal(cold.slotsKnown, true, 'and its capacity is real, not zero');
    assert.equal(cold.slots, 12, '16 physical cores x 0.75 = 12');
    assert.match(cold.note, /cold-start miss rather than proof of congestion/);

    await sleep(60);
    const second = await getNodes(mesh.url);
    const warm = second.json.nodes[0];
    assert.equal(warm.retried, false, 'the next read did not need a retry');
    assert.equal(warm.state, 'ok', 'and a warm node comes back at full rank');
    assert.equal(warm.slots, 12);
  } finally {
    await mesh.close();
    if (typeof coldServer.closeAllConnections === 'function') coldServer.closeAllConnections();
    await new Promise((resolve) => coldServer.close(() => resolve()));
  }
});

test('REQUIREMENT 3b a SLOW node with more free slots is still a candidate: an ok node with fewer wins only if it can take the job', async () => {
  // THE DEFECT THIS PINS (found live 2026-09-17 by the stream that wired dispatch to the broker,
  // docs/mesh/92-provider-placement.md §5.2-§5.3 and §6.2). `slow` used to remove a node from the
  // `fits` pool ENTIRELY (`preferred = dispatchable.filter(c => !c.slow)`), not merely rank it
  // last. The node that alternates ok/slow on consecutive reads is the OWNER'S OWN LAPTOP - the
  // machine running his engine - so it received no children at all while any other node answered
  // quickly, even with more free slots than the winner. Measured consequence: eight concurrent
  // children all landed on the desktop (zabz-tech×8), and a two-child split never happened
  // (§5.3: the desktop at 11 free slots against the laptop's 12, placed on the desktop).
  //
  // The frozen contract is explicit (docs/mesh/71-mesh-program.md §2.2, and docs/mesh/76-broker.md
  // §10.8): a slow node is "ranked below every node that answered first time and never refused".
  // Ranked below is not the same as removed, and a node that is merely slow to answer is not a
  // node that cannot take work.
  //
  // The mesh below is the measured §5.3 shape, one job at a time: the fast node has FEWER free
  // slots than the job needs (4 slots against a 6-child fleet), the slow node has more and fits
  // (12). Correct ranking therefore places on the slow node; the old code dropped it from the
  // pool and QUEUED the fleet on the fast node instead - a queue the mesh did not need.
  let requests = 0;
  const slowServer = http.createServer((request, response) => {
    requests += 1;
    if (requests === 1) return; // accepted, never answered: the first attempt misses the deadline
    // The laptop's own shape (16 physical / 22 logical), with a free-slot count that fits the
    // child the fast node cannot take.
    const body = JSON.stringify({
      schema: 1,
      node: 'zabz-yoga-1',
      fqdn: 'zabz-yoga-1.tail93e6e6.ts.net',
      at: new Date().toISOString(),
      cpu: { logical: 22, physical: 16, load1: null },
      mem: { totalMiB: 32373, freeMiB: freeMiBForSlots(12), swapUsedPct: 0 },
      disk: { workRoot: 'C:/Users/ezabz/code', freeGiB: 64.1 },
      agents: { loopsRunning: 7 },
      governor: { budgetSlots: 24, inUse: 0, queued: 0 },
      accepts: { oneShot: true, fleet: true, maxChildren: 12, reason: null },
    });
    // A real delay on the retry, so this is the "congested" reading of `slow` rather than the
    // cold-start miss, and the state cannot be confused with a fast recovery.
    setTimeout(() => {
      response.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
      response.end(body);
    }, 700);
  });
  await new Promise((resolve) => slowServer.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${slowServer.address().port}`;
  const mesh = await startMesh({
    nodes: [
      { node: 'zabz-yoga-1', location: 'home', stub: false, baseUrl: url },
      // freeMiBForSlots(4) with 32 physical cores: 4 memory slots, 24 core slots -> effective 4.
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(4), inUse: 0, diskGiB: 220, logical: 32, physical: 24 },
    ],
    broker: { readTimeoutMs: 300, retryTimeoutMs: 1200 },
  });
  try {
    // The FIRST read of that gate is the cold one; prime the cache so the placement below judges
    // the slow reading itself rather than racing a second cold read.
    const report = await getNodes(mesh.url);
    const yoga = report.json.nodes.find((node) => node.node === 'zabz-yoga-1');
    assert.equal(yoga.state, 'slow', 'the fixture really did produce a slow reading');
    assert.equal(yoga.slots, 12, 'and the slow node really does have 12 free slots');

    const result = await postPlace(mesh.url, { kind: 'fleet', children: 6 });
    const { status, json } = result;
    assertPlacementShape(json, status);
    assert.equal(
      json.node,
      'zabz-yoga-1',
      `the slow node is still eligible: it is the only candidate that can take the job\n${json.rationale.join('\n')}`,
    );
    assert.equal(json.position, 0, 'and the fleet starts now, rather than queueing work the mesh can already run');
    assert.equal(json.score, 12);
    assert.equal(json.tier, 'fits', 'it is a normal fits placement, not a fallback tier: a slow node is a candidate');

    const text = json.rationale.join('\n');
    const slowLine = json.rationale.find((line) => line.startsWith('zabz-yoga-1: ') && line.includes('SLOW'));
    assert.ok(slowLine !== undefined, `the slow node's classification is printed, not hidden: ${text}`);
    assert.ok(
      json.rationale.some((line) => line.includes('classification=slow')),
      `the classification is printed as a fact of its own: ${text}`,
    );
    assert.ok(text.includes('never removed from the pool and never refused'), 'and the rule applied to it is stated');
    // The losing fast node must still be explained - it lost on capacity, not on being invisible.
    assert.ok(
      json.rationale.some((line) => line.startsWith('zabz-tech: ') && line.includes('4 free slot(s)')),
      `the ok node with fewer slots is still explained: ${text}`,
    );
  } finally {
    await mesh.close();
    if (typeof slowServer.closeAllConnections === 'function') slowServer.closeAllConnections();
    await new Promise((resolve) => slowServer.close(() => resolve()));
  }
});

test('REQUIREMENT 4 a node whose capacity cannot be read is CAPACITY-UNREADABLE, not unreachable and not dropped', async () => {
  // The Mac Mini's reader (stream S1's) answers 200 with `mem: { totalMiB: null, freeMiB: null }`,
  // and other broken readers answer with a wrong schema or a non-numeric field. The node is up;
  // its READER is broken. Before this such a document was rejected outright, so the node was
  // invisible - and an invisible node and an offline node look the same at the caller. It is now
  // its own state, excluded from the ranking and visible in /nodes with the reason it gave, so a
  // broken reader looks like a broken reader.
  //
  // (A document that is usable apart from `mem.freeMiB: null` is a DIFFERENT case and is covered
  // by "a node that answers with mem.freeMiB null is REACHABLE with unknown slots": it answered
  // and its memory alone is unread, which is unknown slots rather than an unreadable capacity.)
  const brokenReader = http.createServer((request, response) => {
    const body = JSON.stringify({ schema: 2, node: 'lakewooechsmini', fqdn: 'lakewooechsmini.tail93e6e6.ts.net', at: new Date().toISOString(), mem: { totalMiB: null, freeMiB: null } });
    response.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
    response.end(body);
  });
  await new Promise((resolve) => brokenReader.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${brokenReader.address().port}`;
  const mesh = await startMesh({
    nodes: [
      { node: 'lakewooechsmini', location: 'office', stub: false, baseUrl: url },
      { node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(9), inUse: 0, diskGiB: 220, logical: 32, physical: 24 },
    ],
  });
  try {
    const report = await getNodes(mesh.url);
    assert.equal(report.status, 200);
    assert.equal(report.json.nodes.length, 2, 'a node with a broken reader is REPORTED, never dropped');
    const mini = report.json.nodes.find((node) => node.node === 'lakewooechsmini');
    assert.equal(mini.state, 'capacity-unreadable');
    assert.equal(mini.unreachable, false, 'it answered, so calling it unreachable would be a false claim');
    assert.equal(mini.absent, false);
    assert.equal(mini.capacityUnreadable, true);
    assert.match(mini.reason, /schema 2 is not 1/, "the reason is the node's OWN, not a broker paraphrase");
    assert.match(mini.note, /broken reader, not an offline machine/);
    assert.equal(Object.hasOwn(mini, 'reading'), false, 'it is given no reading');
    assert.ok(mini.unreadableReading !== undefined, 'but the document it sent is kept, so the reader can be debugged');

    const { status, json } = await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assertPlacementShape(json, status);
    assert.equal(json.node, 'zabz-tech', 'the unreadable node is excluded from the ranking');
    assert.equal(json.absent, 0);
    assert.ok(
      json.rationale.some((line) => line.startsWith('lakewooechsmini: ') && line.includes('CAPACITY-UNREADABLE')),
      `the unreadable node is explained in the rationale: ${json.rationale.join(' | ')}`,
    );
  } finally {
    await mesh.close();
    await new Promise((resolve) => brokenReader.close(() => resolve()));
  }
});

test('GET /nodes reuses a reading for its cache TTL and ?fresh=1 forces a re-read', async () => {
  const mesh = await startMesh({
    nodes: [{ node: 'zabz-tech', location: 'office', freeMiB: freeMiBForSlots(5), inUse: 0 }],
  });
  try {
    const first = await getNodes(mesh.url);
    assert.equal(mesh.stubs[0].requests(), 1);
    assert.equal(first.json.cacheTtlSec, 15, 'the shipping cache TTL is 15 s, as §2.2 requires (at most)');

    const second = await getNodes(mesh.url);
    assert.equal(mesh.stubs[0].requests(), 1, 'the second call inside the TTL did not touch the node');
    assert.equal(typeof second.json.nodes[0].ageSec, 'number');

    await postPlace(mesh.url, { kind: 'oneShot', children: 1 });
    assert.equal(mesh.stubs[0].requests(), 1, 'a placement also uses the cached reading');

    const forced = await getNodes(mesh.url, '?fresh=1');
    assert.equal(mesh.stubs[0].requests(), 2, '?fresh=1 forces a re-read');
    assert.equal(forced.json.nodes[0].unreachable, false);
    assert.equal(forced.json.nodes[0].reading.schema, 1);
  } finally {
    await mesh.close();
  }
});
