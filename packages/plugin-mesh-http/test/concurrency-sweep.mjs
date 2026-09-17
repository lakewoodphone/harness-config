/**
 * The transport-concurrency sweep — one level of N concurrent children, over ONE transport.
 *
 * WHAT THIS MEASURES, AND WHAT IT DELIBERATELY DOES NOT
 * It measures what the CALLER can see and control: how many children it asked for, when each one
 * started and finished, what each one reported, and — for the HTTP transport — which of them were
 * admitted immediately and which were QUEUED behind the node's own derived ceiling.
 *
 * It does NOT claim to measure concurrency. The number that matters is read on the TARGET, from
 * that machine's own process list, by `sweep-sampler.ps1`. A caller's "I started 12" is a claim
 * about intent; this program's job is to make the claim, so the target can be checked against it.
 *
 * THE TWO TRANSPORTS, AS THEY ACTUALLY ARE
 *   v1 (ssh) — one `ssh` per child, and NOTHING in the transport limits how many at once
 *              (`plugin-remote-fanout/lib/ssh-transport.js` has no slot of any kind). The ssh
 *              client's streams go to FILES, never to pipes, because a Windows ssh client whose
 *              stdout is a pipe does not exit (`70-remote-fanout-proof.md` §4.1, measured).
 *   v2 (http)— one signed `POST /mesh/run` per child through the node's own route and gate. The
 *              node admits up to its derived `maxConcurrent` and gives every further request a
 *              POSITION, answered in arrival order.
 *
 * Usage (from a checkout of harness-config, on any node with ssh access to the target):
 *
 *   node packages/plugin-mesh-http/test/concurrency-sweep.mjs \
 *     --node zabz-tech --transport v2 --n 12 --seconds 300 --label v2-n12 \
 *     --secret-file C:/Users/ezabz/target-secret.env --out C:/Users/ezabz/mesh-sweep
 *
 * Every child runs the SAME short prompt, so a level differs from another only in N and transport.
 */

import { spawn } from 'node:child_process';
import { mkdirSync, openSync, closeSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { MeshAuth } from '../lib/auth.js';
import { NODES, hostMatchesNode, extractHosts } from '../bin/mesh-dispatch.mjs';

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));

export function parseArgs(argv) {
  const options = {
    node: undefined, transport: 'v2', n: 4, seconds: 240, label: 'level',
    secretFile: undefined, out: undefined, timeoutSec: 240, tailnet: process.env.MESH_TAILNET ?? 'tail93e6e6.ts.net',
    gapMs: 0,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--node') options.node = argv[++i];
    else if (arg === '--transport') options.transport = String(argv[++i]).toLowerCase();
    else if (arg === '--n') options.n = Number(argv[++i]);
    else if (arg === '--seconds') options.seconds = Number(argv[++i]);
    else if (arg === '--label') options.label = argv[++i];
    else if (arg === '--secret-file') options.secretFile = argv[++i];
    else if (arg === '--out') options.out = argv[++i];
    else if (arg === '--timeout-sec') options.timeoutSec = Number(argv[++i]);
    else if (arg === '--tailnet') options.tailnet = argv[++i];
    else throw new Error(`unknown argument "${arg}"`);
  }
  if (typeof options.node !== 'string' || NODES[options.node] === undefined) {
    throw new Error(`--node must be one of ${Object.keys(NODES).join(', ')}`);
  }
  if (options.transport !== 'v1' && options.transport !== 'v2') throw new Error('--transport must be v1 or v2');
  if (options.transport === 'v2' && (typeof options.secretFile !== 'string' || options.secretFile === '')) {
    // Checked HERE and not at first use: the sampler is started before the first request, so a
    // missing secret would otherwise cost the capture window before failing on the first child.
    throw new Error('--secret-file is required for transport v2 (a dispatcher signs with the TARGET node\'s secret)');
  }
  if (!Number.isFinite(options.n) || options.n < 1) throw new Error('--n must be a positive integer');
  return options;
}

/**
 * The prompt every child in every level receives — identical, so N and transport are the only deltas.
 *
 * The `MESH-HOST:` line is the proof of location and it MUST survive into the child's answer
 * (`71` §2.4). The first version of this prompt ended with "reply with exactly one line: SWEEP-OK …",
 * and the child obeyed the nearer instruction and dropped the preamble — a run with
 * `meshHostLines: 0`, which is the exact shape `83-http-transport.md` §8 warns reads as "a run whose
 * children did not report". The line is therefore demanded in the same breath as the answer.
 */
export function sweepTask(host) {
  return [
    `You are running on the node "${host}".`,
    `Begin your final report with exactly this line: MESH-HOST: ${host}`,
    'Then do the task. Be concise.',
    '',
    'Run the shell command: Start-Sleep -Seconds 4 ; hostname',
    'Then reply with exactly these two lines and nothing else:',
    `MESH-HOST: ${host}`,
    'SWEEP-OK <the hostname it printed>',
  ].join('\n');
}

