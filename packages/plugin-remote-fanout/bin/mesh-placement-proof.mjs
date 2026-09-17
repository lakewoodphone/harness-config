#!/usr/bin/env node
/**
 * mesh-placement-proof — dispatch N REAL children at once through the provider,
 * against a REAL broker, and print where each one was placed and where it ran.
 *
 * WHY THIS EXISTS
 * The claim is that the provider asks the placement broker before every child and
 * dispatches where it is told, so a fan-out spreads over the mesh instead of
 * piling onto the one node a config row named. That claim is measured, not read:
 * this script runs the provider's own code path (`lib/placement.js` +
 * `lib/provider.js`), over the provider's own ssh transport, to real nodes, and
 * prints for every child:
 *
 *   * the node the BROKER named, with the position and the first rationale lines
 *     the broker gave for it,
 *   * the lease, and whether `POST /done` released it,
 *   * the child's OWN `MESH-HOST:` line, which the target machine wrote.
 *
 * A child that ran somewhere the broker did not name is a FAILED proof, and so
 * is a lease that was never released: this exits non-zero for either.
 *
 * USAGE
 *   node bin/mesh-placement-proof.mjs [--children N] [--task "..."] [--dry]
 *                                     [--queue-wait-ms MS] [--queue-poll-ms MS]
 *                                     [--json]
 *   MESH_BROKER_SSH / MESH_BROKER_URL select the broker (defaults: the live one
 *   on the authority). MESH_LEDGER_DIR moves the placement ledger.
 *
 * It changes nothing: no engine is started or restarted, the broker is only
 * asked, and every lease it takes is given back.
 */

import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { createBrokerClient } from '../lib/broker-client.js';
import { createNodePlacer, createPlacementLedger } from '../lib/placement.js';
import { RemoteOneShotProvider, extractMeshHost } from '../lib/provider.js';
import { hostMatchesNode } from '../lib/nodes.js';

const TASK = 'Answer with exactly this one line and nothing else: PROOF-OK';

function parseArgs(argv) {
  const options = { children: 2, task: TASK, dry: false, json: false, hold: 0, queueWaitMs: undefined, queuePollMs: undefined, timeoutMs: 300_000 };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === '--children') options.children = Number(argv[++index]);
    else if (token === '--hold') options.hold = Number(argv[++index]);
    else if (token === '--task') options.task = argv[++index];
    else if (token === '--dry') options.dry = true;
    else if (token === '--json') options.json = true;
    else if (token === '--queue-wait-ms') options.queueWaitMs = Number(argv[++index]);
    else if (token === '--queue-poll-ms') options.queuePollMs = Number(argv[++index]);
    else if (token === '--child-timeout-ms') options.timeoutMs = Number(argv[++index]);
    else if (token === '--help' || token === '-h') {
      process.stdout.write('mesh-placement-proof [--children N] [--task "..."] [--dry] [--json]\n');
      process.exit(0);
    } else {
      process.stderr.write(`mesh-placement-proof: unknown argument "${token}"\n`);
      process.exit(1);
    }
  }
  return options;
}

const say = (line) => process.stdout.write(`${line}\n`);
const note = (line) => process.stderr.write(`${line}\n`);

const options = parseArgs(process.argv.slice(2));
const broker = createBrokerClient({
  sshExe: process.env.MESH_SSH_EXE,
  sshTarget: process.env.MESH_BROKER_SSH ?? 'secratary-ts',
  url: process.env.MESH_BROKER_URL ?? 'http://localhost:3091',
  timeoutMs: 30_000,
  logger: { info: (line) => note(`  [broker] ${line}`), warn: (line) => note(`  [broker] ${line}`) },
});

// ---- the broker, as it actually is ----------------------------------------
const health = await broker.healthz();
say('=== the broker this proof asked ===');
say(`where      ${broker.describe()}`);
say(`healthz    ${JSON.stringify(health)}`);

