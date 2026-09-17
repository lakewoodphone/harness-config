#!/usr/bin/env node
/**
 * mesh-dispatch — one task to one named node, over transport v2 (this plugin's HTTP route) with an
 * EXPLICIT, LOGGED fallback to transport v1 (ssh + `--profile headless`).
 *
 * WHY THERE IS A FALLBACK AT ALL, AND WHAT IT IS ALLOWED TO BE
 * The fleet is heterogeneous: a node may not have this plugin mounted (the laptop cannot be
 * restarted for it tonight), it may be an older build, or its engine may be down while the machine
 * itself is fine. Refusing to use such a node throws away real capacity. So v1 stays.
 *
 * What a fallback must NEVER be is silent. Three rules are enforced here and each one is visible in
 * the JSONL record and in the exit code:
 *
 *   1. **The transport is named.** `transport: "http"` or `transport: "ssh"`, every run, plus the
 *      reason the other one was not used. A run that reports where the broker said while having run
 *      somewhere else is worse than no routing at all.
 *   2. **The fallback happens before anything runs, never after.** v2 is probed with
 *      `GET /mesh/health` (cheap, no prompt). Only if that probe fails, or the POST fails to
 *      connect, does v1 run. If the route ACCEPTED the prompt and then the child failed, that is a
 *      failed run — v1 is NOT tried, because the node has already been given the work and running it
 *      twice on two machines is exactly the duplicate the owner must never get.
 *   3. **A fallback the caller did not ask for is a failure.** `--require-v2` makes a v2 refusal
 *      terminal, which is what a proof run uses so that a green result cannot be v1 in disguise.
 *
 * WHAT IT DOES NOT DO, AND WHY THAT MATTERS MORE THAN IT SOUNDS
 * It does not run the child anywhere except the node it was told to use. There is no local path, no
 * second candidate node, and no retry elsewhere — a run that cannot reach its node FAILS, naming the
 * node. Measured 2026-09-17 against the real transport: a dead destination produces
 * `stopReason: 'error'` and a child that ran NOWHERE (`test/dead-target-fallback.mjs`, and
 * `docs/mesh/83-http-transport.md` §8, which answers the manager's question about whether a failed
 * ssh transport falls back to running work locally). A routing system that runs work where it likes
 * while reporting where the broker said is worse than no routing at all, and this is the one place
 * where that property is enforced for transport v2.
 *
 * `MESH_SSH_EXE` exists for exactly one purpose: a test that needs v1 to be impossible (point it at
 * a program that does not exist). It is the sabotage a proof documents, not a production knob.
 *
 * WHAT IT DOES NOT DO
 * It does not choose a node. Placement is the broker's (`71` §2.2) and this script only carries out
 * a decision it was given (`--node`), which keeps the thing that decides apart from the thing that
 * moves bytes. It also does not verify `MESH-HOST:` — that is the caller's job, and it is printed
 * and recorded here so the caller can.
 *
 * EXIT CODES: 0 answered (whatever the child's own exit code was — see `childExitCode`), 1 the
 * transport failed, 2 the node is unknown here, 3 the caller asked for v2 and it was unavailable.
 */

import { spawn } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { MeshAuth } from '../lib/auth.js';
import { parseEnvText } from '../lib/secret.js';

/**
 * Per-node facts only the DISPATCHER can know, and the reason this table is in the caller rather
 * than in a profile: a profile boots on whichever node runs the parent, so `process.platform`
 * describes the parent, not the target (`70` §4.5, measured).
 *
 * `url` is how transport v2 reaches the node THROUGH THE GATE: `tailscale serve` publishes
 * `https://<label>.tail<tailnet>.ts.net/` on the node itself and the gate relays everything it does
 * not answer itself to `127.0.0.1:3089`, where the engine and this route live (`71` §1). The gate's
 * device allow-list is in front of the route, and the route's HMAC is on top of it.
 *
 * `ssh` is transport v1's destination. `hosts` is every name the node may legitimately report, for
 * the `MESH-HOST:` check — note `zabz-yoga-1` (the tailnet DNS label) beside `ZABZ-YOGA` (the
 * machine's own hostname): a child prints the latter and the broker names the former, and a check
 * that only knew one of them would either fail a good run or pass a wrong one (`70` §2.6).
 */
