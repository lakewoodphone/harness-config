/**
 * Machine posture, and the placement gate built on it.
 *
 * THE PROPERTY UNDER TEST, in one sentence: a placement that would run a child on a
 * host whose posture is not writable is REFUSED, with a reason a reader can act on,
 * and a placement on a writable host is untouched.
 *
 * WHERE THE FROZEN SET COMES FROM — and why these tests do not carry their own copy
 * of the estate's decision. The tests below are in two halves on purpose:
 *
 *   * the DECISION is tested against a fixture table, so it is deterministic and a
 *     change to the estate's real postures does not silently rewrite the test;
 *   * the AUTHORITY is tested against the REAL `settings/machines/host-posture.tsv`
 *     in this repo, asserting the properties that must hold there (every node in
 *     `lib/nodes.js` is designated, and `secratary` is the only one barred). A guard
 *     whose own input is never checked is a guard nobody can trust.
 */

import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { createFixedPlacer, createNodePlacer, createPlacementLedger } from '../lib/placement.js';
import { createFailoverPlacer } from '../lib/failover-placer.js';
import { NODES } from '../lib/nodes.js';
import {
  barredNodeNames,
  loadPosture,
  parsePostureTable,
  placementRefusal,
  postureForNode,
  PLACEMENT_HOST_FROZEN,
  PLACEMENT_HOST_READ_ONLY,
  PLACEMENT_HOST_UNDESIGNATED,
  PLACEMENT_POSTURE_UNKNOWN,
  POSTURE_FILE_RELATIVE,
} from '../lib/posture.js';

/** The designation these tests DECIDE with. Five pipe-separated fields, as the file specifies. */
const FIXTURE = [
  '# a fixture, not the estate: the shape is the real file\'s, the hosts are the real ones',
  'host | posture | since | decided | reason',
  'zabz-tech|writable|2026-09-11T00:00:00Z|fixture|fixture: a normal host',
  'desktop-ts|writable|2026-09-11T00:00:00Z|fixture|fixture: zabz-tech over the tailnet',
  'zabz-yoga-1|writable|2026-09-11T00:00:00Z|fixture|fixture: a normal host',
  'zabz-tech-linux|writable|2026-09-11T00:00:00Z|fixture|fixture: a normal host',
  'lakewooechsmini|writable|2026-09-11T00:00:00Z|fixture|fixture: a normal host',
  'secratary|frozen|2026-10-11T05:43:36Z|fixture decision|fixture: the FROZEN rollback anchor',
  'secratary-ts|frozen|2026-10-11T05:43:36Z|fixture decision|fixture: the frozen box over the tailnet',
  'lpt-apps-01|read-only|2026-10-06T00:00:00Z|fixture|fixture: a vault; do not write it',
].join('\n');

const fixturePosture = () => ({ file: 'test/fixture-host-posture.tsv', designations: parsePostureTable(FIXTURE) });

/** A pressure reader that is never the reason a placement was refused. */
const calmPressure = () => ({
  read: () => ({
    band: 'ok', why: 'test double', commitToPhysicalPct: 40, commitBytes: 1, physicalBytes: 2,
    availableBytes: 3, commitAvailableBytes: 4, commitAvailablePct: 60, agentsRunning: 1,
    nodeProcesses: 1, toolRunnerProcesses: 0, ageMs: 1, source: 'test double', at: new Date(0).toISOString(),
  }),
});

/** A broker double: it answers `/place` from a script and records what it was asked. */
function fakeBroker(answers) {
  const calls = { place: [], done: [] };
  return {
    calls,
    describe: () => 'broker test://broker',
    async place(task) {
      calls.place.push(task);
      const answer = typeof answers === 'function' ? answers(calls.place.length) : answers;
      return { score: 9, eligible: 4, tier: 'fits', blockedBy: [], queue: [], rationale: ['r'], leaseTtlSec: 900, ...answer };
    },
    async done(lease, ok) {
      calls.done.push({ lease, ok });
      return { ok: true, released: true, lease, node: 'x', state: 'running', heldMs: 1 };
    },
    async nodes() { return { nodes: [] }; },
  };
}