const before = await broker.nodes({ fresh: true });
say('');
say('=== the live mesh, read fresh ===');
for (const row of before.nodes) {
  say(`  ${String(row.node).padEnd(18)} state=${String(row.state).padEnd(10)} slots=${String(row.slots).padEnd(4)} free=${String(row.freeSlots).padEnd(4)} `
    + `memSlots=${row.memorySlots} coreSlots=${row.coreSlots}(${row.coreSlotsBasis}) swap=${row.swapUsedPct}% transport=${row.transport?.v1} leases=${JSON.stringify(row.brokerLeases ?? null)}`);
}

// ---- the placer, the provider, and the ledger -----------------------------
const ledgerDir = process.env.MESH_LEDGER_DIR ?? mkdtempSync(path.join(tmpdir(), 'mesh-placement-proof-'));
const ledger = createPlacementLedger({ dir: ledgerDir, logger: { warn: (line) => note(`  [ledger] ${line}`) } });
const placer = createNodePlacer({
  broker,
  logger: { info: (line) => note(`  [placer] ${line}`), warn: (line) => note(`  [placer] ${line}`) },
  ledger,
  timeoutMs: options.timeoutMs,
  queueWaitMs: options.queueWaitMs,
  queuePollMs: options.queuePollMs,
});
const provider = new RemoteOneShotProvider({
  name: 'remote-ssh',
  placer,
  timeoutMs: options.timeoutMs,
  logger: { info: (line) => note(`  [provider] ${line}`), warn: (line) => note(`  [provider] ${line}`) },
  ledger,
});

say('');
say(`=== plan ===`);
say(`children   ${options.children}, requested at once, placement ${placer.explain()}`);
say(`ledger     ${ledgerDir}`);

if (options.dry) {
  for (let index = 0; index < options.children; index += 1) {
    const placement = await placer.acquire({ id: `dry-${index}` });
    say(`  dry ${index + 1}: broker → ${placement.node} (${placement.ssh}) position ${placement.position} score ${placement.score} tier ${placement.tier} lease ${placement.lease}`);
    say(`        ${placement.rationale[0]}`);
    await placer.release(placement, true);
  }
  process.exit(0);
}

// ---- optionally put the mesh in the state a fleet leaves it in -------------
// `--hold N` takes N real leases and keeps them while the children below are
// placed, which is exactly the mesh state a fleet of N children leaves behind
// (each of them holds a lease for as long as it runs). It is not a rigged
// decision: the broker ranks the same nodes with the same arithmetic; it is a
// load. Every held lease is released in the same breath as the children's.
const held = [];
if (options.hold > 0) {
  for (let index = 0; index < options.hold; index += 1) {
    const lease = await placer.acquire({ id: `hold-${index}` });
    held.push(lease);
  }
  say('');
  say(`=== the mesh as a fleet leaves it ===`);
  for (const lease of held) {
    say(`  held ${lease.lease} on ${lease.node} (position ${lease.position}, score ${lease.score}, tier ${lease.tier})`);
  }
}

// ---- N children, one `start()` each, all issued before any is awaited ------
const started = Date.now();
const runs = [];
for (let index = 0; index < options.children; index += 1) {
  runs.push(provider.start({ prompt: [{ type: 'text', text: `${options.task} (child ${index + 1} of ${options.children})` }], signal: new AbortController().signal }));
}
const handles = await Promise.all(runs);
note(`  [proof] ${handles.length} children placed and launched in ${Date.now() - started} ms`);

const results = await Promise.all(handles.map(async (run) => {
  const result = await run.result;
  const text = result.output.map((block) => block.text).join('');
  return { id: run.id, result, text, meshHost: extractMeshHost(text) ?? null };
}));

