#!/usr/bin/env node
/**
 * O2 evidence — the question the manager asked: if the ssh transport to the node the broker named
 * fails, does anything run the child locally or on another node?
 *
 * WHAT THIS DRIVES, AND WHY IT IS NOT A SIMULATION
 * It imports the REAL transport (`packages/plugin-remote-fanout/lib/ssh-transport.js`, read-only)
 * and the REAL provider (`lib/provider.js`) and points them at a destination that cannot be
 * reached, then reports what came back. No double, no stub: the ssh client that runs is the one
 * the mesh uses. Only the destination is sabotaged, and only for this one process — nothing in
 * the fleet's configuration is edited, so nothing has to be restored afterwards.
 *
 * THE SABOTAGE, EXACTLY
 *   ssh -p 1 ezabz@127.0.0.1 ...
 * Port 1 on loopback has no listener, so the client refuses the connection in milliseconds
 * (measured below) with exit 255. `BatchMode=yes` stops it from ever prompting for a password,
 * and `ConnectTimeout=5` bounds it. On this machine ssh is Win32-OpenSSH, which is the same
 * client transport v1 uses on the two Windows nodes.
 *
 * THE THREE THINGS THE ANSWER TURNS ON
 *   1. where the child RAN — the marker file this script writes only on the machine that runs it,
 *      plus the provider's own `transport host =` line, which the target shell records;
 *   2. whether anything was executed at the destination at all (a refusal is not a run);
 *   3. what the caller finally sees: `stopReason`, the diagnostic, and the exit code.
 *
 * This script writes exactly one file — the marker in its own directory, beside it — and removes
 * nothing.
 */

import { existsSync, writeFileSync } from 'node:fs';
import { hostname } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { RemoteOneShotProvider, DEFAULT_TASK_PREAMBLE, MESH_HOST_LINE } from '../../plugin-remote-fanout/lib/provider.js';
import { createSshTransport } from '../../plugin-remote-fanout/lib/ssh-transport.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MARKER = path.join(HERE, 'dead-target-marker.txt');
const MARKER_TEXT = `O2-DEAD-TARGET-MARKER written on ${hostname()} at ${new Date().toISOString()}`;

/** The destination that does not answer: loopback port 1, BatchMode, short connect timeout. */
const DEAD_TARGET = 'ezabz@127.0.0.1';
const DEAD_ARGS = ['-p', '1', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5'];

writeFileSync(MARKER, `${MARKER_TEXT}\n`, 'utf8');

const transport = createSshTransport({ sshArgs: DEAD_ARGS, target: DEAD_TARGET, timeoutMs: 30_000 });
const provider = new RemoteOneShotProvider({
  name: 'remote-ssh-deadproof',
  transport,
  remote: {
    nodeExe: 'C:/Program Files/nodejs/node.exe',
    dshBin: 'C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js',
    profile: 'headless',
    cwd: 'C:/Users/ezabz',
    shell: 'powershell',
  },
  timeoutMs: 30_000,
  targetHosts: ['zabz-tech'],
});

const task = [
  'Read the file ' + MARKER + ' and print its whole contents.',
  'Then print the hostname of the machine you are running on.',
].join('\n');

const startedAt = Date.now();
const run = await provider.start({ prompt: [{ type: 'text', text: task }], signal: new AbortController().signal });
const result = await run.result;
const text = result.output.map((block) => block.text).join('');

const report = {
  at: new Date().toISOString(),
  proof: 'does a failed ssh transport fall back to running the child anywhere?',
  sabotage: `${transport.describe()}  (no listener on loopback port 1)`,
  askedTask: task,
  childStartedAnywhere: { markerExistsHere: existsSync(MARKER), markerText: MARKER_TEXT },
  stopReason: result.stopReason,
  diagnostic: result.diagnostic ?? null,
  providerText: text,
  sawMeshHostLine: text.includes(MESH_HOST_LINE),
  sawSshRefusal: /Connection refused|connect to host|No connection could be made/i.test(text),
  ms: Date.now() - startedAt,
};

console.log(JSON.stringify(report, null, 2));
await run.dispose();