function ledgerInTempDir(t) {
  const dir = mkdtempSync(path.join(tmpdir(), 'fanout-posture-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return { dir, ledger: createPlacementLedger({ dir }) };
}

// ---------------------------------------------------------------------------
// the parse — the file's own format, not a paraphrase of it
// ---------------------------------------------------------------------------

test('the table is read as five pipe fields, and a comment or a short row is never a designation', () => {
  const table = parsePostureTable([
    '# host | posture | since | decided | reason',
    '',
    '   ',
    'secratary | FROZEN | 2026-10-11T05:43:36Z | docs/mesh/131.md | the anchor',
    'half-written|writable|2026-01-01',
    'secratary-cloud|writable|2026-10-11T05:43:36Z|docs/mesh/131.md|the authority',
  ].join('\n'));
  assert.equal(table.size, 2, 'the header, the blank lines and the 3-field row are not designations');
  assert.equal(table.get('secratary').posture, 'frozen', 'the posture is case-folded and whitespace-stripped');
  assert.equal(table.get('secratary').decided, 'docs/mesh/131.md');
  assert.equal(table.get('secratary').reason, 'the anchor');
  assert.equal(table.get('secratary').line, 4, 'the row reports where it was read from');
  assert.equal(table.get('secratary-cloud').posture, 'writable');
  // The keys are canonicalised once, at parse, and the LOOKUP is case-insensitive —
  // a host that arrives shouted (`SECRATARY`, as a Windows hostname does) is the same
  // machine and must not read as undesignated.
  assert.equal(placementRefusal('SECRATARY', { designations: table, nodes: {} }).code, PLACEMENT_HOST_FROZEN);
});

test('a duplicate designation does not let a later row turn a frozen host writable', () => {
  const table = parsePostureTable([
    'secratary|frozen|2026-10-11T05:43:36Z|the decision|the anchor',
    'secratary|writable|2026-10-12T00:00:00Z|a later edit|oops',
  ].join('\n'));
  assert.equal(table.size, 1);
  assert.equal(table.get('secratary').posture, 'frozen', 'first row wins, so appended text cannot unlock a freeze');
});

// ---------------------------------------------------------------------------
// the authority: the real file in this repo
// ---------------------------------------------------------------------------

test('the REAL designation file marks the office box frozen under every alias, and the cloud box writable', () => {
  const file = path.resolve(import.meta.dirname, '..', '..', '..', POSTURE_FILE_RELATIVE);
  const table = parsePostureTable(readFileSync(file, 'utf8'));
  for (const alias of ['secratary', 'secratary-ts', 'secratary-lan', '192.168.50.77']) {
    assert.equal(table.get(alias)?.posture, 'frozen', `${alias} must be frozen in ${file}`);
  }
  assert.equal(table.get('secratary-cloud').posture, 'writable', 'the authority is writable, not frozen');
  assert.equal(table.get('178.156.194.1').posture, 'writable');
  // THE PROPERTY THAT MAKES THE GATE TOTAL: every node this package can dispatch to
  // is designated, so no placement is decided on an unread posture.
  for (const node of Object.keys(NODES)) {
    assert.notEqual(postureForNode(node, { designations: table, nodes: NODES }).posture, 'undesignated', `${node} has no posture row`);
  }
  assert.deepEqual(barredNodeNames({ designations: table, nodes: NODES }), ['secratary'], 'exactly one node is unplaceable, and it is the frozen anchor');
});

// ---------------------------------------------------------------------------
// the decision
// ---------------------------------------------------------------------------

test('a frozen host is refused, with what it is FOR, who decided it and what to read', () => {
  const table = fixturePosture().designations;
  const refusal = placementRefusal('secratary-ts', { designations: table, nodes: NODES, file: 'host-posture.tsv' });
  assert.equal(refusal.code, PLACEMENT_HOST_FROZEN);
  assert.match(refusal.message, /REFUSED/);
  assert.match(refusal.message, /FROZEN/);
  assert.match(refusal.message, /WHAT IT IS FOR : fixture: the frozen box over the tailnet/);
  assert.match(refusal.message, /WHO DECIDED    : fixture decision/);
  assert.match(refusal.message, /SINCE          : 2026-10-11T05:43:36Z/);
  assert.match(refusal.message, /DESIGNATION    : frozen/);
  assert.match(refusal.message, /ASK THE\s+OWNER/, 'it says who to ask when the freeze is believed wrong');
  assert.equal(refusal.detail.matchedBy, 'secratary-ts');
});

test('the frozen refusal cannot be unlocked by the read-only escape hatch', () => {
  const table = fixturePosture().designations;
  for (const allowReadOnly of [false, true]) {
    const refusal = placementRefusal('secratary', { designations: table, nodes: NODES, allowReadOnly });
    assert.equal(refusal?.code, PLACEMENT_HOST_FROZEN, 'frozen is refused whatever allowReadOnly says');
  }
});

test('a read-only host is refused by default and allowed only when the owner has been asked', () => {
  const table = fixturePosture().designations;
  const facts = { 'lpt-apps': { ssh: 'lpt-apps-01', hosts: ['lpt-apps-01'] } };
  const refused = placementRefusal('lpt-apps', { designations: table, nodes: facts });
  assert.equal(refused.code, PLACEMENT_HOST_READ_ONLY);
  assert.match(refused.message, /owner has said yes|owner-confirmed/);
  assert.equal(placementRefusal('lpt-apps', { designations: table, nodes: facts, allowReadOnly: true }), null);
});

test('an undesignated host is refused: an unrecognised host is not permission', () => {
  const table = fixturePosture().designations;
  const refusal = placementRefusal('a-node-nobody-designated', { designations: table, nodes: NODES });
  assert.equal(refusal.code, PLACEMENT_HOST_UNDESIGNATED);
  assert.match(refusal.message, /UNDESIGNATED/);
  assert.match(refusal.message, /NOT permission/);
});

test('the worst spelling wins: one frozen alias makes the node frozen', () => {
  const table = parsePostureTable([
    'zabz-tech|writable|2026-01-01T00:00:00Z|fixture|the node',
    'desktop-ts|frozen|2026-10-11T05:43:36Z|fixture|the same machine, frozen under its ssh alias',
  ].join('\n'));
  const reading = postureForNode('zabz-tech', { designations: table, nodes: NODES });
  assert.equal(reading.posture, 'frozen');
  assert.equal(reading.matchedBy, 'desktop-ts');
});

// ---------------------------------------------------------------------------
// the gate, on each of the three placers
// ---------------------------------------------------------------------------

test('END TO END: a broker that NAMES the frozen node is refused, and the lease is handed back unspent', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ node: 'secratary', position: 0, lease: 'L-FROZEN' });
  const transported = [];
  const placer = createNodePlacer({
    broker,
    nodes: NODES,
    posture: fixturePosture(),
    pressureReader: calmPressure(),
    localNode: 'zabz-yoga-1',
    ledger,
    createTransport: (config) => { transported.push(config.target); return { describe: () => 't', async start() { throw new Error('must not run'); } }; },
  });

  await assert.rejects(() => placer.acquire({ id: 'remote-frozen' }), (error) => {
    assert.equal(error.code, PLACEMENT_HOST_FROZEN, 'the code a caller gates on');
    assert.equal(error.name, 'PostureRefusalError');
    assert.match(error.message, /secratary/);
    assert.match(error.message, /FROZEN/);
    assert.match(error.message, /NOTHING WAS DISPATCHED/);
    assert.match(error.message, /released unspent/);
    return true;
  });

  // THE GUARANTEE, MEASURED THREE WAYS.
  assert.deepEqual(broker.calls.done, [{ lease: 'L-FROZEN', ok: false }], 'the reservation is given back, not stranded for its 900 s TTL');
  assert.deepEqual(transported, [], 'no ssh transport was ever built for the frozen node, so nothing could run there');
  const record = ledger.get('remote-frozen');
  assert.equal(record.state, 'posture-refused');
  assert.equal(record.code, PLACEMENT_HOST_FROZEN);
  assert.equal(record.posture.posture, 'frozen');
  assert.equal(record.brokerAnswer.node, 'secratary');
  // The exclusion that was sent is a HINT and the answer was checked anyway — the
  // record must say both, or a reader cannot tell why the refusal was needed.
  assert.deepEqual(record.excludeSentToBroker, ['secratary']);
});