say('');
say('=== what the broker said, per child ===');
const perNode = new Map();
const failures = [];
for (const entry of results) {
  const record = ledger.get(entry.id) ?? {};
  const placed = record.node ?? '(unrecorded)';
  perNode.set(placed, (perNode.get(placed) ?? 0) + 1);
  say('');
  say(`child ${entry.id}`);
  say(`  placed on   ${placed} (${record.ssh ?? '?'})  position=${record.position} score=${record.score} tier=${record.tier} lease=${record.lease}`);
  say(`  waited      ${record.waitedMs ?? 0} ms${record.queueTimedOut === true ? ' (queue wait expired; dispatched anyway)' : ''}`);
  say(`  lease       ${record.leaseReleased === true ? 'RELEASED by POST /done' : `not released (${record.leaseReleaseSkipped ?? record.leaseReleaseError ?? 'unknown'})`}`);
  say(`  stopReason  ${entry.result.stopReason}`);
  say(`  MESH-HOST   ${entry.meshHost ?? '(none)'}`);
  say(`  rationale   ${(record.rationale ?? [])[0] ?? '(none)'}`);
  say(`  rationale   ${(record.rationale ?? [])[1] ?? ''}`);
  say(`  rationale   ${(record.rationale ?? [])[2] ?? ''}`);
  if (entry.result.diagnostic !== undefined) say(`  diagnostic  ${entry.result.diagnostic}`);
  if (entry.result.stopReason !== 'completed') failures.push(`${entry.id}: stopReason ${entry.result.stopReason}`);
  if (record.leaseReleased !== true) failures.push(`${entry.id}: the lease ${record.lease} was not released`);
  if (entry.meshHost === null) failures.push(`${entry.id}: the child reported no MESH-HOST line`);
  else if (!hostMatchesNode(entry.meshHost, placed)) failures.push(`${entry.id}: ran on ${entry.meshHost} but the broker named ${placed}`);
}

const after = await broker.healthz();
for (const lease of held) {
  const released = await placer.release(lease, true);
  say(`released held lease ${lease.lease} on ${lease.node}: ${JSON.stringify(released.released ?? released.skipped ?? released.error)}`);
}
const afterRelease = await broker.healthz();
say('');
say('=== the mesh after, and what is left behind ===');
say(`nodes used      ${[...perNode.entries()].map(([node, count]) => `${node}×${count}`).join(', ')}`);
say(`distinct nodes  ${perNode.size}`);
say(`broker leases   before live=${before.nodes.reduce((sum, row) => sum + (row.brokerLeases?.running ?? 0) + (row.brokerLeases?.queued ?? 0), 0)}  after live=${after.leases?.live} (running=${after.leases?.running}, queued=${after.leases?.queued})  after releasing the held leases=${afterRelease.leases?.live}`);
say(`counters        ${JSON.stringify(provider.counters)}`);
say(`failures        ${failures.length === 0 ? 'none' : failures.join(' | ')}`);

const summary = {
  broker: broker.describe(),
  children: options.children,
  nodesUsed: [...perNode.entries()].map(([node, count]) => ({ node, count })),
  distinctNodes: perNode.size,
  leaseLiveAfter: afterRelease.leases?.live ?? null,
  counters: provider.counters,
  failures,
  placements: results.map((entry) => {
    const record = ledger.get(entry.id) ?? {};
    return {
      id: entry.id,
      node: record.node ?? null,
      ssh: record.ssh ?? null,
      position: record.position ?? null,
      score: record.score ?? null,
      tier: record.tier ?? null,
      lease: record.lease ?? null,
      waitedMs: record.waitedMs ?? null,
      leaseReleased: record.leaseReleased === true,
      stopReason: entry.result.stopReason,
      meshHost: entry.meshHost,
      firstRationale: (record.rationale ?? [])[0] ?? null,
    };
  }),
};
say('');
say(`PROOF-SUMMARY ${JSON.stringify(summary)}`);
for (const handle of handles) await handle.dispose().catch(() => undefined);
process.exit(failures.length === 0 ? 0 : 1);
