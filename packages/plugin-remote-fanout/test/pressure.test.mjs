/**
 * Local pressure, and the routing it changes (docs/mesh/109-pressure-routing.md).
 *
 * Every test here is about a THRESHOLD and a DECISION, so the machine's own
 * numbers are injected rather than measured: a test that depends on how busy
 * this laptop happens to be is a test that fails for the wrong reason. The one
 * thing that IS taken from the platform is `localNodeName()`, which is the
 * translation the whole feature depends on and cannot be faked usefully.
 */

import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { BrokerError, BROKER_UNREACHABLE } from '../lib/broker-client.js';
import { createNodePlacer, createPlacementLedger, LOCAL_PRESSURE_REFUSED, MESH_UNAVAILABLE_LOCAL_SATURATED, PressureRefusalError } from '../lib/placement.js';
import {
  CRITICAL_COMMIT_PHYSICAL_PCT,
  HIGH_COMMIT_PHYSICAL_PCT,
  REFUSE_AVAILABLE_FLOOR_BYTES,
  createPressureReader,
  decidePressure,
  describePressure,
  localNodeName,
  pressureCheckLine,
  pressureLine,
  readingFromProbe,
  readingFromSnapshot,
  shapePressure,
} from '../lib/pressure.js';

const GIB = 1024 ** 3;
/** This laptop's measured shape: 31.62 GiB of physical memory. */
const PHYSICAL = Math.round(31.62 * GIB);

/** A shaped reading with the two numbers a caller controls. */
const reading = ({ commitPct, availableMiB = 8000, source = 'test', at = Date.now() }) => shapePressure({
  commitBytes: Math.round(PHYSICAL * commitPct),
  physicalBytes: PHYSICAL,
  availableBytes: availableMiB * 1048576,
  commitLimitBytes: Math.round(PHYSICAL * 1.397),
  commitAvailableBytes: Math.round(PHYSICAL * 1.397) - Math.round(PHYSICAL * commitPct),
}, { measuredAt: at, now: Date.now(), source });

