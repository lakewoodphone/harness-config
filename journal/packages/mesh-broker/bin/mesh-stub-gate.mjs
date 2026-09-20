#!/usr/bin/env node
/**
 * `mesh-stub-gate` — a stand-in for stream S1's `GET /mesh/capacity`, for manual runs.
 *
 *   node bin/mesh-stub-gate.mjs --node zabz-tech --free-mib 51000 --in-use 15 --disk-gib 236
 *   node bin/mesh-stub-gate.mjs --node zabz-yoga --free-mib 0            # capacity forced to zero
 *   node bin/mesh-stub-gate.mjs --node secratary --engine-down           # §2.1's down-state
 *
 * It binds port 0 by default, so two of them never collide, and prints the URL to point a
 * broker at. Nothing about it is production: it exists so a placement can be reproduced from
 * controlled numbers without waiting for a real node.
 */

import { startStubGate, freeMiBForSlots } from '../lib/stub-gate.js';

function parseArgs(argv) {
  const flags = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (next === undefined || next.startsWith('--')) {
      flags[key] = true;
    } else {
      flags[key] = next;
      index += 1;
    }
  }
  return flags;
}

const number = (value, fallback) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const flags = parseArgs(process.argv.slice(2));
const slots = flags.slots === undefined ? null : number(flags.slots, 0);
const gate = await startStubGate({
  node: typeof flags.node === 'string' ? flags.node : 'stub-node',
  freeMiB: slots === null ? number(flags['free-mib'], 17575) : freeMiBForSlots(slots),
  inUse: number(flags['in-use'], 2),
  diskGiB: number(flags['disk-gib'], 236),
  load1: number(flags['load1'], 0.42),
  logical: number(flags.logical, 22),
  engineDown: flags['engine-down'] === true,
  acceptsFleet: flags['no-fleet'] === true ? false : true,
  acceptsOneShot: flags['no-oneshot'] === true ? false : true,
  maxChildren: number(flags['max-children'], 12),
  acceptsReason: typeof flags.reason === 'string' ? flags.reason : null,
});

process.stdout.write(`mesh-stub-gate: ${gate.node} serving GET /mesh/capacity at ${gate.url}/mesh/capacity\n`);
process.stdout.write(`  ${JSON.stringify(gate.capacity)}\n`);
const stop = () => gate.close().then(() => process.exit(0));
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
