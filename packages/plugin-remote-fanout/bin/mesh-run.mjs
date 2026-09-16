#!/usr/bin/env node
/**
 * mesh-run — the mesh dispatcher CLI (`docs/mesh/71-mesh-program.md` §2.3).
 *
 * FLAGS (frozen): -Prompt <task> [-Node <name>] [-Children N] [-Workdir PATH] [-Json]
 * EXIT CODES (frozen): 0 completed · 10 queued · 1 failed
 *
 * WHAT IT ACTUALLY DOES, IN ORDER
 *   1. PLACE   ask the broker where this job should run — unless `-Node` names a
 *              node, in which case the broker is consulted not at all.
 *   2. CONFIGURE  turn the broker's answer into the `mesh` profile's environment:
 *              MESH_TARGET_NODE (the ssh destination) and MESH_TARGET_HOSTS (the
 *              hostnames that destination is allowed to be, §2.4).
 *   3. RUN     `dsh --profile mesh headless "<task>"` as a FRESH process in the
 *              caller's own home. The parent's children fan out to the placed
 *              node; the caller's node runs only the parent.
 *   4. VERIFY  every `MESH-HOST:` line in the report must name the node the
 *              broker named, and every `transport host =` line (recorded by the
 *              TARGET's own shell, which no model can influence) must too.
 *              Disagreement is a FAILED run, not a warning: §2.4.
 *   5. DONE    `POST /done {"lease":...}` on success or failure, so the
 *              reservation is released rather than waiting out its TTL.
 *
 * WHY THE BROKER IS REACHED OVER SSH
 * The broker is loopback-only on the authority, deliberately: a placed job must
 * not be requestable by every device on a tailnet whose ACL is allow-all. The
 * caller already has ssh to the authority, so `ssh secratary-ts curl -s
 * -XPOST localhost:3091/...` is the transport. If that is ever reconsidered, the
 * argument for publishing it would have to come with an authenticated path in
 * front of it — the same argument `66-dsh-remote-capability.md` makes for the
 * plugin route, and it is not obviously won.
 *
 * WHY THE JSON GOES IN argv AND NOT ON STDIN
 * Measured 2026-09-17: Win32-OpenSSH's client does not exit when its STDOUT is a
 * pipe (the command runs, the output arrives, the client hangs). This script
 * therefore hands ssh a single-quoted curl argument and redirects both streams
 * to temp files, the same shape `lib/ssh-transport.js` uses.
 *
 * LOGS: one JSONL file per run under `~/.dsh/mesh/logs/`, plus a `.out` file with
 * the parent's raw stdout. Every record carries the node, start, end, exit code,
 * the host the child reported, and the bytes of output.
 */

import { spawn } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';

const BROKER_SSH = process.env.MESH_BROKER_SSH ?? 'secratary-ts';
const BROKER_URL = process.env.MESH_BROKER_URL ?? 'http://localhost:3091';

/**
 * The node table: everything about a node that only the DISPATCHER can know.
 *
 * Why it has to live here and not in the `mesh` profile: the profile is booted on
 * whichever node runs the parent, so `process.platform` describes the PARENT's
 * machine, not the target's. Measured 2026-09-16: with the shell inferred from
 * the local platform, a parent on Windows dispatched to the Linux authority and
 * every child died with `bash: line 1: powershell: command not found` (exit 127).
 * The node name is known only to the placement decision, so the per-node facts
 * travel with it, as environment for the profile that is about to boot.
 *
 * `verified` records whether the two paths were ever measured on that node —
 * an empty result is not health, and an unverified path is not a placement.
 */
