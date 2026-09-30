/**
 * Reroute support: a dispatcher that has just lost a child on a node must be able to
 * insist on a different one.
 *
 * WHY THIS FILE EXISTS
 *
 * `task.exclude` already existed as a SOFT hint, and the broker's own header explains
 * why soft: a caller's list must yield to "queue, never amputate" when it names every
 * node. But a caller that has just lost a child ON A NODE has a stronger need than a
 * preference, and the measured behaviour without this was that the placer re-offered the
 * node that had just failed and the PROVIDER had to notice and skip it (2026-09-30).
 * That is a reroute implemented by hoping, and hoping is not a mechanism.
 *
 * So `excludeNodes` is its own field: still soft enough not to empty the mesh, but named
 * distinctly so the request, the rationale and the ledger all say that a reroute is in
 * progress rather than that someone expressed a preference. `excludeLease` names a lease
 * to treat as spent, for a caller whose node name it no longer trusts.
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';

import { createBroker, normalizeTask } from '../lib/broker.js';
import { startStubGate } from '../lib/stub-gate.js';

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
  return { broker: createBroker({ nodes }), close: async () => { for (const s of stubs) await s.close(); } };
}

test('normalizeTask accepts excludeNodes and excludeLease, and reports the junk it dropped', () => {
  const clean = normalizeTask({ task: { kind: 'oneShot', children: 1, excludeNodes: ['a', 'b'] } });
  assert.deepEqual(clean.task.excludeNodes, ['a', 'b']);
  assert.equal(clean.task.excludeLease, null);
  assert.deepEqual(clean.notes, []);

  const withLease = normalizeTask({ task: { excludeLease: 'lease-42' } });
  assert.equal(withLease.task.excludeLease, 'lease-42');

  // Junk is dropped with a note rather than silently changing the request's meaning.
  const dirty = normalizeTask({ task: { excludeNodes: ['ok', 7, '', null], excludeLease: '   ' } });
  assert.deepEqual(dirty.task.excludeNodes, ['ok']);
  assert.equal(dirty.task.excludeLease, null, 'a whitespace lease is not a lease');
  assert.ok(dirty.notes.some((note) => note.includes('excludeNodes')), `expected a note about excludeNodes, got ${JSON.stringify(dirty.notes)}`);
});

test('a reroute exclusion moves the placement to a node that was not excluded', async () => {
  const mesh = await meshWith([
    { node: 'first-host', maxChildren: 4 },
    { node: 'second-host', maxChildren: 4 },
  ]);
  try {
    const initial = await mesh.broker.place({ task: { kind: 'oneShot', children: 1 } });
    assert.ok(['first-host', 'second-host'].includes(initial.node));

    // The dispatcher lost a child on that node and must not be sent back there.
    const rerouted = await mesh.broker.place({
      task: { kind: 'oneShot', children: 1, excludeNodes: [initial.node] },
    });
    assert.notEqual(rerouted.node, initial.node, `the reroute must not return to ${initial.node}`);
    assert.equal(rerouted.position, 0, 'and it must actually start there');
    // The rationale must distinguish a reroute from a mere preference.
    assert.match(rerouted.rationale.join('\n'), /REROUTE/, 'the rationale must say a reroute excluded the node');
  } finally {
    await mesh.close();
  }
});

test('excluding every node still places — queue, never amputate — and says so', async () => {
  // The rule that keeps soft exclusions soft: a caller cannot empty the mesh by naming
  // every node. It gets a node and a queue position, never a refusal.
  const mesh = await meshWith([{ node: 'only-host', maxChildren: 4 }]);
  try {
    const placed = await mesh.broker.place({
      task: { kind: 'oneShot', children: 1, excludeNodes: ['only-host'] },
    });
    assert.equal(placed.node, 'only-host', 'with one node, excluding it still names it');
    assert.ok(placed.position >= 0);
    const rationale = placed.rationale.join('\n');
    assert.match(rationale, /REROUTE/, 'and the caller is told its exclusion could not be honoured');
  } finally {
    await mesh.close();
  }
});

test('exclude and excludeNodes are independent and both are honoured', async () => {
  const mesh = await meshWith([
    { node: 'a-host', maxChildren: 4 },
    { node: 'b-host', maxChildren: 4 },
    { node: 'c-host', maxChildren: 4 },
  ]);
  try {
    const placed = await mesh.broker.place({
      task: { kind: 'oneShot', children: 1, exclude: ['a-host'], excludeNodes: ['b-host'] },
    });
    assert.equal(placed.node, 'c-host', 'both lists are excluded, so only the third node remains');
  } finally {
    await mesh.close();
  }
});

test('an exclusion naming a node that is not in the roster is harmless', async () => {
  const mesh = await meshWith([{ node: 'real-host', maxChildren: 4 }]);
  try {
    const placed = await mesh.broker.place({
      task: { kind: 'oneShot', children: 1, excludeNodes: ['a-node-that-never-existed'] },
    });
    assert.equal(placed.node, 'real-host', 'an unknown name excludes nothing and does not wedge the broker');
    assert.equal(placed.position, 0);
  } finally {
    await mesh.close();
  }
});
