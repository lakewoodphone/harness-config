#!/usr/bin/env node
/**
 * `mesh-pressure` — read this machine's pressure, exactly as the placement path
 * reads it, and print the decision that reading would produce.
 *
 * WHY A CLI EXISTS FOR THIS
 * The reader lives on a hot path inside the engine, and a number that can only
 * be observed by dispatching a child is a number nobody can check. This runs the
 * same `createPressureReader()` the provider runs, in a fresh process, and
 * prints raw bytes, every ratio, the age and source of the reading, and the
 * routing decision — so a reader can compare it against `Get-Counter` in the
 * same minute (`docs/mesh/109-pressure-routing.md` §4).
 *
 *   node bin/mesh-pressure.mjs                 # the reading and the decision
 *   node bin/mesh-pressure.mjs --json          # the same, machine-readable
 *   node bin/mesh-pressure.mjs --probe         # run this package's own probe now
 *   node bin/mesh-pressure.mjs --simulate 0.95 --available-mib 900
 *                                              # the refusal path, without
 *                                              # saturating the machine
 */

import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  createPressureReader,
  decidePressure,
  describePressure,
  localNodeName,
  shapePressure,
  HIGH_COMMIT_PHYSICAL_PCT,
  CRITICAL_COMMIT_PHYSICAL_PCT,
  REFUSE_AVAILABLE_FLOOR_BYTES,
  DEFAULT_MAX_AGE_MS,
} from '../lib/pressure.js';

function parseArgs(argv) {
  const out = { json: false, probe: false, forceProbe: false, help: false, simulate: null, availableMiB: null, agents: null };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--json') out.json = true;
    else if (arg === '--probe') out.probe = true;
    else if (arg === '--force-probe') out.forceProbe = true;
    else if (arg === '--help' || arg === '-h') out.help = true;
    else if (arg === '--simulate') out.simulate = Number(argv[++index]);
    else if (arg === '--available-mib') out.availableMiB = Number(argv[++index]);
    else if (arg === '--agents') out.agents = Number(argv[++index]);
  }
  return out;
}

const USAGE = [
  'mesh-pressure — this machine\'s pressure, as the placement path reads it',
  '',
  '  node bin/mesh-pressure.mjs [--json] [--probe] [--force-probe] [--simulate <commitToPhysical>] [--available-mib <MiB>] [--agents <n>]',
  '',
  `  thresholds: high >= ${HIGH_COMMIT_PHYSICAL_PCT} of physical committed, critical >= ${CRITICAL_COMMIT_PHYSICAL_PCT}`,
  `              and less than ${Math.round(REFUSE_AVAILABLE_FLOOR_BYTES / 1048576)} MiB physical available   (docs/mesh/109-pressure-routing.md §2)`,
  `  a snapshot older than ${DEFAULT_MAX_AGE_MS} ms is treated as absent`,
  '  --force-probe  point the reader at a snapshot that cannot exist, so the FALLBACK PROBE',
  '                 itself is what runs. For measuring the fallback path on a host whose',
  '                 plugin-health snapshot is healthy (and therefore never used up).',
].join('\n');

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  process.stdout.write(`${USAGE}\n`);
  process.exit(0);
}

// `--force-probe` is the only mode that changes the reader's SOURCES: it points
// the snapshot at a path that does not exist and the probe cache at a temp
// directory, so the fallback probe is the only thing that can answer. It is the
// path a node without plugin-health takes, and this is how it is measured.
const forceProbeDir = args.forceProbe ? mkdtempSync(path.join(tmpdir(), 'mesh-pressure-probe-')) : undefined;
const reader = createPressureReader({
  ...(args.forceProbe ? { snapshotFile: path.join(forceProbeDir, 'no-such-snapshot.json'), probeDir: forceProbeDir } : {}),
  logger: { warn: (line) => process.stderr.write(`${line}\n`) },
});
let reading = reader.read();