export const NODES = {
  'zabz-tech': {
    ssh: 'desktop-ts',
    label: 'zabz-tech',
    hosts: ['ZABZ-TECH', 'zabz-tech', 'zabz-tech.tail93e6e6.ts.net'],
    shell: 'powershell',
    nodeExe: 'C:/Program Files/nodejs/node.exe',
    dshBin: 'C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: 'C:/Users/ezabz',
  },
  'zabz-yoga-1': {
    ssh: 'laptop-ts',
    label: 'zabz-yoga-1',
    hosts: ['ZABZ-YOGA', 'zabz-yoga', 'zabz-yoga-1', 'zabz-yoga-1.tail93e6e6.ts.net'],
    shell: 'powershell',
    nodeExe: 'C:/Program Files/nodejs/node.exe',
    dshBin: 'C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: 'C:/Users/ezabz',
  },
  secratary: {
    ssh: 'secratary-ts',
    label: 'secratary',
    hosts: ['secratary', 'secratary.tail93e6e6.ts.net'],
    shell: 'posix',
    nodeExe: '/home/zabz/node/bin/node',
    dshBin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
  },
  'lakewooechsmini': {
    ssh: 'mac-mini-ts',
    label: 'lakewooechsmini',
    hosts: ['LakewooechsMini', 'lakewooechsmini', 'lakewooechsmini.tail93e6e6.ts.net'],
    shell: 'posix',
    nodeExe: '/usr/local/bin/node',
    dshBin: '/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/Users/lpt/lpt-hub',
  },
  'zabz-tech-linux': {
    ssh: 'linux-pc-ts',
    label: 'zabz-tech-linux',
    hosts: ['zabz-tech-linux'],
    shell: 'posix',
    nodeExe: '/home/zabz/.local/node-v24.12.0-linux-x64/bin/node',
    dshBin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
  },
};

const TAILNET = process.env.MESH_TAILNET ?? 'tail93e6e6.ts.net';
/**
 * The ssh client transport v1 uses. `MESH_SSH_EXE` exists so a TEST can put the v1 path beyond
 * use — point it at a program that does not exist and the fallback cannot silently succeed, which
 * is what the ssh-disabled proof needs. It is the sabotage the proof documents, not a knob.
 */
const SSH_EXE = process.env.MESH_SSH_EXE ?? 'ssh';
const EXIT_OK = 0;
const EXIT_TRANSPORT_FAILED = 1;
const EXIT_UNKNOWN_NODE = 2;
const EXIT_V2_REQUIRED = 3;

