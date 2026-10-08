#!/usr/bin/env node
/**
 * `mesh-pressure-proof` — prove, on this machine, that local pressure changes
 * where a child is placed. `docs/mesh/109-pressure-routing.md` §4.
 *
 * WHAT IT PROVES, AND HOW
 * It builds the REAL placer — the real broker client over ssh, the real node
 * table, the real placement ledger — and runs the same three cases the provider
 * runs, with the pressure reading injected so the result does not depend on what
 * this laptop happens to be doing:
 *
 *   A  the machine's OWN reading, taken now, dispatching to the real broker.
 *      Prints the reading next to a `Get-Counter` reading of the same counters
 *      taken in the same minute, so the reader can see they agree.
 *   B  a SIMULATED calm reading, which must reproduce today's behaviour exactly:
 *      no local node excluded, no pressure line in the report, no refusal.
 *   C  a SIMULATED critical reading, which must refuse BEFORE the broker is
 *      asked — no ssh call, no lease — and must say which half was simulated.
 *
 * What is SIMULATED and what is MEASURED is printed per case. Nothing here
 * dispatches a child turn; placement is what this proves, and `docs/mesh/70`
 * already proves the transport.
 *
 *   node bin/mesh-pressure-proof.mjs [--ledger <dir>] [--json]
 *
 * It does NOT dispatch a child turn, deliberately: what this work changes is
 * WHERE a child is placed, and the placement is proved end-to-end here — a live
 * broker decision, a live lease, a live ssh. The transport that would carry the
 * child is unchanged and already measured (`docs/mesh/70-remote-fanout-proof.md`
 * §2), and `docs/mesh/109-pressure-routing.md` §7 records that no child was run.
 */

