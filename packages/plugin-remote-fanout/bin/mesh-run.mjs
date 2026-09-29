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
import { homedir, hostname, tmpdir } from 'node:os';
import path from 'node:path';

import { createBrokerClient } from '../lib/broker-client.js';
import { hostMatchesNode, invocationForNode, isHostToken, NODES } from '../lib/nodes.js';

const BROKER_SSH = process.env.MESH_BROKER_SSH ?? 'secratary-ts';
const BROKER_URL = process.env.MESH_BROKER_URL ?? 'http://localhost:3091';

/**
 * ONE implementation of "ask the broker", shared with the provider
 * (`lib/broker-client.js`). It reaches the broker the same way every other
 * caller does — one bounded `ssh` to the authority running a `curl` against a
 * loopback-only service — and it refreshes nothing: `brokerPost` below is the
 * same `{ok, json, parseError}` shape this file has always branched on.
 */
const broker = createBrokerClient({
  sshExe: process.env.MESH_SSH_EXE,
  sshTarget: BROKER_SSH,
  url: BROKER_URL,
  timeoutMs: 30_000,
});

/**
 * The node table lives in `lib/nodes.js` — moved there 2026-09-17, when the
 * PROVIDER needed the same facts for the same broker-named nodes. Two copies
 * would have drifted, and the drift would have been invisible until a child
 * landed somewhere it could not run. It is the same content this file carried:
 * `verified` records whether the two paths were ever measured on that node,
 * because an empty result is not health and an unverified path is not a
 * placement.
 */

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

/** POST one JSON body to a broker route, over ssh. Throws nothing: failures come back as `ok:false`. */
async function brokerPost(route, body, timeoutMs) {
  try {
    const json = route === '/place'
      ? await broker.place(body.task, { timeout: timeoutMs })
      : await broker.done(body.lease, body.ok !== false, { timeout: timeoutMs });
    return { ok: true, json };
  } catch (error) {
    return { ok: false, parseError: `${error?.code ?? 'broker-error'}: ${String(error?.message ?? error)}` };
  }
}

/**
 * `hostMatchesNode` and `isHostToken` moved to `lib/nodes.js` — the provider's
 * location check needs the same two functions against the node the BROKER named,
 * and a second copy of a check is a second answer to the same question.
 */

/**
 * Can this node's sshd session traverse the reparse points a CHILD will resolve
 * through? One read through an EXISTING link under `<DSH_HOME>/profiles`, and —
 * only when the home has no links yet — one fresh junction in the target's TEMP.
 *
 * It must read a pre-existing link, not a freshly created one: a junction
 * created inside the sshd session is always trusted by that session, so probing
 * with one would certify a node whose real links are untrusted (measured
 * 2026-09-17, `70-remote-fanout-proof.md` §4.4).
 *
 * POSIX targets have no reparse points, so the probe is skipped and says so.
 */
async function probeTraversal(node, alias, nodeFacts, timeoutMs = 30_000) {
  if (nodeFacts.shell !== 'powershell') return { ok: true, skipped: 'posix target: reparse points do not exist' };
  const script = [
    '$dsh = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE ".dsh" }',
    '$links = @(Get-ChildItem -Path (Join-Path $dsh "profiles") -Recurse -Depth 3 -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.LinkType } | Select-Object -First 5)',
    'if ($links.Count -gt 0) {',
    '  $ok = 0; $bad = @()',
    '  foreach ($link in $links) {',
    '    try { $null = Get-ChildItem -LiteralPath $link.FullName -Force -ErrorAction Stop | Select-Object -First 1; $ok++ }',
    '    catch { $bad += ($link.FullName + " :: " + $_.Exception.Message) }',
    '  }',
    '  if ($bad.Count -eq 0) { "MESH-TRAVERSAL=OK existing " + $ok + " of " + $links.Count + " link(s) traversable" }',
    '  else { "MESH-TRAVERSAL=BLOCKED " + $bad.Count + " of " + $links.Count + " link(s) :: " + $bad[0] }',
    '} else {',
    '  $d = Join-Path $env:TEMP ("meshtrav-" + [guid]::NewGuid().ToString("N"))',
    '  $t = Join-Path $d "t"; $l = Join-Path $d "l"',
    '  New-Item -ItemType Directory -Force -Path $t | Out-Null',
    '  Set-Content -Path (Join-Path $t "probe.txt") -Value "OK" -Encoding ascii',
    '  New-Item -ItemType Junction -Path $l -Target $t | Out-Null',
    '  try { $v = (Get-Content -LiteralPath (Join-Path $l "probe.txt") -Raw).Trim(); "MESH-TRAVERSAL=OK fresh-home " + $v } catch { "MESH-TRAVERSAL=BLOCKED fresh-home :: " + $_.Exception.Message }',
    '  & cmd /c rmdir /s /q "$d"',
    '}',
  ].join('\n');
  const result = await sshRun(['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', alias, 'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', pwshEncode(script)], { timeoutMs });
  const line = /MESH-TRAVERSAL=(\S+)(.*)/.exec(result.stdout);
  if (line === null) {
    return { ok: false, reason: `the traversal probe printed no verdict (exit ${result.exitCode ?? 'none'}; stdout: ${result.stdout.trim().slice(0, 200)}; stderr: ${result.stderr.trim().slice(0, 200)})` };
  }
  const detail = (line[2] ?? '').trim().slice(0, 200);
  if (line[1] === 'OK') return { ok: true, reason: `reparse points traverse over ssh — ${detail}` };
  return { ok: false, reason: `this node's sshd session cannot traverse a reparse point (${detail}) — profile bundle resolution would fail; fix it by recreating the links INSIDE an ssh session (see 70-remote-fanout-proof.md §4.4)` };
}