function ledgerInTempDir(t) {
  const dir = mkdtempSync(path.join(tmpdir(), 'fanout-pressure-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return { dir, ledger: createPlacementLedger({ dir }) };
}

/** A broker double, with the placement every test wants to control. */
function fakeBroker({ placement = { node: 'zabz-tech', position: 0, lease: 'L1' }, throw: error } = {}) {
  const calls = { place: [] };
  return {
    calls,
    describe: () => 'broker http://localhost:3091 over ssh secratary-ts',
    async place(task) {
      calls.place.push(task);
      if (error !== undefined) throw error;
      return { score: 16, eligible: 4, tier: 'fits', blockedBy: [], queue: [], rationale: ['r'], leaseTtlSec: 900, ...placement };
    },
    async done() {
      return { ok: true, released: true };
    },
    async nodes() {
      return { nodes: [] };
    },
  };
}

// ---------------------------------------------------------------------------
// the thresholds, as arithmetic rather than opinion
// ---------------------------------------------------------------------------

test('the bands are exactly the published lines, and the refuse band needs BOTH halves', () => {
  assert.equal(HIGH_COMMIT_PHYSICAL_PCT, 0.85);
  assert.equal(CRITICAL_COMMIT_PHYSICAL_PCT, 0.92);
  assert.equal(REFUSE_AVAILABLE_FLOOR_BYTES, 1536 * 1024 * 1024);

  // Below the first line: nothing changes.
  assert.equal(reading({ commitPct: 0.5 }).band, 'ok');
  assert.equal(reading({ commitPct: 0.8499 }).band, 'ok');
  // At the first line: route remote, never refuse.
  assert.equal(reading({ commitPct: 0.85 }).band, 'high');
  // At the second line WITH room available: still only route remote. This is the
  // half that stops a machine with a large pagefile being refused while it has
  // gigabytes free (measured: 37.95 GiB committed of 31.62 GiB physical with
  // 7.4 GiB of commit headroom and a pagefile holding 194 MB).
  assert.equal(reading({ commitPct: 0.95, availableMiB: 8000 }).band, 'high');
  // At the second line with the floor breached: refuse.
  assert.equal(reading({ commitPct: 0.95, availableMiB: 900 }).band, 'critical');
  assert.equal(reading({ commitPct: 0.92, availableMiB: 1535 }).band, 'critical');
  // The floor is a floor: exactly at it is NOT below it.
  assert.equal(reading({ commitPct: 0.92, availableMiB: 5000 }).band, 'high');
  // The exact lines the brief names, and the boundary is inclusive: at 92 % with
  // the physical floor NOT breached, the machine is routed away from and not
  // refused.
  assert.equal(reading({ commitPct: 0.92, availableMiB: 1536 }).commitToPhysicalPct, 92);
  assert.equal(reading({ commitPct: 0.92, availableMiB: 1536 }).availableStarved, false);
  assert.equal(reading({ commitPct: 0.92, availableMiB: 1536 }).band, 'high');
  // ... and below the ratio, no amount of memory hunger refuses anything.
  assert.equal(reading({ commitPct: 0.5, availableMiB: 10 }).band, 'ok');
});

test('a reading that cannot be made is unknown, and unknown never changes a decision', () => {
  const missing = shapePressure({}, { measuredAt: Date.now(), now: Date.now(), source: 'none' });
  assert.equal(missing.band, 'unknown');
  assert.equal(missing.commitToPhysicalPct, null);
  const decision = decidePressure(missing, { localNode: 'zabz-yoga-1' });
  assert.equal(decision.decision, 'ok');
  assert.equal(decision.refuse, false);
  assert.equal(decision.routeAwayFromLocal, false);
  assert.match(decision.reason, /no pressure reading/);
});

test('the decision table: ok, route-remote, refuse-local, and the mesh-unavailable case', () => {
  assert.equal(decidePressure(reading({ commitPct: 0.5 }), { localNode: 'zabz-yoga-1' }).decision, 'ok');

  const high = decidePressure(reading({ commitPct: 0.9 }), { localNode: 'zabz-yoga-1' });
  assert.equal(high.decision, 'route-remote');
  assert.equal(high.routeAwayFromLocal, true);
  assert.equal(high.refuse, false);
  assert.match(high.reason, /the local node is excluded from the ranking rather than forbidden/);

  const critical = decidePressure(reading({ commitPct: 0.95, availableMiB: 900 }), { localNode: 'zabz-yoga-1' });
  assert.equal(critical.decision, 'refuse-local');
  assert.equal(critical.refuse, true);

  // THE DECIDED CASE: the mesh cannot be reached AND this machine is over its
  // high line. Because the high line is what excludes the local node from the
  // ask, an unreachable mesh means the local option is ALREADY declined and
  // there is nowhere to offer the child — so this refuses at both bands.
  const stranded = decidePressure(reading({ commitPct: 0.95, availableMiB: 900 }), {
    localNode: 'zabz-yoga-1',
    brokerReachable: false,
    brokerError: BROKER_UNREACHABLE,
  });
  assert.equal(stranded.decision, 'refuse-local');
  assert.equal(stranded.refuse, true);
  assert.equal(stranded.meshUnavailable, true);
  assert.match(stranded.reason, /the mesh cannot be reached/);
  assert.match(stranded.reason, /nothing is dispatched/);

  const highUnreachable = decidePressure(reading({ commitPct: 0.95, availableMiB: 8000 }), { localNode: 'zabz-yoga-1', brokerReachable: false });
  assert.equal(highUnreachable.decision, 'refuse-local');
  assert.equal(highUnreachable.refuse, true);
  assert.equal(highUnreachable.meshUnavailable, true);

  // Under NO pressure an unreachable mesh changes nothing: the child runs here,
  // which is exactly what happened before this check existed.
  const calmUnreachable = decidePressure(reading({ commitPct: 0.4 }), { localNode: 'zabz-yoga-1', brokerReachable: false });
  assert.equal(calmUnreachable.decision, 'ok');
  assert.equal(calmUnreachable.refuse, false);
});

// ---------------------------------------------------------------------------
// reading the sources
// ---------------------------------------------------------------------------

test('a plugin-health snapshot becomes a reading, and a stale one does not', () => {
  const at = new Date('2026-09-17T22:13:37Z').toISOString();
  const snapshot = {
    at,
    enginePid: 4416,
    system: {
      totalPhysBytes: PHYSICAL,
      availPhysBytes: 7.5 * GIB,
      commitLimitBytes: Math.round(PHYSICAL * 1.397),
      commitAvailableBytes: 5 * GIB,
      memoryLoadPercent: 75,
    },
    processes: [
      { pid: 4416, ppid: 1, name: 'node.exe' },
      { pid: 5000, ppid: 4416, name: 'node.exe' },
      { pid: 5001, ppid: 4416, name: 'node.exe' },
      { pid: 5002, ppid: 4416, name: 'pwsh.exe' },
    ],
  };
  const now = Date.parse(at) + 1000;
  const fresh = readingFromSnapshot(snapshot, { now, maxAgeMs: 30_000 });
  assert.equal(fresh.band, fresh.commitToPhysicalPct >= 92 ? 'high' : fresh.band);
  assert.equal(fresh.commitBytes, snapshot.system.commitLimitBytes - snapshot.system.commitAvailableBytes);
  assert.equal(fresh.availableBytes, Math.round(7.5 * GIB));
  assert.equal(fresh.nodeProcesses, 3);
  // The runner count is a FLOOR on the local agent count, and it must exclude
  // the engine itself and count only node children.
  assert.equal(fresh.toolRunnerProcesses, 2);
  assert.match(fresh.source, /plugin-health snapshot/);

  // Provenance is the point: a snapshot older than the bound is NOT a reading.
  assert.equal(readingFromSnapshot(snapshot, { now: Date.parse(at) + 30_001, maxAgeMs: 30_000 }), undefined);
  // And a document missing the memory fields is not a reading either.
  assert.equal(readingFromSnapshot({ at, system: { totalPhysBytes: PHYSICAL } }, { now }), undefined);
  assert.equal(readingFromSnapshot({ at: 'not a date', system: snapshot.system }, { now }), undefined);
});

test('the reader prefers the snapshot, spawns nothing for it, and falls back to its own probe', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'fanout-pressure-src-'));
  const probeDir = mkdtempSync(path.join(tmpdir(), 'fanout-pressure-probe-'));
  rmSync(probeDir, { recursive: true, force: true });
  const spawned = [];
  // A spawn that records that it happened and answers with a plausible probe.
  const spawnImpl = (shell, argv) => {
    spawned.push({ shell, argv });
    const listeners = {};
    const child = {
      stdout: { on: (event, handler) => { listeners[`stdout:${event}`] = handler; } },
      stderr: { on: (event, handler) => { listeners[`stderr:${event}`] = handler; } },
      once: (event, handler) => { listeners[event] = handler; },
      unref: () => {},
      kill: () => {},
      // Answer on the next tick, the way a real child does.
      _answer: () => {
        listeners['stdout:data']?.(JSON.stringify({
          totalPhysBytes: PHYSICAL,
          availPhysBytes: 6 * GIB,
          commitLimitBytes: Math.round(PHYSICAL * 1.397),
          commitAvailableBytes: 3 * GIB,
          commitBytes: Math.round(PHYSICAL * 0.9),
          memoryLoadPercent: 70,
          nodeProcesses: 20,
        }));
        listeners.close?.(0);
      },
    };
    setTimeout(() => child._answer(), 0);
    return child;
  };

  const snapshotFile = path.join(dir, 'processes.json');
  const reader = createPressureReader({ snapshotFile, probeDir, spawnImpl, agentsRunning: () => 7 });
  // 1. Nothing at all yet: an unknown reading, and the probe has been started.
  const first = reader.read();
  assert.equal(first.band, 'unknown');
  assert.equal(spawned.length, 1, 'the probe is started when no source can answer');

  // 2. A fresh snapshot: the snapshot answers, the probe is NOT spawned again.
  writeFileSync(snapshotFile, JSON.stringify({
    at: new Date().toISOString(),
    enginePid: 1,
    system: {
      totalPhysBytes: PHYSICAL,
      availPhysBytes: 8 * GIB,
      commitLimitBytes: Math.round(PHYSICAL * 1.397),
      commitAvailableBytes: 6 * GIB,
      memoryLoadPercent: 60,
    },
    processes: [],
  }));
  const second = reader.read();
  assert.notEqual(second.band, 'unknown');
  assert.match(second.source, /plugin-health snapshot/);
  assert.equal(second.agentsRunning, 7, 'the live census travels with a snapshot reading');
  assert.equal(spawned.length, 1, 'a snapshot costs no process');

  // 3. A stale snapshot is ABSENT, not a reading — provenance is the point.
  writeFileSync(snapshotFile, JSON.stringify({
    at: new Date(Date.now() - 60_000).toISOString(),
    enginePid: 1,
    system: {
      totalPhysBytes: PHYSICAL,
      availPhysBytes: 8 * GIB,
      commitLimitBytes: Math.round(PHYSICAL * 1.397),
      commitAvailableBytes: 6 * GIB,
    },
  }));
  assert.equal(reader.probe().maxAgeMs, 30_000);
  // 4. With the snapshot stale, the probe's cached reading is the answer, and it
  //    says so — this is the fallback path, not a second reading of the snapshot.
  const probeFile = path.join(probeDir, 'last-probe.json');
  writeFileSync(probeFile, JSON.stringify({
    at: Date.now(),
    totalPhysBytes: PHYSICAL,
    availPhysBytes: 5 * GIB,
    commitLimitBytes: Math.round(PHYSICAL * 1.397),
    commitAvailableBytes: 4 * GIB,
    commitBytes: Math.round(PHYSICAL * 0.9),
    nodeProcesses: 22,
    processes: 400,
  }));
  const viaProbe = reader.read();
  assert.match(viaProbe.source, /this package's own probe/);
  assert.equal(viaProbe.band, 'high');
  assert.equal(reader.probe().spawns, 1, 'the fallback probe still ran at most once');
  rmSync(dir, { recursive: true, force: true });
  rmSync(probeDir, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// the placement path
// ---------------------------------------------------------------------------

test('under the high line nothing changes: the broker is asked with the caller\'s own exclude list', async (t) => {
  const { dir, ledger } = ledgerInTempDir(t);
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 0, lease: 'L-ok' } });
  const placer = createNodePlacer({
    broker,
    ledger,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => reading({ commitPct: 0.4 }) },
  });
  const placement = await placer.acquire({ id: 'remote-ok' });

  assert.deepEqual(broker.calls.place, [{ kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [] }]);
  assert.equal(placement.node, 'zabz-tech');
  assert.equal(placement.excludedLocalNode, false);
  assert.equal(placement.pressureDecision.decision, 'ok');
  assert.equal(placement.pressureDecision.excludeSentToBroker.length, 0);
  assert.equal(placement.pressureConflict, undefined);
  // The reading is on the record even when it changed nothing.
  const written = JSON.parse(readFileSync(path.join(dir, 'remote-ok.json'), 'utf8'));
  assert.equal(written.pressure.band, 'ok');
  assert.match(written.pressureLine, /pressure OK/);
});