export function readSecret(file) {
  const text = readFileSync(file, 'utf8');
  const match = /^\s*(?:export\s+)?MESH_HTTP_SECRET\s*=\s*(.+?)\s*$/m.exec(text);
  if (match === null) throw new Error(`no MESH_HTTP_SECRET= line in ${file}`);
  return match[1].replace(/^["']|["']$/g, '');
}

/**
 * One child over transport v1: an `ssh` whose two streams are FILES.
 * The PowerShell program travels as `-EncodedCommand`, because between this PowerShell and the
 * target's there is a bash that rewrites the remote command line (`ship-to-node.ps1`'s header has
 * the measurement) and `-EncodedCommand` has no quoting surface at all.
 */
function spawnSshChild({ facts, task, outDir, index, timeoutSec }) {
  // THIS RIG IS WINDOWS-ONLY, and it says so rather than measuring a node with a program its shell
  // cannot run: the child travels as a PowerShell `-EncodedCommand` (`70` §4.1's measurement is
  // about the ssh session). A POSIX node is refused here — the POSIX v1 path is
  // `bin/mesh-dispatch.mjs`'s, which is proven against the live node in docs/mesh/104-node-enabled.md.
  if (facts.shell !== 'powershell') {
    throw new Error(`--transport v1 in this rig is Windows-only: ${facts.label} runs ${facts.shell}`);
  }
  // THE INVOCATION COMES FROM THE SHARED TABLE (`plugin-remote-fanout/lib/nodes.js`, via
  // `bin/mesh-dispatch.mjs`), so this rig runs the same command the dispatcher does instead of a
  // second copy of the paths that can rot on its own.
  const { invocation } = facts;
  const parts = [invocation.command, ...(invocation.argvPrefix ?? [])].map((word) => `'${String(word)}'`);
  const program = [
    '$ErrorActionPreference = "Continue"',
    `& ${parts.join(' ')} --profile headless '${task.replace(/'/g, "''")}'`,
    'exit $LASTEXITCODE',
  ].join("\n");
  const encoded = Buffer.from(program, 'utf16le').toString('base64');
  const outPath = path.join(outDir, `v1-${index}.stdout.txt`);
  const errPath = path.join(outDir, `v1-${index}.stderr.txt`);
  const outFd = openSync(outPath, 'w');
  const errFd = openSync(errPath, 'w');
  const startedAt = Date.now();
  const child = spawn('ssh', [
    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
    facts.ssh,
    'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded,
  ], { stdio: ['ignore', outFd, errFd], windowsHide: true });
  const record = { index, transport: 'v1', startedAt: new Date(startedAt).toISOString(), startedAtMs: startedAt, outPath, errPath };
  const timer = setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* gone */ } }, (timeoutSec + 60) * 1000);
  return new Promise((resolve) => {
    const finish = (exitCode) => {
      clearTimeout(timer);
      try { closeSync(outFd); } catch { /* closed */ }
      try { closeSync(errFd); } catch { /* closed */ }
      const stdout = safeRead(outPath);
      const stderr = safeRead(errPath);
      resolve({
        ...record,
        endedAtMs: Date.now(),
        // MINUS the ssh client's own ~1-2 s of session setup, when it can be seen: the child prints
        // its own answer, and the wall clock is what the caller actually waited for. Both are kept.
        ms: Date.now() - startedAt,
        exitCode,
        stdoutBytes: Buffer.byteLength(stdout),
        stdout,
        stderrTail: stderr.slice(-400),
        childHosts: [...new Set([...extractHosts(stdout).meshHosts])],
        meshHostLines: extractHosts(stdout).meshHosts.length,
      });
    };
    child.on('error', (error) => finish(`spawn-error:${error?.message ?? error}`));
    child.on('close', (code) => finish(code ?? null));
  });
}

/** One child over transport v2: one signed POST to the node's own route, through its gate. */
function spawnHttpChild({ base, secret, task, index, timeoutSec, node }) {
  const startedAt = Date.now();
  const body = JSON.stringify({ prompt: task, meshHost: node, timeoutSec });
  const headers = MeshAuth.headersFor({ secret, body: Buffer.from(body, 'utf8') });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error('timeout')), (timeoutSec + 60) * 1000);
  return fetch(`${base}/mesh/run`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body,
    signal: controller.signal,
  }).then(async (response) => {
    clearTimeout(timer);
    const text = await response.text();
    let json;
    try { json = JSON.parse(text); } catch { json = undefined; }
    const stdout = json?.stdout ?? '';
    return {
      index, transport: 'v2',
      startedAt: new Date(startedAt).toISOString(), startedAtMs: startedAt,
      endedAtMs: Date.now(), ms: Date.now() - startedAt,
      httpStatus: response.status,
      exitCode: json?.exitCode ?? null,
      timedOut: json?.timedOut === true,
      // WHERE THE NODE SAYS THIS REQUEST WAITED. position 0 = admitted immediately.
      queue: json?.queue ?? null,
      reason: json?.reason ?? null,
      nodeSaysItIs: json?.node ?? null,
      stdout,
      stderrTail: String(json?.stderr ?? '').slice(-400),
      childHosts: [...new Set(extractHosts(stdout).meshHosts)],
      meshHostLines: extractHosts(stdout).meshHosts.length,
      disagreements: [...extractHosts(stdout).meshHosts].filter((h) => !hostMatchesNode(h, node)),
    };
  }).catch((error) => {
    clearTimeout(timer);
    return {
      index, transport: 'v2', startedAt: new Date(startedAt).toISOString(), startedAtMs: startedAt,
      endedAtMs: Date.now(), ms: Date.now() - startedAt, ok: false,
      error: String(error?.cause?.code ?? error?.message ?? error),
    };
  });
}