export function parseArgs(argv) {
  const options = {
    node: undefined, prompt: undefined, timeoutSec: 900, wantJson: false,
    requireV2: false, noFallback: false, allowFallback: false, quiet: false,
    secretFile: undefined, cwd: undefined, logDir: undefined, dryRun: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '-Node' || arg === '--node') options.node = argv[++i];
    else if (arg === '-Prompt' || arg === '--prompt') options.prompt = argv[++i];
    else if (arg === '-PromptFile' || arg === '--prompt-file') options.prompt = readFileSync(argv[++i], 'utf8');
    else if (arg === '-TimeoutSec' || arg === '--timeout-sec') options.timeoutSec = Number(argv[++i]);
    else if (arg === '-Json' || arg === '--json') options.wantJson = true;
    else if (arg === '-Quiet' || arg === '--quiet') options.quiet = true;
    else if (arg === '-RequireV2' || arg === '--require-v2') options.requireV2 = true;
    else if (arg === '-NoFallback' || arg === '--no-fallback') options.noFallback = true;
    else if (arg === '--allow-fallback') options.allowFallback = true;
    else if (arg === '-SecretFile' || arg === '--secret-file') options.secretFile = argv[++i];
    else if (arg === '-Workdir' || arg === '--workdir') options.cwd = argv[++i];
    else if (arg === '-LogDir' || arg === '--log-dir') options.logDir = argv[++i];
    else if (arg === '--dry-run') options.dryRun = true;
    else if (arg === '-Help' || arg === '--help' || arg === '-h') {
      process.stdout.write([
        'mesh-dispatch -Node <node> -Prompt "<task>" [options]',
        '  -TimeoutSec N        wall-clock bound for one turn (default 900)',
        '  -RequireV2           refuse to fall back to ssh; a v2 refusal is terminal (exit 3)',
        '  -NoFallback          same as -RequireV2, kept for callers that spell it that way',
        '  -Workdir PATH        working directory ON THE TARGET (needs the node to allow it)',
        '  -SecretFile PATH     this dispatcher\'s own shared secret (default: this node\'s)',
        '  -Json                print only the JSONL records',
        'exit: 0 answered (a child exit code is in the record), 1 transport failed, 2 unknown node, 3 v2 required',
        '',
      ].join('\n'));
      process.exit(EXIT_OK);
    } else {
      process.stderr.write(`mesh-dispatch: unknown argument "${arg}"\n`);
      process.exit(EXIT_TRANSPORT_FAILED);
    }
  }
  if (typeof options.node !== 'string' || options.node.trim() === '') {
    process.stderr.write('mesh-dispatch: -Node <name> is required (this script does not choose a node)\n');
    process.exit(EXIT_UNKNOWN_NODE);
  }
  if (typeof options.prompt !== 'string' || options.prompt.trim() === '') {
    process.stderr.write('mesh-dispatch: -Prompt "<task>" is required\n');
    process.exit(EXIT_TRANSPORT_FAILED);
  }
  if (options.noFallback) options.requireV2 = true;
  return options;
}

/** This node's own secret file, by platform. The dispatcher authenticates with ITS node's secret. */
export function defaultDispatcherSecretFile(platform = process.platform) {
  return process.env.MESH_HTTP_SECRET_FILE ?? (platform === 'win32' ? 'C:/ProgramData/dsh-mesh.env' : '/etc/dsh-mesh.env');
}

/**
 * Read one secret FILE's `MESH_HTTP_SECRET=`. The dispatcher reads its own file directly rather
 * than importing the plugin, so a dispatch does not depend on the plugin being loadable on the
 * CALLER — a node may be a dispatcher long before it is a worker.
 */
export function readSecret(file) {
  try {
    const value = parseEnvText(readFileSync(file, 'utf8')).get('MESH_HTTP_SECRET')
      ?? parseEnvText(readFileSync(file, 'utf8')).get('MESH_SECRET');
    if (typeof value !== 'string' || value.trim().length < 16) {
      return { ok: false, reason: `${file} has no usable MESH_HTTP_SECRET (a secret is at least 16 bytes)` };
    }
    return { ok: true, secret: value.trim(), path: file };
  } catch (error) {
    return { ok: false, reason: `cannot read ${file} (${error?.code ?? error?.message ?? error})` };
  }
}

/** Where a run's record goes: one JSONL per dispatch, beside the mesh's other records. */
export function defaultLogDir() {
  return path.join(process.env.DSH_HOME ?? path.join(homedir(), '.dsh'), 'mesh', 'logs');
}

/** Every name that may legitimately report as this node, compared loosely but not loosely enough. */
export function hostMatchesNode(host, node) {
  const facts = NODES[node];
  const allowed = facts?.hosts ?? [node];
  const normalize = (value) => String(value ?? '').trim().toLowerCase().split('.')[0].replace(/-ts$/, '');
  return allowed.some((candidate) => normalize(candidate) === normalize(host));
}