test('at or above the high line the local node is offered to the broker as excluded, and the record names the reason', async (t) => {
  const { dir, ledger } = ledgerInTempDir(t);
  // The broker ranks WITHOUT the local node, which is what makes this a
  // pressure-caused placement rather than a coincidence.
  const broker = fakeBroker({ placement: { node: 'zabz-tech', position: 0, lease: 'L-high', score: 24 } });
  const placer = createNodePlacer({
    broker,
    ledger,
    localNode: 'zabz-yoga-1',
    // The caller had its own hint; the local node is added to it, not swapped in.
    exclude: ['lakewooechsmini'],
    pressureReader: { read: () => reading({ commitPct: 0.87 }) },
  });
  const placement = await placer.acquire({ id: 'remote-high' });

  assert.deepEqual(broker.calls.place[0].exclude, ['lakewooechsmini', 'zabz-yoga-1']);
  assert.equal(placement.node, 'zabz-tech');
  assert.equal(placement.excludedLocalNode, true);
  assert.equal(placement.pressureDecision.decision, 'route-remote');
  assert.equal(placement.placedLocally, false);

  const written = JSON.parse(readFileSync(path.join(dir, 'remote-high.json'), 'utf8'));
  assert.equal(written.excludedLocalNode, true);
  assert.deepEqual(written.pressureDecision.excludeSentToBroker, ['lakewooechsmini', 'zabz-yoga-1']);
  assert.match(written.pressureDecision.reason, /the local node is excluded from the ranking/);
  assert.equal(written.pressure.band, 'high');
  assert.deepEqual(written.pressureDecision.localNode, 'zabz-yoga-1');
});

