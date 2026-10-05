// Diagnostic harness (not a test): exercise the REAL provider dispatch path
// against the real node table and the real ssh transport, print the generated
// script, the outcome and the transport argv.
//
// usage: node test/repro-mesh-dispatch.mjs [--short] [--node <name>] [--keep]
//        node test/repro-mesh-dispatch.mjs --broker          (the deployed path: broker placement)
import { writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { RemoteOneShotProvider, DEFAULT_TASK_PREAMBLE, renderTaskPreamble } from '../lib/provider.js';
import { createSshTransport } from '../lib/ssh-transport.js';
import { createNodePlacer, createPlacementLedger } from '../lib/placement.js';
import { createBrokerClient } from '../lib/broker-client.js';
import { NODES, resolveNodeInvocation } from '../lib/nodes.js';
import { meshChildPaths } from '../lib/remote-script.js';

const argv = process.argv.slice(2);
const brokerMode = argv.includes('--broker');
const nodeName = argv.includes('--node') ? argv[argv.indexOf('--node') + 1] : 'zabz-tech';
const short = argv.includes('--short');
const keep = argv.includes('--keep');

const token = `CHILD-${randomBytes(5).toString('hex').toUpperCase()}`;
const id = `repro-${randomBytes(4).toString('hex')}`;
const body = short
  ? 'Reply with exactly one line: MESH-HOST-PROBE-OK'
  : `Run this and report its output, then stop: pwsh -NoProfile -Command "\\"$env:COMPUTERNAME $env:USERPROFILE ${token}\\""`;

const logger = { info: (m) => console.log(`[info] ${m}`), warn: (m) => console.log(`[warn] ${m}`) };
const SSH_ARGS = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=25', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4'];

let provider;
let task;

if (brokerMode) {
  const broker = createBrokerClient({ sshTarget: 'secratary-ts', url: 'http://localhost:3091', timeoutMs: 30000, logger });
  const placer = createNodePlacer({
    broker,
    nodes: NODES,
    logger,
    ledger: createPlacementLedger({ logger }),
    remoteProfile: 'headless',
    sshExe: 'ssh',
    sshArgs: SSH_ARGS,
    queueWaitMs: 120000,
    queuePollMs: 5000,
    preferRemote: true,
  });
  provider = new RemoteOneShotProvider({ name: 'repro-broker', placer, logger, verifyMeshHost: true });
  task = `${renderTaskPreamble(DEFAULT_TASK_PREAMBLE, meshChildPaths({ dshHome: undefined, id, shell: 'powershell' }))}\n${body}`;
} else {
  const facts = NODES[nodeName];
  if (facts === undefined) throw new Error(`unknown node ${nodeName}`);
  const transport = createSshTransport({ sshExe: 'ssh', sshArgs: SSH_ARGS, target: facts.ssh });
  provider = new RemoteOneShotProvider({
    name: 'repro',
    transport,
    remote: { nodeExe: facts.driver, dshBin: facts.bin, profile: 'headless', cwd: facts.cwd, shell: facts.shell },
    targetHosts: facts.hosts,
    timeoutMs: 300000,
    logger,
  });
  task = short
    ? body
    : `${renderTaskPreamble(DEFAULT_TASK_PREAMBLE, meshChildPaths({ dshHome: facts.dshHome, id, shell: facts.shell }))}\n${body}`;
  console.log(`# node=${nodeName} ssh=${facts.ssh}`);
  console.log(`# resolved invocation = ${JSON.stringify(resolveNodeInvocation(facts))}`);
}

console.log(mode(provider), `# child id = ${id}`);
console.log(`# task bytes = ${Buffer.byteLength(task, 'utf8')}`);
console.log(`# token the CHILD must produce = ${token}`);

const started = Date.now();
const run = await provider.start({ prompt: [{ type: 'text', text: task }] });
const settled = await run.result;
await run.dispose?.();

console.log(`### stopReason = ${settled.stopReason} (${Date.now() - started} ms wall)`);
console.log('### diagnostic =', settled.diagnostic ?? '(none)');
console.log('### output =');
console.log(settled.output?.map((b) => b.text).join('\n') ?? '(none)');

function mode(p) {
  return `# placement = ${p.placementKind} — ${p.describePlacement?.() ?? '?'}`;
}