test('a normal placement to a writable node still succeeds, and carries its posture', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ node: 'zabz-tech', position: 0, lease: 'L-OK' });
  const placer = createNodePlacer({
    broker, nodes: NODES, posture: fixturePosture(), pressureReader: calmPressure(), localNode: 'zabz-yoga-1', ledger,
  });
  const placement = await placer.acquire({ id: 'remote-ok' });
  assert.equal(placement.node, 'zabz-tech');
  assert.equal(placement.ssh, 'desktop-ts');
  assert.equal(placement.posture.posture, 'writable');
  assert.equal(placement.posture.matchedBy, 'zabz-tech');
  assert.equal(ledger.get('remote-ok').state, 'placed');
  // The frozen node was offered to the broker as excluded, so the ordinary path does
  // not spend a lease on a host that would be refused.
  assert.deepEqual(broker.calls.place[0].exclude, ['secratary']);
});

test('a designation that cannot be READ refuses before the broker is asked, so no lease is stranded', async (t) => {
  const { ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ node: 'zabz-tech', position: 0, lease: 'L' });
  const placer = createNodePlacer({
    broker,
    nodes: NODES,
    // The real loader, pointed at no candidate at all: the fail-closed path.
    postureLoader: () => loadPosture({ candidates: [] }),
    pressureReader: calmPressure(),
    localNode: 'zabz-yoga-1',
    ledger,
  });
  await assert.rejects(() => placer.acquire({ id: 'remote-nofile' }), (error) => {
    assert.equal(error.code, PLACEMENT_POSTURE_UNKNOWN);
    assert.match(error.message, /HARNESS_CONFIG_POSTURE/, 'the error names the remedy');
    return true;
  });
  assert.equal(broker.calls.place.length, 0, 'the broker must not be asked for a placement that cannot be judged');
  assert.equal(ledger.get('remote-nofile'), undefined, 'nothing was placed, so there is nothing to record');
});