test('a broker that places on THIS machine while the machine is in the high band dispatches, and says so', async (t) => {
  const { dir, ledger } = ledgerInTempDir(t);
  // The broker ignored the exclusion: `exclude` is the caller's HINT, and it
  // yields when it is the only option. Nothing may be invented about that.
  const broker = fakeBroker({ placement: { node: 'zabz-yoga-1', position: 0, lease: 'L-local' } });
  const placer = createNodePlacer({
    broker,
    ledger,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => reading({ commitPct: 0.87 }) },
  });
  const placement = await placer.acquire({ id: 'remote-conflict' });
  assert.equal(placement.node, 'zabz-yoga-1');
  assert.equal(placement.placedLocally, true);
  assert.match(placement.pressureConflict, /the local node was offered to the broker as excluded, and it was chosen anyway/);
  const written = JSON.parse(readFileSync(path.join(dir, 'remote-conflict.json'), 'utf8'));
  assert.match(written.pressureConflict, /chosen anyway/);
});

test('above the critical line the child is REFUSED before the broker is asked, so no lease is stranded', async () => {
  const broker = fakeBroker();
  const placer = createNodePlacer({
    broker,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => reading({ commitPct: 0.95, availableMiB: 900 }) },
  });
  await assert.rejects(
    () => placer.acquire({ id: 'remote-critical' }),
    (error) => {
      assert.equal(error.code, LOCAL_PRESSURE_REFUSED);
      assert.ok(error instanceof PressureRefusalError);
      assert.match(error.message, /this machine has no room to honour another turn/);
      assert.match(error.message, /nothing was dispatched and no reservation was taken/);
      // The evidence travels with the refusal, so a caller can report the numbers.
      assert.equal(error.detail.pressure.band, 'critical');
      assert.equal(error.detail.decision.decision, 'refuse-local');
      return true;
    },
  );
  assert.equal(broker.calls.place.length, 0, 'a refusal must not spend an ssh call, and must not hold a lease');
});