const NODES = {
  'zabz-tech': {
    ssh: 'desktop-ts',
    hosts: ['ZABZ-TECH', 'zabz-tech', 'zabz-tech.tail93e6e6.ts.net'],
    shell: 'powershell',
    nodeExe: 'C:/Program Files/nodejs/node.exe',
    dshBin: 'C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: 'C:/Users/ezabz',
    verified: '2026-09-17: node v24.19.0, dsh 0.1.5-rc.1, a child turn completed over ssh',
  },
  'zabz-yoga': {
    ssh: 'laptop-ts',
    hosts: ['ZABZ-YOGA', 'zabz-yoga', 'zabz-yoga-1.tail93e6e6.ts.net'],
    shell: 'powershell',
    nodeExe: 'C:/Program Files/nodejs/node.exe',
    dshBin: 'C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: 'C:/Users/ezabz',
    verified: '2026-09-17: node v24.12.0, dsh 0.1.5-rc.1, but NOT reachable as a worker over ssh — see MESH_YOGA_UNREACHABLE below',
  },
  'zabz-tech-linux': {
    ssh: 'linux-pc-ts',
    hosts: ['zabz-tech-linux'],
    shell: 'posix',
    nodeExe: '/home/zabz/.local/node-v24.12.0-linux-x64/bin/node',
    dshBin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
    verified: 'NOT VERIFIED: this node has no Node runtime yet (62-worker-runtime.md §3.1); the paths are the ones §3.4 says to install',
  },
  secratary: {
    ssh: 'secratary-ts',
    hosts: ['secratary'],
    shell: 'posix',
    nodeExe: '/home/zabz/node/bin/node',
    dshBin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
    verified: 'MEASURED 2026-09-16 (62 §1.2): node v22.23.2 at /home/zabz/node/bin/node; the dsh install is the one the systemd engine runs from',
  },
  'lakewooechsmini': {
    ssh: 'mac-mini-ts',
    hosts: ['LakewooechsMini'],
    shell: 'posix',
    nodeExe: '/usr/local/bin/node',
    dshBin: '/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/Users/lpt/lpt-hub',
    verified: 'MEASURED 2026-09-16 (62 §3.2) for the two paths; not exercised as a worker',
  },
};

const EXIT_COMPLETED = 0;
const EXIT_QUEUED = 10;
const EXIT_FAILED = 1;

function parseArgs(argv) {
  const options = { prompt: undefined, node: undefined, children: 1, workdir: undefined, json: false, timeoutMs: 900_000, dshBin: undefined, wait: true, exclude: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '-Prompt' || arg === '--prompt') options.prompt = argv[++i];
    else if (arg === '-Node' || arg === '--node') options.node = argv[++i];
    else if (arg === '-Children' || arg === '--children') options.children = Number(argv[++i]);
    else if (arg === '-Workdir' || arg === '--workdir') options.workdir = argv[++i];
    else if (arg === '-Json' || arg === '--json') options.json = true;
    else if (arg === '-TimeoutMs' || arg === '--timeout-ms') options.timeoutMs = Number(argv[++i]);
    else if (arg === '-DshBin' || arg === '--dsh-bin') options.dshBin = argv[++i];
    else if (arg === '-NoWait' || arg === '--no-wait') options.wait = false;
    else if (arg === '-Exclude' || arg === '--exclude') options.exclude.push(...String(argv[++i]).split(',').map((name) => name.trim()).filter((name) => name !== ''));
    else if (arg === '-Help' || arg === '--help' || arg === '-h') {
      console.log('mesh-run -Prompt "<task>" [-Node <name>] [-Children N] [-Workdir PATH] [-Json] [-DshBin <path>] [-TimeoutMs <n>] [-Exclude a,b] [-NoWait]');
      console.log('exit: 0 completed, 10 queued, 1 failed');
      process.exit(EXIT_COMPLETED);
    } else {
      console.error(`mesh-run: unknown argument "${arg}"`);
      process.exit(EXIT_FAILED);
    }
  }
  if (typeof options.prompt !== 'string' || options.prompt.trim() === '') {
    console.error('mesh-run: -Prompt "<task>" is required');
    process.exit(EXIT_FAILED);
  }
  return options;
}