/** base64(UTF-16LE) for `powershell -EncodedCommand`. */
function pwshEncode(script) {
  return Buffer.from(script, 'utf16le').toString('base64');
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
  record({
    phase: 'configure',
    ok: false,
    error: `the broker named node "${node}", which is not in this dispatcher's node table — refusing to dispatch into a lookup miss`,
    knownNodes: Object.keys(NODES),
  });
  console.error(`mesh-run: the broker named node "${node}", which is not in this dispatcher's node table (${Object.keys(NODES).join(', ')})`);
  process.exit(EXIT_FAILED);
}
const nodeFacts = NODES[node];

// ---- 2b. CAPABILITY, PROBED BEFORE ANY WORK IS STARTED ------------------------
// A Windows node whose sshd session cannot traverse reparse points cannot run a
// DSH child, because profile bundle resolution goes through the junctions in
// <DSH_HOME>/profiles/node_modules. That property is NOT visible in any
// configuration — measured 2026-09-17 on two nodes with identical junctions,
// targets, ACLs, token privileges, integrity level and fsutil symlink policy,
// where one traverses and the other returns UNKNOWN. So it is probed, recorded,
// and a blocked node fails the run BEFORE a parent is started.
const traversal = await probeTraversal(node, alias, nodeFacts);
record({ phase: 'traversal', node, shell: nodeFacts.shell, ...traversal });
if (!traversal.ok) {
  console.error(`mesh-run: node "${node}" cannot accept v1 ssh work: ${traversal.reason}`);
  process.exit(EXIT_FAILED);
}

// ---- 2/3. CONFIGURE and RUN ---------------------------------------------------
// The target's own facts travel as environment for the profile that is about to
// boot, because the profile can only see the node it runs ON (see the NODES
// comment). The parent's own machine is not a source of truth about the target.
const env = {
  ...process.env,
  MESH_TARGET_NODE: alias,
  MESH_TARGET_HOSTS: nodeFacts.hosts.join(','),
  MESH_REMOTE_SHELL: nodeFacts.shell,
  // The invocation travels as THREE facts, in the order the resolver prefers
  // them: an executor on the target's PATH (the node's own `dsh` wrapper, which
  // sources the worker credential), then the interpreter pair as its fallback.
  // Passing the pair alone is what produced a child that died with
  // `node …: not found` on `zabz-tech-linux` (docs/mesh/102-linux-dispatch.md).
  MESH_NODE_COMMAND: nodeFacts.command ?? '',
  MESH_WORKER_ENV_FILES: (nodeFacts.credentialEnvFiles ?? []).join(','),
  MESH_NODE_EXE: nodeFacts.driver ?? '',
  MESH_DSH_BIN: nodeFacts.bin ?? '',
  MESH_REMOTE_CWD: options.workdir ?? nodeFacts.cwd,
};
const started = Date.now();
record({
  phase: 'run',
  node,
  alias,
  children: options.children,
  shell: nodeFacts.shell,
  // WHICH INVOCATION THE CHILD WILL USE, in the run log, before it runs.
  invocation: invocationForNode(node),
  targetVerified: nodeFacts.verified,
  dshBin,
  prompt: options.prompt.slice(0, 200),
  logPath,
});
// SAY WHAT -Node ACTUALLY DOES, BEFORE THE RUN, BECAUSE THE OPPOSITE WAS BELIEVED THREE TIMES.
//
// Measured 2026-09-18 (journal P327): three runs of this tool -- `-Node lakewooechsmini`,
// `-Node secratary`, and a headless child with MESH_TARGET_NODE set in the real environment --
// each produced a child that ran on the DISPATCHER's machine. The verify phase caught all
// three (`location disagreement`, exit 1), which is the only reason they were not recorded as
// successes. The run log did not help: it prints `node`, `alias`, `invocation` and
// `targetVerified`, four lines that all read as "this is where the work goes".
//
// So the tool now states the truth out loud. The child below runs HERE, spawned by
// `sshRunLocal`; -Node travels only as environment for the child's own provider. If a caller
// wants the child itself to run elsewhere, this command is not the way to ask.
console.error(
  `mesh-run: NOTE — this child runs on ${hostname()}, the machine you are invoking this from. `
  + `-Node ${node} sets the dispatch target the child's own subagents will be aimed at (via MESH_TARGET_NODE="${alias}"); `
  + 'it does NOT place this child. The verify phase below fails the run if the child\'s own report names a different host.',
);
const runResult = await sshRunLocal(dshBin, options.prompt, env, options.timeoutMs);
writeFileSync(outPath, runResult.stdout, 'utf8');
record({ phase: 'run-end', node, exitCode: runResult.exitCode, timedOut: runResult.timedOut, ms: Date.now() - started, stdoutBytes: runResult.stdout.length, stderrBytes: runResult.stderr.length, outPath });