/** A `MESH-HOST:` token worth comparing — the report writes `(not reported)` when a child never ran. */
export function isHostToken(value) {
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(String(value ?? ''));
}

/** The lines a caller must be able to check. Unanchored on purpose (`70` §4.6). */
export function extractHosts(text) {
  const meshHosts = [...String(text ?? '').matchAll(/MESH-HOST:\s*(\S+)/gi)].map((m) => m[1]).filter(isHostToken);
  const transportHosts = [...String(text ?? '').matchAll(/transport host\s*=\s*(\S+)/gi)].map((m) => m[1]).filter(isHostToken);
  return { meshHosts, transportHosts };
}

/** POST one signed body to a node's route. Bounded in every direction by construction. */
export async function postToNode({ url, body, secret, timeoutMs, fetchImpl = fetch }) {
  const bytes = Buffer.from(body, 'utf8');
  const headers = {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(bytes.byteLength),
    'x-mesh-request-id': `dispatch-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    ...MeshAuth.headersFor({ secret, body: bytes }),
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error('dispatch timeout')), timeoutMs);
  try {
    const response = await fetchImpl(url, { method: 'POST', headers, body: bytes, signal: controller.signal });
    const text = await response.text();
    let json;
    try { json = JSON.parse(text); } catch { json = undefined; }
    return { ok: true, status: response.status, json, text, headers };
  } catch (error) {
    return { ok: false, error: String(error?.cause?.code ?? error?.message ?? error), headers };
  } finally {
    clearTimeout(timer);
  }
}

/** Probe a node's route without spending a prompt. */
export async function probeRoute({ base, timeoutMs = 5000, fetchImpl = fetch }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error('probe timeout')), timeoutMs);
  try {
    const response = await fetchImpl(`${base}/mesh/health`, { method: 'GET', signal: controller.signal });
    const text = await response.text();
    let json;
    try { json = JSON.parse(text); } catch { json = undefined; }
    return { ok: response.ok, status: response.status, json, text };
  } catch (error) {
    return { ok: false, error: String(error?.cause?.code ?? error?.message ?? error) };
  } finally {
    clearTimeout(timer);
  }
}

/** ssh with both streams to FILES — never pipes, and that is measured (`70` §4.1). */
function sshRun(argv, { timeoutMs }) {
  const tag = `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const outPath = path.join(tmpdir(), `meshdispatch-${tag}.out`);
  const errPath = path.join(tmpdir(), `meshdispatch-${tag}.err`);
  const outFd = openSync(outPath, 'w');
  const errFd = openSync(errPath, 'w');
  const started = Date.now();
  return new Promise((resolve) => {
    let timedOut = false;
    const child = spawn(SSH_EXE, argv, { stdio: ['ignore', outFd, errFd], windowsHide: true });
    const finish = (extra) => {
      clearTimeout(timer);
      try { closeSync(outFd); } catch { /* closed */ }
      try { closeSync(errFd); } catch { /* closed */ }
      const stdout = existsSync(outPath) ? readFileSync(outPath, 'utf8') : '';
      const stderr = existsSync(errPath) ? readFileSync(errPath, 'utf8') : '';
      rmSync(outPath, { force: true });
      rmSync(errPath, { force: true });
      resolve({ ms: Date.now() - started, stdout, stderr, timedOut, ...extra });
    };
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* gone */ }
    }, timeoutMs);
    timer.unref?.();
    child.on('error', (error) => finish({ ok: false, spawnError: String(error?.message ?? error) }));
    child.on('close', (code) => finish({ ok: code === 0, exitCode: code ?? undefined }));
  });
}

/**
 * Transport v1: the exact command `70` proved, on the target's own shell. Kept deliberately
 * identical to `mesh-run`'s so the two cannot drift in what they claim to have run.
 */