test('critical pressure WITH an unreachable mesh refuses in the words that name both halves', async () => {
  const broker = fakeBroker();
  const placer = createNodePlacer({
    broker,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => reading({ commitPct: 0.97, availableMiB: 400 }) },
    meshCheck: async () => false,
  });
  await assert.rejects(() => placer.acquire({ id: 'remote-stranded' }), (error) => {
    assert.equal(error.code, MESH_UNAVAILABLE_LOCAL_SATURATED);
    assert.match(error.message, /the mesh cannot be reached/);
    assert.match(error.message, /nothing is dispatched/);
    assert.equal(error.detail.decision.meshUnavailable, true);
    return true;
  });
  assert.equal(broker.calls.place.length, 0);
});

test('critical pressure with a REACHABLE mesh refuses as a pressure refusal, not as a mesh failure', async () => {
  const broker = fakeBroker();
  const placer = createNodePlacer({
    broker,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => reading({ commitPct: 0.97, availableMiB: 400 }) },
    meshCheck: async () => true,
  });
  await assert.rejects(() => placer.acquire({ id: 'remote-critical-2' }), (error) => {
    assert.equal(error.code, LOCAL_PRESSURE_REFUSED);
    assert.match(error.message, /the mesh IS reachable, so remote placement is what is wanted/);
    return true;
  });
});

