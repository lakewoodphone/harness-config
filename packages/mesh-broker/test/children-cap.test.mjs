/**
 * The per-node children cap: how many children one node may carry AT ONCE.
 *
 * WHY THIS FILE EXISTS, AND WHY IT TESTS `broker.place()` DIRECTLY
 *
 * MEASURED 2026-09-18: five children were placed on one node. The broker ranks by
 * capacity, and concentrating is exactly what that ranking is for, so all five went to
 * the biggest machine; that machine's sshd handshake stretched from ~1.5 s to 8 s against
 * a 10 s dispatch timeout, and one child was lost to `Connection timed out`. The load that
 * broke it was our own fleet. Nothing capped it.
 *
 * THE CAP IS A ROSTER-ROW FACT (`maxChildren`, beside `excluded`) and it is enforced against
 * the LIVE LEASE COUNT — not against a capacity document that can be stale while the leases
 * are not. Two consequences are pinned here, because both have bitten this system:
 *
 *   1. the cap must BIND: a further child on a full row is queued, not started, and the
 *      broker must say that the ROW is the reason rather than implying the machine is spent;
 *   2. the cap is the MINIMUM of the machine's arithmetic and the row, and a row that names
 *      no cap keeps the pre-existing behaviour exactly.
 *
 * The tests drive `broker.place()` rather than an HTTP listener on purpose. An earlier
 * version of this file went through the socket and was flaky for a reason that had nothing
 * to do with caps: the first capacity read had not landed, so the queue numbering was still
 * settling. A test that can be green for the wrong reason is worse than no test, so these
 * hold the mesh fixed and assert the cap itself.
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';

import { createBroker } from '../lib/broker.js';
import { startStubGate } from '../lib/stub-gate.js';

/** A mesh of stub nodes, one per spec, each carrying the row fields under test. */
async function meshWith(specs) {
  const stubs = [];
  const nodes = [];
  for (const [index, spec] of specs.entries()) {
    const stub = await startStubGate({ ...spec, node: spec.node });
    stubs.push(stub);
    nodes.push({
      node: spec.node,
      baseUrl: stub.url,
      fqdn: spec.fqdn ?? `${spec.node}.example.ts.net`,
      location: spec.location ?? null,
      excluded: spec.excluded === true,
      maxChildren: spec.maxChildren,
      index,
    });
  }
  return {
    broker: createBroker({ nodes }),
    close: async () => { for (const s of stubs) await s.close(); },
  };
}

test('a node at its row maximum queues the next child instead of starting it', async () => {
  const mesh = await meshWith([{ node: 'capped-host', maxChildren: 2 }]);
  try {
    const first = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
    assert.equal(first.node, 'capped-host');
    assert.equal(first.position, 0, 'the first child starts now');

    const second = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
    assert.equal(second.node, 'capped-host');
    assert.equal(second.position, 0, 'the second child still fits under a cap of two');

    // The third must NOT be told it can start: the machine may have slots to spare, but its
    // roster row says it may not carry a third child at once.
    const third = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
    assert.equal(third.node, 'capped-host', 'with one node in the roster it is still the node, queued');
    assert.ok(third.position > 0, `the third child must be queued, got position ${third.position}`);

    // And a reader must be able to see that the ROW bound it, not the machine.
    const rationale = third.rationale.join('\n');
    assert.match(rationale, /ROSTER ROW/, 'the rationale must name the roster row as the binding constraint');
    assert.match(rationale, /slot\(s\) of machine capacity are left unused/, 'and say how much capacity the cap is leaving unused');
  } finally {
    await mesh.close();
  }
});

test('the cap is what binds: the same request is admitted on a one-child-larger row', async () => {
  // The control for the test above. Identical requests, ONE configuration field different.
  // If the queue position there came from anything but the cap, this pair would not differ.
  const capped = await meshWith([{ node: 'capped-host', maxChildren: 2 }]);
  const roomy = await meshWith([{ node: 'capped-host', maxChildren: 3 }]);
  try {
    for (let i = 0; i < 2; i += 1) {
      await capped.broker.place({ task: { kind: 'oneShot', children: 1 } });
      await roomy.broker.place({ task: { kind: 'oneShot', children: 1 } });
    }
    const underCapped = await capped.broker.place({ task: { kind: 'oneShot', children: 1 } });
    const underRoomy = await roomy.broker.place({ task: { kind: 'oneShot', children: 1 } });
    assert.ok(underCapped.position > 0, 'the third child queues on a two-child row');
    assert.equal(underRoomy.position, 0, 'and starts immediately on a three-child row — the cap is the only difference');
  } finally {
    await capped.close();
    await roomy.close();
  }
});

test('a node at its cap is not offered again while another node has room', async () => {
  // The fleet case: the capped node takes its one child and then must stop being a
  // candidate, however idle its machine looks. Every later placement goes to the node
  // with room; that is the property that would have saved the 2026-09-18 child.
  const mesh = await meshWith([
    { node: 'capped-host', maxChildren: 1 },
    { node: 'roomy-host', maxChildren: 8 },
  ]);
  try {
    const first = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
    const cappedNode = first.node;
    assert.ok(cappedNode === 'capped-host' || cappedNode === 'roomy-host', `unexpected node ${cappedNode}`);

    for (let i = 0; i < 3; i += 1) {
      const placed = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
      // Both nodes have identical machine capacity, so whichever one the ranking prefers it
      // must be able to keep taking children — and the capped one, once full, must not be
      // chosen ahead of a node with room.
      assert.equal(placed.position, 0, `placement ${i + 2} must start, not queue, while a node has room`);
      if (cappedNode === 'capped-host') {
        assert.notEqual(placed.node, 'capped-host', 'the full row must not be offered while another node has room');
      }
      assert.ok(placed.node === 'capped-host' || placed.node === 'roomy-host', `unexpected node ${placed.node}`);
    }

    // The surface must name the cap and whether it is binding, so an operator can answer
    // "why did my fleet queue when the machine looks idle?" without reading nodes.json.
    const report = await mesh.broker.nodes({ fresh: true });
    const cappedRow = (report.nodes ?? []).find((entry) => entry.node === 'capped-host');
    assert.equal(cappedRow.maxChildren, 1, 'the configured cap must be readable from GET /nodes');
  } finally {
    await mesh.close();
  }
});

test('a roster with no cap field behaves exactly as before — the old behaviour is preserved', async () => {
  // A row that names no cap must not be limited by this mechanism. This is the "do not break
  // the fleet you already have" half, and the reason the cap is a per-row field rather than
  // a global limit: the shipped nodes.json names none.
  const mesh = await meshWith([{ node: 'uncapped-host', maxChildren: undefined }]);
  try {
    for (let i = 0; i < 4; i += 1) {
      const placed = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
      assert.equal(placed.position, 0, `child ${i + 1} should still start on an uncapped row`);
    }
    const report = await mesh.broker.nodes({ fresh: true });
    const row = (report.nodes ?? []).find((entry) => entry.node === 'uncapped-host');
    assert.equal(row.maxChildren, null, 'an uncapped row reports no cap rather than a number it does not have');
    assert.equal(row.childrenCapReached, false, 'and it is never "at a cap" it does not have');
  } finally {
    await mesh.close();
  }
});