// ---- 4. VERIFY ----------------------------------------------------------------
// Unanchored on purpose: a parent agent summarising its own children writes
// `CHILD=1 MESH_HOST=MESH-HOST: zabz-tech TRANSPORT=transport host = ZABZ-TECH`,
// so the tokens appear mid-line. Measured 2026-09-16 — an anchored `^MESH-HOST:`
// found zero of three and failed a run that had actually succeeded.
//
// AND IT MUST ACCEPT THE SHORT FORM THE PROVIDER'S OWN PREAMBLE TEACHES. Measured
// 2026-09-17T03:37Z, a six-child fleet: all six children ran on zabz-tech through
// `subagent_remote` and the parent reported them as `CHILD=n MESH_HOST=zabz-tech TOKEN=...`, but
// this matcher wanted the literal token `MESH-HOST:` in the PARENT's summary and scored
// `meshHostLines: 0`, so a run in which six remote children had demonstrably completed exited 1.
// The provider's preamble asks the child to "begin its report with a line of the form
// `MESH-HOST: <hostname>`", and the child's FINAL MESSAGE is what the provider returns; the
// parent holds `CHILD=n MESH_HOST=<host>`. Both are the child naming its own host, which is what
// §2.4 requires. So the parent-summary form is accepted, and the check that keeps it honest is
// `hostMatchesNode` below: a summarised host that is not the node the broker named is still a
// disagreement, and a failure is still reported as a failure.
const meshHosts = [...runResult.stdout.matchAll(/MESH-HOST:\s*(\S+)/gi)].map((match) => match[1]).filter(isHostToken);
const summarised = [...runResult.stdout.matchAll(/MESH_HOST=(\S+)/g)].map((match) => match[1]).filter(isHostToken);
const transportHosts = [...runResult.stdout.matchAll(/transport host\s*=\s*(\S+)/gi)].map((match) => match[1]).filter(isHostToken);
const reportedHosts = (summarised.length > 0 ? summarised : meshHosts).filter((host) => host !== '(not');
const disagreements = [];
for (const host of [...reportedHosts, ...transportHosts]) {
  if (!hostMatchesNode(host, node)) disagreements.push(host);
}
const childHosts = [...new Set(reportedHosts)];
record({
  phase: 'verify',
  node,
  meshHostLines: reportedHosts.length,
  meshHostLinesLiteral: meshHosts.length,
  meshHostLinesSummarised: summarised.length,
  transportHostLines: transportHosts.length,
  childHosts,
  disagreements,
  ok: disagreements.length === 0 && reportedHosts.length >= options.children,
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
// EVERY FAILURE RECORD NAMES WHERE THE CHILD'S TEXT SURVIVED. The bytes are written to
// `outPath` (line 373) and printed before any of these exits, so nothing is discarded —
// but a record that says only `failed` forces a reader to guess, and a reader of the
// 2026-09-18 logs concluded the answer had been thrown away
// (docs/mesh/122-crash-and-loss-evidence.md). Name the file. `outPath` is in the
// `run-end` record too; repeating it here means the failure is self-contained.
if ((runResult.exitCode ?? 1) !== 0) {
  record({ phase: 'result', outcome: 'failed', reason: `parent exit ${runResult.exitCode}`, outPath, childTextBytes: runResult.stdout.length });
  process.exit(EXIT_FAILED);
}
if (disagreements.length > 0) {
  record({ phase: 'result', outcome: 'failed', reason: `location disagreement: ${disagreements.join(', ')} not on ${node}`, outPath, childTextBytes: runResult.stdout.length });
  process.exit(EXIT_FAILED);
}
// The exit gate tests the SAME quantity `verify` recorded. Measured 2026-09-17T03:47:54Z: the
// `verify` record said `meshHostLines: 6, childHosts: ["zabz-tech"], disagreements: [], ok: true`
// and this line, still reading the pre-fix `meshHosts`, then failed the run with "only 0
// MESH-HOST lines for 6 children" - a green verification and a red exit in the same second, which
// is worse than either alone because the log contradicts itself.
if (reportedHosts.length < options.children) {
  record({ phase: 'result', outcome: 'failed', reason: `only ${reportedHosts.length} MESH-HOST lines for ${options.children} children (${meshHosts.length} literal, ${summarised.length} summarised)`, outPath, childTextBytes: runResult.stdout.length });
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