test('an unreachable broker with NO pressure reading is still the plain broker failure — nothing regresses', async () => {
  const broker = fakeBroker({ throw: new BrokerError(BROKER_UNREACHABLE, 'ssh exited 255') });
  const placer = createNodePlacer({
    broker,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => shapePressure({}, { measuredAt: Date.now(), now: Date.now() }) },
  });
  await assert.rejects(() => placer.acquire({ id: 'r-unreachable' }), (error) => {
    assert.equal(error.code, BROKER_UNREACHABLE);
    assert.equal(error instanceof PressureRefusalError, false);
    return true;
  });
});

test('a node this package cannot dispatch to is still refused as a lookup miss', async () => {
  const broker = fakeBroker({ placement: { node: 'someone-elses-laptop', position: 0, lease: 'L3' } });
  const placer = createNodePlacer({
    broker,
    localNode: 'zabz-yoga-1',
    pressureReader: { read: () => reading({ commitPct: 0.4 }) },
  });
  await assert.rejects(() => placer.acquire({ id: 'r-miss' }), /refusing to dispatch into a lookup miss/);
});

// ---------------------------------------------------------------------------
// the local node's name, and the two report lines
// ---------------------------------------------------------------------------

test('this machine\'s node name is translated through the node table, not assumed', () => {
  // The broker names nodes by their Tailscale label; the OS calls this laptop
  // ZABZ-YOGA. Both spellings, and the -ts alias, must land on one name.
  assert.equal(localNodeName('ZABZ-YOGA'), 'zabz-yoga-1');
  assert.equal(localNodeName('zabz-yoga-1.tail93e6e6.ts.net'), 'zabz-yoga-1');
  assert.equal(localNodeName('laptop-ts'), undefined, 'an ssh alias is not a node name');
  assert.equal(localNodeName('ZABZ-TECH'), 'zabz-tech');
  assert.equal(localNodeName('some-unknown-host'), undefined);
});

test('the child\'s report names the decision, the numbers, the node, and the declined local option', () => {
  const placement = {
    node: 'zabz-tech',
    pressure: reading({ commitPct: 0.88 }),
    pressureDecision: decidePressure(reading({ commitPct: 0.88 }), { localNode: 'zabz-yoga-1' }),
  };
  const line = pressureLine(placement, 'ZABZ-TECH');
  assert.match(line, /^HIGH — route-remote/);
  assert.match(line, /the LOCAL option was declined and offered to the mesh as excluded/);
  assert.match(line, /child was placed on "zabz-tech"/);
  assert.match(line, /physical committed \(88 %\)/);

  // Under no pressure the line is still present, and it says the local option
  // was NOT declined — a reader must never have to infer that from silence.
  const calm = {
    node: 'zabz-tech',
    pressure: reading({ commitPct: 0.4 }),
    pressureDecision: decidePressure(reading({ commitPct: 0.4 }), { localNode: 'zabz-yoga-1' }),
  };
  assert.match(pressureLine(calm, 'ZABZ-TECH'), /under no pressure: the local node was NOT excluded/);
  assert.match(pressureCheckLine(calm.pressure), /^local pressure OK — /);

  // A placement with no reading says so rather than staying silent.
  assert.match(pressureCheckLine(undefined), /NOT been sampled/);
  assert.equal(pressureLine({ node: 'zabz-tech' }, 'ZABZ-TECH'), undefined);
  assert.match(describePressure(placement.pressure, placement.pressureDecision), /tool-call runners/);
});