/** Find the local dsh entry point: explicit, env, the npx cache, or PATH. */
function resolveDshBin(explicit) {
  if (explicit !== undefined) return explicit;
  if (process.env.MESH_LOCAL_DSH_BIN) return process.env.MESH_LOCAL_DSH_BIN;
  const cache = path.join(process.env.LOCALAPPDATA ?? path.join(homedir(), 'AppData', 'Local'), 'npm-cache', '_npx');
  try {
    for (const entry of readdirSync(cache)) {
      const candidate = path.join(cache, entry, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
      if (existsSync(candidate)) return candidate;
    }
  } catch {
    // no npx cache on this node
  }
  return undefined;
}

/** Quote one argument for the remote shell as a single-quoted POSIX/PowerShell-safe word. */
function singleQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

/**
 * Run one ssh command with stdout/stderr captured through FILES (never pipes —
 * see the header), bounded by a timeout.
 */
function sshRun(argv, { timeoutMs }) {
  const tag = `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const outPath = path.join(tmpdir(), `mesh-${tag}.out`);
  const errPath = path.join(tmpdir(), `mesh-${tag}.err`);
  const outFd = openSync(outPath, 'w');
  const errFd = openSync(errPath, 'w');
  const started = Date.now();
  return new Promise((resolve) => {
    const child = spawn('ssh', argv, { stdio: ['ignore', outFd, errFd], windowsHide: true });
    let timer;
    let extraTimedOut = false;
    const finish = (extra) => {
      clearTimeout(timer);
      try { closeSync(outFd); } catch { /* already closed */ }
      try { closeSync(errFd); } catch { /* already closed */ }
      const stdout = existsSync(outPath) ? readFileSync(outPath, 'utf8') : '';
      const stderr = existsSync(errPath) ? readFileSync(errPath, 'utf8') : '';
      rmSync(outPath, { force: true });
      rmSync(errPath, { force: true });
      resolve({ ms: Date.now() - started, stdout, stderr, ...extra });
    };
    child.on('error', (error) => finish({ ok: false, spawnError: String(error?.message ?? error) }));
    child.on('close', (code) => finish({
      ok: code === 0,
      exitCode: code === undefined ? undefined : code,
      timedOut: extraTimedOut,
    }));
    timer = setTimeout(() => {
      extraTimedOut = true;
      try { child.kill('SIGKILL'); } catch { /* already gone */ }
    }, timeoutMs);
    timer.unref?.();
  });
}

/** POST one JSON body to a broker route, over ssh, and parse the reply. */
async function brokerPost(route, body, timeoutMs) {
  const json = JSON.stringify(body);
  if (json.includes("'")) throw new Error('mesh-run: refusing a body containing a single quote (it is passed through a shell)');
  const curl = `curl -s -S -XPOST ${BROKER_URL}${route} -H "content-type: application/json" -d ${singleQuote(json)}`;
  const result = await sshRun(['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', BROKER_SSH, curl], { timeoutMs });
  if (!result.ok) return { ok: false, ...result, parseError: result.stderr.trim().slice(0, 400) || 'ssh to the authority failed' };
  try {
    return { ok: true, ...result, json: JSON.parse(result.stdout.trim()) };
  } catch (error) {
    return { ok: false, ...result, parseError: `unparsable broker reply: ${String(error?.message ?? error)}; body was ${result.stdout.trim().slice(0, 200)}` };
  }
}

/** Which nodes may legitimately report a given host. */
function hostMatchesNode(host, node) {
  const allowed = NODES[node]?.hosts ?? [node];
  const normalize = (value) => String(value ?? '').trim().toLowerCase().split('.')[0].replace(/-ts$/, '');
  return allowed.some((candidate) => normalize(candidate) === normalize(host));
}

/** A host token worth comparing: not the placeholder the report writes when a child never ran. */
function isHostToken(value) {
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(String(value ?? ''));
}

const options = parseArgs(process.argv.slice(2));
const dshBin = resolveDshBin(options.dshBin);
if (dshBin === undefined || !existsSync(dshBin)) {
  console.error('mesh-run: could not find @deepseek-ai/dsh/lib/bin.js — pass -DshBin <path>');
  process.exit(EXIT_FAILED);
}
const logDir = path.join(process.env.DSH_HOME ?? path.join(homedir(), '.dsh'), 'mesh', 'logs');
mkdirSync(logDir, { recursive: true });
const runId = new Date().toISOString().replace(/[:.]/g, '-');
const logPath = path.join(logDir, `${runId}.jsonl`);
const outPath = path.join(logDir, `${runId}.out`);

const record = (event) => {
  writeFileSync(logPath, `${JSON.stringify({ at: new Date().toISOString(), runId, ...event })}\n`, { flag: 'a' });
  if (!options.json) console.log(`mesh-run: ${JSON.stringify(event)}`);
};

// ---- 1. PLACE -----------------------------------------------------------------
let node = options.node;
let lease;
let placement;
if (node === undefined) {
  placement = await brokerPost('/place', {
    task: { kind: 'fleet', children: Number.isFinite(options.children) ? options.children : 1, worktreeGiB: 2, prefer: null, exclude: options.exclude },
  }, 30_000);
  if (!placement.ok) {
    record({ phase: 'place', ok: false, error: placement.parseError ?? placement.spawnError ?? 'broker unreachable' });
    console.error(`mesh-run: could not reach the broker at ${BROKER_SSH}:${BROKER_URL} (${placement.parseError ?? placement.spawnError}) — pass -Node <name> to place by hand`);
    process.exit(EXIT_FAILED);
  }
  node = placement.json.node;
  lease = placement.json.lease;
  record({
    phase: 'place',
    ok: true,
    node,
    position: placement.json.position,
    score: placement.json.score,
    eligible: placement.json.eligible,
    tier: placement.json.tier,
    blockedBy: placement.json.blockedBy ?? [],
    rationale: placement.json.rationale ?? [],
    lease,
  });
  if (!Array.isArray(placement.json.rationale) || placement.json.rationale.length === 0) {
    console.error('mesh-run: the broker named a node without a rationale — that is a bug in the decision, not a warning');
    process.exit(EXIT_FAILED);
  }
  if (Number(placement.json.position) > 0 && options.wait) {
    // Queue, never amputate: the caller is told to come back, and the frozen
    // exit code says which of the three outcomes this is.
    record({ phase: 'queued', node, position: placement.json.position });
    process.exit(EXIT_QUEUED);
  }
}

const alias = NODES[node]?.ssh;
if (alias === undefined) {
  record({ phase: 'configure', ok: false, error: `unknown node "${node}" — add it to the NODES table in mesh-run` });
  process.exit(EXIT_FAILED);
}
const nodeFacts = NODES[node];

// ---- 2/3. CONFIGURE and RUN ---------------------------------------------------
// The target's own facts travel as environment for the profile that is about to
// boot, because the profile can only see the node it runs ON (see the NODES
// comment). The parent's own machine is not a source of truth about the target.
const env = {
  ...process.env,
  MESH_TARGET_NODE: alias,
  MESH_TARGET_HOSTS: nodeFacts.hosts.join(','),
  MESH_REMOTE_SHELL: nodeFacts.shell,
  MESH_NODE_EXE: nodeFacts.nodeExe,
  MESH_DSH_BIN: nodeFacts.dshBin,
  MESH_REMOTE_CWD: options.workdir ?? nodeFacts.cwd,
};
const started = Date.now();
record({
  phase: 'run',
  node,
  alias,
  children: options.children,
  shell: nodeFacts.shell,
  targetVerified: nodeFacts.verified,
  dshBin,
  prompt: options.prompt.slice(0, 200),
  logPath,
});
const runResult = await sshRunLocal(dshBin, options.prompt, env, options.timeoutMs);
writeFileSync(outPath, runResult.stdout, 'utf8');
record({ phase: 'run-end', node, exitCode: runResult.exitCode, timedOut: runResult.timedOut, ms: Date.now() - started, stdoutBytes: runResult.stdout.length, stderrBytes: runResult.stderr.length, outPath });

// ---- 4. VERIFY ----------------------------------------------------------------
// Unanchored on purpose: a parent agent summarising its own children writes
// `CHILD=1 MESH_HOST=MESH-HOST: zabz-tech TRANSPORT=transport host = ZABZ-TECH`,
// so the tokens appear mid-line. Measured 2026-09-16 — an anchored `^MESH-HOST:`
// found zero of three and failed a run that had actually succeeded.
const meshHosts = [...runResult.stdout.matchAll(/MESH-HOST:\s*(\S+)/gi)].map((match) => match[1]).filter(isHostToken);
const transportHosts = [...runResult.stdout.matchAll(/transport host\s*=\s*(\S+)/gi)].map((match) => match[1]).filter(isHostToken);
const disagreements = [];
for (const host of [...meshHosts, ...transportHosts]) {
  if (!hostMatchesNode(host, node)) disagreements.push(host);
}
const childHosts = [...new Set(meshHosts)];
record({
  phase: 'verify',
  node,
  meshHostLines: meshHosts.length,
  transportHostLines: transportHosts.length,
  childHosts,
  disagreements,
  ok: disagreements.length === 0 && meshHosts.length >= options.children,
});

// ---- 5. DONE ------------------------------------------------------------------
if (lease !== undefined) {
  const done = await brokerPost('/done', { lease, ok: disagreements.length === 0 && (runResult.exitCode ?? 1) === 0 }, 30_000);
  record({ phase: 'done', ok: done.ok, lease, brokerSaid: done.json ?? done.parseError });
}

// ---- EXIT CONTRACT ------------------------------------------------------------
if (!options.json) {
  console.log('----- dispatcher output -----');
  console.log(runResult.stdout.trim());
  if (runResult.stderr.trim() !== '') {
    console.log('----- dispatcher stderr (tail) -----');
    console.log(runResult.stderr.trim().split('\n').slice(-15).join('\n'));
  }
}
if (runResult.timedOut) {
  record({ phase: 'result', outcome: 'failed', reason: 'timeout' });
  process.exit(EXIT_FAILED);
}
if ((runResult.exitCode ?? 1) !== 0) {
  record({ phase: 'result', outcome: 'failed', reason: `parent exit ${runResult.exitCode}` });
  process.exit(EXIT_FAILED);
}
if (disagreements.length > 0) {
  record({ phase: 'result', outcome: 'failed', reason: `location disagreement: ${disagreements.join(', ')} not on ${node}` });
  process.exit(EXIT_FAILED);
}
if (meshHosts.length < options.children) {
  record({ phase: 'result', outcome: 'failed', reason: `only ${meshHosts.length} MESH-HOST lines for ${options.children} children` });
  process.exit(EXIT_FAILED);
}
record({ phase: 'result', outcome: 'completed', node, childHosts });
process.exit(EXIT_COMPLETED);

/** Run `dsh --profile mesh headless "<task>"` as a fresh local process, files not pipes. */
function sshRunLocal(bin, prompt, envVars, timeoutMs) {
  const tag = `${process.pid}-${Date.now()}`;
  const out = path.join(tmpdir(), `meshrun-${tag}.out`);
  const err = path.join(tmpdir(), `meshrun-${tag}.err`);
  const outFd = openSync(out, 'w');
  const errFd = openSync(err, 'w');
  const startedAt = Date.now();
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [bin, '--profile', 'mesh', 'headless', prompt], {
      stdio: ['ignore', outFd, errFd],
      env: envVars,
      windowsHide: true,
    });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* gone */ }
    }, timeoutMs);
    timer.unref?.();
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ ok: false, spawnError: String(error?.message ?? error), stdout: '', stderr: '', ms: Date.now() - startedAt });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      try { closeSync(outFd); } catch { /* closed */ }
      try { closeSync(errFd); } catch { /* closed */ }
      const stdout = existsSync(out) ? readFileSync(out, 'utf8') : '';
      const stderr = existsSync(err) ? readFileSync(err, 'utf8') : '';
      rmSync(out, { force: true });
      rmSync(err, { force: true });
      resolve({ ok: code === 0, exitCode: code === undefined ? undefined : code, stdout, stderr, timedOut, ms: Date.now() - startedAt });
    });
  });
}