// `--probe` asks for the fallback path on purpose: it starts this package's own
// probe and waits for it, which is the only way to measure the probe's cost
// without an engine.
if (args.probe || args.forceProbe) {
  const before = reader.probe().spawns;
  const started = Date.now();
  for (let attempt = 0; attempt < 40; attempt += 1) {
    // eslint-disable-next-line no-await-in-loop
    await new Promise((resolve) => setTimeout(resolve, 250));
    reading = reader.read();
    if (reader.probe().spawns > before && reading.band !== 'unknown') break;
  }
  process.stderr.write(`probe: ${reader.probe().spawns - before} spawn(s), ${Date.now() - started} ms, ${reader.probe().probeFile}`
    + `${reader.probe().lastProbeError === null ? '' : `, lastError=${reader.probe().lastProbeError}`}\n`);
}

if (Number.isFinite(args.simulate)) {
  // A SIMULATED reading, and it says so in `source`. The refusal path has to be
  // demonstrable on a machine that cannot be pushed over the critical line
  // without hurting the owner's live work, and a simulated reading is honest
  // only if the reading itself is labelled.
  const physicalBytes = reading.physicalBytes ?? 31.62 * 1024 ** 3;
  const availableBytes = Number.isFinite(args.availableMiB) ? args.availableMiB * 1048576 : reading.availableBytes;
  reading = shapePressure({
    commitBytes: Math.round(physicalBytes * args.simulate),
    physicalBytes,
    availableBytes,
    commitLimitBytes: reading.commitLimitBytes ?? physicalBytes,
    commitAvailableBytes: reading.commitAvailableBytes ?? physicalBytes - Math.round(physicalBytes * args.simulate),
    agentsRunning: Number.isFinite(args.agents) ? args.agents : reading.agentsRunning,
    nodeProcesses: reading.nodeProcesses,
  }, { measuredAt: Date.now(), now: Date.now(), source: 'SIMULATED reading (bin/mesh-pressure.mjs --simulate) — not measured on this machine' });
}

const mesh = { localNode: localNodeName(), brokerReachable: undefined };
const decision = decidePressure(reading, mesh);

if (args.json) {
  process.stdout.write(`${JSON.stringify({
    host: reading && { hostname: process.env.COMPUTERNAME ?? null },
    reading,
    localNode: mesh.localNode,
    decision,
    thresholds: {
      highCommitPhysicalPct: HIGH_COMMIT_PHYSICAL_PCT,
      criticalCommitPhysicalPct: CRITICAL_COMMIT_PHYSICAL_PCT,
      refuseAvailableFloorBytes: REFUSE_AVAILABLE_FLOOR_BYTES,
      maxAgeMs: DEFAULT_MAX_AGE_MS,
    },
    reader: reader.probe(),
  }, null, 2)}\n`);
} else {
  const mib = (bytes) => (Number.isFinite(bytes) ? `${(bytes / 1048576).toFixed(1)} MiB` : '?');
  process.stdout.write(`${describePressure(reading, decision)}\n`);
  process.stdout.write(`raw: commitBytes=${reading.commitBytes} commitLimitBytes=${reading.commitLimitBytes}`
    + ` commitAvailableBytes=${reading.commitAvailableBytes} physicalBytes=${reading.physicalBytes}`
    + ` availableBytes=${reading.availableBytes}\n`);
  process.stdout.write(`ratios: commit/physical=${reading.commitToPhysicalPct} %`
    + `  commit/limit=${reading.commitToLimitPct} %  commitAvailable/limit=${reading.commitAvailablePct} %`
    + `  available/physical=${reading.availablePct} %\n`);
  process.stdout.write(`band=${reading.band} decision=${decision.decision}`
    + ` localNode=${mesh.localNode ?? '(not in the node table)'}`
    + ` routeAwayFromLocal=${decision.routeAwayFromLocal} refuse=${decision.refuse}\n`);
  process.stdout.write(`reason: ${decision.reason}\n`);
  process.stdout.write(`probe: spawns=${reader.probe().spawns} failures=${reader.probe().probeErrors}`
    + ` snapshot=${reader.probe().snapshotFile}${existsSync(reader.probe().snapshotFile) ? '' : ' (ABSENT)'}\n`);
}