async function runOverSsh({ node, prompt, timeoutMs, cwd }) {
  const facts = NODES[node];
  const target = facts.ssh;
  const task = [
    `You are running on the node "${node}".`,
    'Begin your final report with exactly this line: MESH-HOST: <the hostname of the machine you are running on>',
    'Get that name from your own shell (run `hostname`, or read $env:COMPUTERNAME on Windows) — never guess it.',
    '',
    prompt,
  ].join('\n');
  let argv;
  if (facts.shell === 'posix') {
    // The script travels on stdin; ssh is handed the shell, not a quoted program.
    argv = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', target, 'sh', '-s'];
  } else {
    const encoded = Buffer.from(`& '${facts.nodeExe}' '${facts.dshBin}' --profile headless '${task.replace(/'/g, "''")}'`, 'utf16le').toString('base64');
    argv = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', target, 'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded];
  }
  if (facts.shell === 'posix') {
    // `sh -s` needs the program; spawn cannot be given it here, so write it to a file and use it
    // as stdin. The v1 path in `mesh-run` passes the task as argv; this one is equivalent and does
    // not have to survive a shell, which is why it is used for POSIX targets.
    const script = `exec '${facts.nodeExe}' '${facts.dshBin}' --profile headless ${shellQuote(task)}\n`;
    const result = await sshRunWithStdin(argv, script, { timeoutMs });
    return result;
  }
  return sshRun(argv, { timeoutMs });
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function sshRunWithStdin(argv, script, { timeoutMs }) {
  const tag = `${process.pid}-${Date.now()}`;
  const outPath = path.join(tmpdir(), `meshdispatch-${tag}.out`);
  const errPath = path.join(tmpdir(), `meshdispatch-${tag}.err`);
  const outFd = openSync(outPath, 'w');
  const errFd = openSync(errPath, 'w');
  const started = Date.now();
  return new Promise((resolve) => {
    let timedOut = false;
    const child = spawn(SSH_EXE, argv, { stdio: ['pipe', outFd, errFd], windowsHide: true });
    const finish = (extra) => {
      clearTimeout(timer);
      try { closeSync(outFd); } catch { /* closed */ }
      try { closeSync(errFd); } catch { /* closed */ }
      const stdout = existsSync(outPath) ? readFileSync(outPath, 'utf8') : '';
      const stderr = existsSync(errPath) ? readFileSync(errPath, 'utf8') : '';
      rmSync(outPath, { force: true });
      rmSync(errPath, { force: true });
      resolve({ ms: Date.now() - started, stdout, stderr, timedOut, ...extra });
    };
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* gone */ }
    }, timeoutMs);
    timer.unref?.();
    child.on('error', (error) => finish({ ok: false, spawnError: String(error?.message ?? error) }));
    child.on('close', (code) => finish({ ok: code === 0, exitCode: code ?? undefined }));
    if (child.stdin) {
      child.stdin.on('error', () => {});
      child.stdin.end(script);
    }
  });
}

export { runOverSsh };