function safeRead(file) {
  try { return readFileSync(file, 'utf8'); } catch { return ''; }
}

/** Fire all N at once, from a single synchronous loop — the concurrency is the caller's, not a queue's. */
export async function runLevel(options) {
  const facts = NODES[options.node];
  const base = `https://${facts.label}.${options.tailnet}`;
  const task = sweepTask(facts.hosts[0]);
  const outDir = options.out === undefined ? path.join(tmpdir(), `mesh-sweep-${options.label}`) : path.join(options.out, options.label);
  mkdirSync(outDir, { recursive: true });
  const startedAt = Date.now();

  const pending = [];
  if (options.transport === 'v1') {
    for (let i = 1; i <= options.n; i += 1) {
      pending.push(spawnSshChild({ facts, task, outDir, index: i, timeoutSec: options.timeoutSec }));
    }
  } else {
    const secret = readSecret(options.secretFile);
    for (let i = 1; i <= options.n; i += 1) {
      pending.push(spawnHttpChild({ base, secret, task, index: i, timeoutSec: options.timeoutSec, node: options.node }));
    }
  }
  const results = await Promise.all(pending);
  const wallMs = Date.now() - startedAt;

  const children = results.map((r) => ({
    index: r.index,
    ms: r.ms,
    httpStatus: r.httpStatus ?? null,
    exitCode: r.exitCode ?? null,
    ok: r.transport === 'v2'
      ? (r.httpStatus === 200 && r.exitCode === 0)
      : (r.exitCode === 0 && r.meshHostLines > 0),
    queuePosition: r.queue?.position ?? null,
    queueWaitedMs: r.queue?.waitedMs ?? null,
    meshHostLines: r.meshHostLines ?? 0,
    childHosts: r.childHosts ?? [],
    disagreements: r.disagreements ?? [],
    reportedHostOk: (r.childHosts ?? []).length > 0 && (r.childHosts ?? []).every((h) => hostMatchesNode(h, options.node)),
  }));

  return {
    level: options.label,
    node: options.node,
    transport: options.transport,
    requested: options.n,
    url: options.transport === 'v2' ? `${base}/mesh/run` : `ssh ${facts.ssh}`,
    startedAt: new Date(startedAt).toISOString(),
    wallMs,
    children,
    summary: {
      started: children.length,
      answered: children.filter((c) => c.ok).length,
      reportedCorrectHost: children.filter((c) => c.reportedHostOk).length,
      refused: children.filter((c) => c.httpStatus !== null && c.httpStatus !== 200).length,
      admittedImmediately: children.filter((c) => c.queuePosition === 0).length,
      queued: children.filter((c) => typeof c.queuePosition === 'number' && c.queuePosition > 0).length,
      maxQueuePosition: children.reduce((m, c) => Math.max(m, c.queuePosition ?? 0), 0),
      maxQueueWaitMs: children.reduce((m, c) => Math.max(m, c.queueWaitedMs ?? 0), 0),
      wallMsMin: children.reduce((m, c) => Math.min(m, c.ms), Infinity),
      wallMsMax: children.reduce((m, c) => Math.max(m, c.ms), 0),
      wallMsMean: Math.round(children.reduce((a, c) => a + c.ms, 0) / children.length),
    },
    raw: results,
  };
}

const isMain = process.argv[1] !== undefined
  && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
if (isMain) {
  const options = parseArgs(process.argv.slice(2));
  const result = await runLevel(options);
  const outDir = options.out ?? tmpdir();
  mkdirSync(outDir, { recursive: true });
  writeFileSync(path.join(outDir, `${options.label}-caller.json`), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  const brief = {
    ...result,
    raw: result.raw.map((r) => ({ ...r, stdout: (r.stdout ?? '').slice(0, 200), stderrTail: undefined })),
  };
  process.stdout.write(`${JSON.stringify(brief, null, 2)}\n`);
  process.write?.('');
  process.exit(0);
}