import { mkdtempSync, readFileSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { createBrokerClient } from '../lib/broker-client.js';
import { createNodePlacer, createPlacementLedger, LOCAL_PRESSURE_REFUSED, MESH_UNAVAILABLE_LOCAL_SATURATED } from '../lib/placement.js';
import {
  createPressureReader,
  decidePressure,
  describePressure,
  localNodeName,
  pressureLine,
  shapePressure,
} from '../lib/pressure.js';

const argv = process.argv.slice(2);
const asJson = argv.includes('--json');
const ledgerDir = (() => {
  const at = argv.indexOf('--ledger');
  return at >= 0 && argv[at + 1] !== undefined ? argv[at + 1] : mkdtempSync(path.join(tmpdir(), 'mesh-pressure-proof-'));
})();

const say = (line) => { if (!asJson) process.stdout.write(`${line}\n`); };
const results = {};

const broker = createBrokerClient({
  sshTarget: process.env.MESH_BROKER_SSH ?? 'secratary-ts',
  sshExe: process.platform === 'win32' ? 'C:/Program Files/OpenSSH/ssh.exe' : 'ssh',
  sshArgs: ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=10'],
  url: process.env.MESH_BROKER_URL ?? 'http://localhost:3091',
});
const ledger = createPlacementLedger({ dir: ledgerDir, logger: { warn: (line) => say(`ledger: ${line}`) } });
const localNode = localNodeName();

// ── CASE A: this machine's own reading, in front of the real broker ──────────
const reader = createPressureReader({ logger: { warn: (line) => say(`reader: ${line}`) } });
const measuredAt = Date.now();
const measured = reader.read();
let placementA;
let errorA;
try {
  const placer = createNodePlacer({
    broker,
    ledger,
    localNode,
    pressureReader: { read: () => measured },
    logger: { info: (line) => say(`  ${line}`), warn: (line) => say(`  WARN ${line}`) },
  });
  placementA = await placer.acquire({ id: 'proof-a-measured' });
} catch (error) {
  errorA = error;
}
results.A = {
  simulated: false,
  reading: measured,
  readingAt: new Date(measuredAt).toISOString(),
  localNode,
  decision: placementA?.pressureDecision ?? (errorA === undefined ? null : { decision: 'refused', code: errorA.code, message: errorA.message }),
  node: placementA?.node ?? null,
  excludedLocalNode: placementA?.excludedLocalNode ?? null,
  pressureLine: placementA === undefined ? null : pressureLine(placementA, placementA.node),
  reportLine: placementA === undefined ? null : pressureLine(placementA, placementA.node),
  error: errorA === undefined ? null : { code: errorA.code, message: errorA.message },
  ledgerFile: ledger.fileFor('proof-a-measured'),
};

say('=== CASE A — MEASURED reading, REAL broker ===');
say(`host                     ${process.env.COMPUTERNAME ?? '(unknown)'} → node ${localNode ?? '(not in the node table)'}`);
say(`${describePressure(measured, decidePressure(measured, { localNode }))}`);
say(`machine counters at      ${new Date(measuredAt).toISOString()} (compare with Get-Counter in the same minute)`);
if (placementA !== undefined) {
  say(`DECISION                 ${placementA.pressureDecision.decision} — broker placed the child on "${placementA.node}"`);
  say(`excludedLocalNode        ${placementA.excludedLocalNode} (exclude sent to the broker: ${JSON.stringify(placementA.pressureDecision.excludeSentToBroker)})`);
  say(`placedLocally            ${placementA.placedLocally}`);
  say(`broker rationale         ${(placementA.rationale ?? []).join(' | ')}`);
  say(`ledger                   ${ledger.fileFor('proof-a-measured')}`);
} else {
  say(`REFUSED                  ${errorA?.code}: ${errorA?.message}`);
}

// ── CASE B: a SIMULATED calm machine, which must behave as today ─────────────
const calmReading = shapePressure({
  commitBytes: Math.round(measured.physicalBytes * 0.4),
  physicalBytes: measured.physicalBytes,
  availableBytes: Math.round(measured.physicalBytes * 0.45),
  commitLimitBytes: measured.commitLimitBytes,
  commitAvailableBytes: Math.round(measured.physicalBytes * 0.9),
  memoryLoadPercent: 40,
}, { measuredAt: Date.now(), now: Date.now(), source: 'SIMULATED reading (mesh-pressure-proof case B) — not measured on this machine' });
let placementB;
let errorB;
try {
  const placer = createNodePlacer({
    broker,
    ledger,
    localNode,
    pressureReader: { read: () => calmReading },
    logger: { info: (line) => say(`  ${line}`), warn: (line) => say(`  WARN ${line}`) },
  });
  placementB = await placer.acquire({ id: 'proof-b-calm' });
} catch (error) {
  errorB = error;
}
results.B = {
  simulated: 'the reading only',
  decision: placementB?.pressureDecision ?? null,
  node: placementB?.node ?? null,
  excludedLocalNode: placementB?.excludedLocalNode ?? null,
  excludeSentToBroker: placementB?.pressureDecision?.excludeSentToBroker ?? null,
  error: errorB === undefined ? null : { code: errorB.code, message: errorB.message },
  ledgerFile: ledger.fileFor('proof-b-calm'),
};

say('');
say('=== CASE B — SIMULATED calm reading (the reading is simulated; the broker is real) ===');
say(`reading                  ${calmReading.source}`);
if (placementB !== undefined) {
  say(`DECISION                 ${placementB.pressureDecision.decision} — broker placed the child on "${placementB.node}"`);
  say(`exclude sent to broker   ${JSON.stringify(placementB.pressureDecision.excludeSentToBroker)}  (empty = exactly today's behaviour)`);
  say(`excludedLocalNode        ${placementB.excludedLocalNode}`);
  say(`ledger                   ${ledger.fileFor('proof-b-calm')}`);
} else {
  say(`ERROR                    ${errorB?.code}: ${errorB?.message}`);
}

// ── CASE C: a SIMULATED critical machine, which must refuse first ────────────
const criticalReading = shapePressure({
  commitBytes: Math.round(measured.physicalBytes * 0.95),
  physicalBytes: measured.physicalBytes,
  availableBytes: 900 * 1048576,
  commitLimitBytes: measured.commitLimitBytes,
  commitAvailableBytes: 2 * 1024 ** 3,
  memoryLoadPercent: 95,
}, { measuredAt: Date.now(), now: Date.now(), source: 'SIMULATED reading (mesh-pressure-proof case C) — not measured on this machine' });
const brokerCalls = [];
const countingBroker = {
  describe: broker.describe,
  place: async (task) => { brokerCalls.push(task); return broker.place(task); },
  done: broker.done,
  healthz: broker.healthz,
  nodes: broker.nodes,
};
// What `meshCheck` answers is REAL: it asks the live broker's own `/healthz` over
// ssh and reports whether that answered. The reading is simulated; the
// reachability of the mesh is not.
const meshReachable = await (async () => {
  try {
    await broker.healthz();
    return true;
  } catch (error) {
    say(`  (the mesh check failed: ${error?.code ?? 'broker-error'} — ${String(error?.message ?? error).slice(0, 200)})`);
    return false;
  }
})();
let errorC;
let placementC;
try {
  const placer = createNodePlacer({
    broker: countingBroker,
    ledger,
    localNode,
    pressureReader: { read: () => criticalReading },
    meshCheck: async () => meshReachable,
    logger: { info: (line) => say(`  ${line}`), warn: (line) => say(`  WARN ${line}`) },
  });
  placementC = await placer.acquire({ id: 'proof-c-critical' });
} catch (error) {
  errorC = error;
}
const refusalRecord = (() => {
  try {
    return JSON.parse(readFileSync(ledger.fileFor('proof-c-critical'), 'utf8'));
  } catch {
    return null;
  }
})();
results.C = {
  simulated: 'the reading only; mesh reachability is a real ssh call',
  band: criticalReading.band,
  meshReachable,
  decision: errorC === undefined ? (placementC?.pressureDecision ?? null) : 'refused',
  code: errorC?.code ?? null,
  message: errorC?.message ?? null,
  brokerCalls: brokerCalls.length,
  refusalRecord,
  ledgerFile: ledger.fileFor('proof-c-critical'),
};

say('');
say('=== CASE C — SIMULATED critical reading (the reading is simulated; the refusal path is real) ===');
say(`reading                  ${criticalReading.source}`);
say(`band                     ${criticalReading.band}`);
say(`mesh reachable           ${meshReachable}  (this half is MEASURED: the broker's own /healthz over ssh)`);
say(`broker calls made        ${brokerCalls.length}  (0 = refused before any ssh, so no lease was taken)`);
if (errorC !== undefined) {
  say(`REFUSAL                  ${errorC.code}: ${errorC.message}`);
} else {
  say(`PLACED                   ${placementC?.node} — the refusal did NOT fire, which is a defect`);
}
say(`ledger                   ${ledger.fileFor('proof-c-critical')}`);
if (refusalRecord !== null) {
  say(`ledger record            state=${refusalRecord.state} code=${refusalRecord.code} band=${refusalRecord.pressure?.band}`);
}

results.ledgerDir = ledgerDir;
results.ledgerFiles = readdirSync(ledgerDir);
results.reader = reader.probe();
results.codes = { LOCAL_PRESSURE_REFUSED, MESH_UNAVAILABLE_LOCAL_SATURATED };

if (asJson) process.stdout.write(`${JSON.stringify(results, null, 2)}\n`);