// ---------------------------------------------------------------------------
// the run
// ---------------------------------------------------------------------------

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const facts = NODES[options.node];
  if (facts === undefined) {
    process.stderr.write(`mesh-dispatch: unknown node "${options.node}" (known: ${Object.keys(NODES).join(', ')})\n`);
    process.exit(EXIT_UNKNOWN_NODE);
  }
  const logDir = options.logDir ?? defaultLogDir();
  mkdirSync(logDir, { recursive: true });
  const runId = new Date().toISOString().replace(/[:.]/g, '-');
  const logPath = path.join(logDir, `${runId}-dispatch.jsonl`);
  const record = (event) => {
    const line = JSON.stringify({ at: new Date().toISOString(), runId, node: options.node, ...event });
    writeFileSync(logPath, `${line}\n`, { flag: 'a' });
    if (!options.wantJson && !options.quiet) process.stderr.write(`mesh-dispatch: ${line}\n`);
  };

  const base = `https://${facts.label}.${TAILNET}`;
  const secretFile = options.secretFile ?? defaultDispatcherSecretFile();
  const secret = readSecret(secretFile);
  record({
    phase: 'start',
    transportPlan: 'v2 (https route) -> v1 (ssh) unless -RequireV2',
    url: `${base}/mesh/run`,
    ssh: facts.ssh,
    timeoutSec: options.timeoutSec,
    dispatcherSecret: secret.ok ? { path: secret.path, bytes: secret.secret.length } : { path: secret.path, unavailable: secret.reason },
    logPath,
  });

  if (options.dryRun) {
    process.stdout.write(JSON.stringify({ runId, node: options.node, url: base, ssh: facts.ssh, secret: secret.ok }, null, 2) + '\n');
    process.exit(EXIT_OK);
  }

  // ---- transport v2: probe, then post ------------------------------------
  let attemptedV2 = false;
  let fallbackReason;
  if (secret.ok) {
    const probe = await probeRoute({ base });
    if (probe.ok && probe.json?.service === 'mesh-http') {
      attemptedV2 = true;
      record({
        phase: 'probe',
        transport: 'http',
        ok: true,
        status: probe.status,
        service: probe.json.service,
        version: probe.json.version,
        nodeSaysItIs: { host: probe.json.host, node: probe.json.node, nodeSource: probe.json.nodeSource, fqdn: probe.json.fqdn },
        secretConfiguredOnNode: probe.json.auth?.secretConfigured === true,
        busy: probe.json.runner?.busy === true,
      });
      if (probe.json.auth?.secretConfigured !== true) {
        fallbackReason = `the node has no shared secret (${probe.json.auth?.secretReason ?? 'no reason given'})`;
      } else if (probe.json.runner?.busy === true) {
        fallbackReason = 'the node is running another turn (one run at a time by design)';
      } else {
        const body = JSON.stringify({
          prompt: options.prompt,
          meshHost: options.node,
          ...(options.cwd === undefined ? {} : { workdir: options.cwd }),
          timeoutSec: options.timeoutSec,
        });
        const started = Date.now();
        // The POST bound is the child's bound plus a generous margin: the node owns the child's
        // timeout, and the dispatcher must not cut a turn the node is still honestly running.
        const post = await postToNode({ url: `${base}/mesh/run`, body, secret: secret.secret, timeoutMs: (options.timeoutSec + 60) * 1000 });
        const { meshHosts, transportHosts } = extractHosts(post.json?.stdout ?? '');
        const disagreements = [...meshHosts, ...transportHosts].filter((host) => !hostMatchesNode(host, options.node));
        record({
          phase: 'run',
          transport: 'http',
          ok: post.ok,
          status: post.status,
          nodeSaysItIs: post.json === undefined ? null : { host: post.json.host, node: post.json.node },
          host: post.json?.host ?? null,
          exitCode: post.json?.exitCode ?? null,
          timedOut: post.json?.timedOut === true,
          childMs: post.json?.ms ?? null,
          dispatcherMs: Date.now() - started,
          meshHostLines: meshHosts.length,
          transportHostLines: transportHosts.length,
          childHosts: [...new Set(meshHosts)],
          disagreements,
          stdoutBytes: post.json?.stdoutBytes ?? null,
          stderrTail: post.ok ? (post.json?.stderr ?? '').slice(-600) : String(post.error ?? ''),
          stdout: post.json?.stdout ?? '',
        });
        if (post.ok && (post.status === 200 || post.status === 504)) {
          // The node has answered: the work was accepted and the child ran (or timed out) THERE.
          // There is no fallback from this point, on purpose — see the header.
          const answered = {
            runId, node: options.node, transport: 'http', url: `${base}/mesh/run`,
            httpStatus: post.status,
            ok: post.json?.ok === true,
            childExitCode: post.json?.exitCode ?? null,
            timedOut: post.json?.timedOut === true,
            host: post.json?.host ?? null,
            childHosts: [...new Set(meshHosts)],
            disagreements,
            meshHostLines: meshHosts.length,
            ms: post.json?.ms ?? null,
            stdout: post.json?.stdout ?? '',
            stderr: post.json?.stderr ?? '',
          };
          if (!options.wantJson) process.stdout.write(answered.stdout);
          process.stdout.write(`${JSON.stringify({ phase: 'result', ...answered }, null, options.wantJson ? 0 : 2)}\n`);
          process.exit(EXIT_OK);
        }
        fallbackReason = post.ok
          ? `the route refused the run with HTTP ${post.status} (${post.json?.reason ?? 'no reason'})`
          : `the route could not be reached (${post.error})`;
      }
    } else {
      fallbackReason = probe.ok
        ? `the node answered ${probe.status} on /mesh/health and it is not this service`
        : `no route on this node (${probe.error ?? 'no error field; see the status'})`;
      record({ phase: 'probe', transport: 'http', ok: false, url: `${base}/mesh/health`, status: probe.status ?? null, error: probe.error ?? null, reason: fallbackReason });
    }
  } else {
    fallbackReason = `this dispatcher has no shared secret (${secret.reason})`;
    record({ phase: 'probe', transport: 'http', ok: false, reason: fallbackReason });
  }

  if (options.requireV2) {
    record({ phase: 'result', outcome: 'v2-required-but-unavailable', transport: 'http', reason: fallbackReason, attemptedV2 });
    process.stderr.write(`mesh-dispatch: transport v2 was required and is unavailable: ${fallbackReason}\n`);
    process.exit(EXIT_V2_REQUIRED);
  }

  // ---- transport v1: explicit, logged, and it changes the recorded transport ----------
  record({
    phase: 'fallback',
    outcome: 'using ssh',
    reason: fallbackReason,
    note: 'explicit and logged: this run is NOT the HTTP transport, and the record says so',
    ssh: facts.ssh,
    targetVerified: 'see docs/mesh/70-remote-fanout-proof.md §2.6 for what each node was measured to accept',
  });
  const started = Date.now();
  const result = await runOverSsh({ node: options.node, prompt: options.prompt, timeoutMs: (options.timeoutSec + 60) * 1000, cwd: options.cwd });
  const { meshHosts, transportHosts } = extractHosts(result.stdout);
  const disagreements = [...meshHosts, ...transportHosts].filter((host) => !hostMatchesNode(host, options.node));
  record({
    phase: 'run',
    transport: 'ssh',
    ok: result.ok,
    exitCode: result.exitCode ?? null,
    timedOut: result.timedOut,
    spawnError: result.spawnError ?? null,
    ms: Date.now() - started,
    meshHostLines: meshHosts.length,
    transportHostLines: transportHosts.length,
    childHosts: [...new Set(meshHosts)],
    disagreements,
    stderrTail: result.stderr.slice(-600),
  });
  if (!options.wantJson) process.stdout.write(result.stdout);
  process.stdout.write(`${JSON.stringify({
    phase: 'result',
    runId,
    node: options.node,
    transport: 'ssh',
    ok: result.ok,
    childExitCode: result.exitCode ?? null,
    timedOut: result.timedOut,
    childHosts: [...new Set(meshHosts)],
    disagreements,
    meshHostLines: meshHosts.length,
    ms: Date.now() - started,
  })}\n`);
  process.exit(result.ok || result.stdout.trim() !== '' ? EXIT_OK : EXIT_TRANSPORT_FAILED);
}

// Only run when executed, not when imported by the tests. (`process.argv[1]` is a filesystem
// path; `import.meta.url` is a URL, so it goes through `fileURLToPath` — comparing them directly
// works on POSIX and never matches on Windows, which silently disables the CLI.)
if (process.argv[1] !== undefined && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  await main();
}