test('an EMPTY designation table is a refusal, not "nothing is frozen"', () => {
  assert.throws(
    () => loadPosture({ candidates: ['x'], exists: () => true, read: () => '# only comments\n\n' }),
    (error) => {
      assert.equal(error.code, PLACEMENT_POSTURE_UNKNOWN);
      assert.match(error.message, /ZERO designations/);
      return true;
    },
  );
});

test('the FIXED target is gated too: MESH_TARGET_NODE=secratary-ts cannot place a child on the frozen box', async () => {
  const frozen = createFixedPlacer({
    transport: { describe: () => 'ssh secratary-ts', async start() { throw new Error('must not run'); } },
    remote: { command: 'dsh', shell: 'posix' },
    target: 'secratary-ts',
    targetHosts: ['secratary'],
    posture: fixturePosture(),
  });
  await assert.rejects(() => frozen.acquire(), (error) => {
    assert.equal(error.code, PLACEMENT_HOST_FROZEN);
    assert.match(error.message, /fixed target/);
    return true;
  });

  const writable = createFixedPlacer({
    transport: { describe: () => 'ssh desktop-ts', async start() {} },
    remote: { command: 'dsh', shell: 'powershell' },
    target: 'desktop-ts',
    targetHosts: ['ZABZ-TECH'],
    posture: fixturePosture(),
  });
  const placement = await writable.acquire();
  assert.equal(placement.posture.posture, 'writable');
  assert.equal(placement.posture.matchedBy, 'desktop-ts');
});

test('a fixed target that names NO machine reports that its posture was not read, rather than pretending it was', async () => {
  const warnings = [];
  const bare = createFixedPlacer({
    transport: { describe: () => 'ssh unnamed', async start() {} },
    remote: { command: 'dsh', shell: 'posix' },
    posture: fixturePosture(),
    logger: { warn: (line) => warnings.push(line) },
  });
  const placement = await bare.acquire();
  assert.equal(placement.posture.posture, 'unreadable');
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /posture/i);
});

test('the DIRECT-PROBE failover path is gated too: a frozen winner with no broker is refused', async () => {
  const unreachable = Object.assign(new Error('broker unreachable'), { code: 'broker-unreachable' });
  const placer = createFailoverPlacer({
    inner: { kind: 'broker', describe: () => 'x', explain: () => 'x', async acquire() { throw unreachable; }, async release() { return {}; } },
    // ONLY the frozen node answers, so the exclusion hint YIELDS and the probe names it —
    // which is exactly the case the check on the answer exists for.
    nodes: ['secratary'],
    posture: fixturePosture(),
    probeMeshImpl: async () => ({
      observations: [{ node: 'secratary', health: { ok: true, node: 'secratary', auth: { secretConfigured: false }, concurrency: { limit: 9 }, runner: { busy: false } }, error: null }],
      reached: ['secratary'],
      unreachable: [],
      at: new Date(0).toISOString(),
    }),
  });
  await assert.rejects(() => placer.acquire({ id: 'c-probe' }), (error) => {
    assert.equal(error.code, PLACEMENT_HOST_FROZEN);
    assert.match(error.message, /direct probe/);
    assert.match(error.message, /NOTHING WAS DISPATCHED/);
    return true;
  });
});
