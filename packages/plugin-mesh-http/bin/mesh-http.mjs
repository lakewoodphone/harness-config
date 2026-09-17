#!/usr/bin/env node
/**
 * mesh-http — the keeper for transport v2's node half.
 *
 * A component that can silently disappear needs a keeper, not a procedure: the same argument
 * `scripts/install-client-plugins.ps1` makes for the plugin junctions and `serve-phone.sh` makes
 * for the phone plugin. This is the keeper for this plugin's secret, its artifacts, and its
 * ability to answer at all.
 *
 * COMMANDS
 *   secret [--file PATH] [--rotate] [--length N]   show, create or rotate the shared secret
 *   check  [--file PATH] [--json]                  is this node ready to accept v2 work?
 *   clean  [--days N] [--dir PATH]                 remove run artifacts older than N days
 *   serve  [--port N] [--host H] [--file PATH]     mount the route on a bare HTTP server
 *   probe  [--node NAME]                           what each node answers, from this machine
 *
 * WHY `serve` EXISTS
 * It mounts EXACTLY what the engine mounts (`createMeshHttp`) on a plain `node:http` server. That
 * is how the route was developed and tested without restarting an engine, and it is how a node
 * whose engine cannot be restarted can still be measured — with the honest caveat that the engine
 * is not in that process, so a `serve` result proves the route, not the deployment.
 *
 * EVERY COMMAND IS READ-ONLY EXCEPT `secret` AND `clean`, and neither of those touches data:
 * `secret` writes one file, `clean` removes this plugin's own run artifacts.
 */

import { createServer } from 'node:http';
import { chmodSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createMeshHttp, createLogger, defaultSecretFile, DEFAULTS, VERSION } from '../lib/index.js';
import { loadSecret } from '../lib/secret.js';
import { NODES } from './mesh-dispatch.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..', '..');

function parse(argv) {
  const out = { command: argv[0] ?? 'check', flags: {}, rest: [] };
  for (let i = 1; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const [key, inline] = arg.slice(2).split('=');
      if (inline !== undefined) out.flags[key] = inline;
      else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith('--')) out.flags[key] = argv[++i];
      else out.flags[key] = true;
    } else out.rest.push(arg);
  }
  return out;
}

/** Windows has no file modes that mean what 0640 means, so the ACL is set explicitly instead. */
function restrictPermissions(file, platform = process.platform) {
  if (platform !== 'win32') {
    chmodSync(file, 0o640);
    return { mode: '0640', how: 'chmod' };
  }
  const user = process.env.USERNAME ?? '';
  const result = spawnSync('icacls', [file, '/inheritance:r', '/grant:r', `${user}:r`, 'SYSTEM:F', 'Administrators:F'], { encoding: 'utf8' });
  return result.status === 0
    ? { mode: 'ACL', how: `icacls: ${user}:r, SYSTEM:F, Administrators:F (inheritance removed)` }
    : { mode: 'UNKNOWN', how: `icacls failed with status ${result.status}: ${(result.stderr ?? '').trim().slice(0, 200)}` };
}

function secretCommand({ flags }) {
  const file = String(flags.file ?? defaultSecretFile());
  const dir = path.dirname(file);
  const exists = existsSync(file);
  if (exists && flags.rotate !== true) {
    const read = loadSecret(file);
    const mode = currentPermissions(file);
    process.stdout.write(JSON.stringify({
      ok: read.ok,
      command: 'secret',
      file,
      exists: true,
      usable: read.ok,
      reason: read.ok ? null : read.reason,
      bytes: read.ok ? read.bytes : null,
      permissions: mode,
      note: 'the value is never printed: it is a shared secret, and a secret in a transcript is a secret spent',
      howToRotate: `node ${path.relative(process.cwd(), HERE)}/mesh-http.mjs secret --rotate`,
    }, null, 2) + '\n');
    process.exit(read.ok ? 0 : 1);
  }
  const length = Number.isFinite(Number(flags.length)) && Number(flags.length) >= 24 ? Number(flags.length) : 48;
  const value = randomBytes(length).toString('base64url');
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  if (exists) writeFileSync(`${file}.bak-${Date.now()}`, readFileSync(file), { mode: 0o600 });
  writeFileSync(file, `# The mesh transport v2 shared secret on this node (docs/mesh/83-http-transport.md).\n`
    + `# Read by the node's own route (packages/plugin-mesh-http) and by a dispatcher that runs HERE.\n`
    + `# It is NOT installed on any other node: a node authenticates with its OWN secret.\n`
    + `MESH_HTTP_SECRET=${value}\n`, { mode: 0o600 });
  const perms = restrictPermissions(file);
  const read = loadSecret(file);
  process.stdout.write(JSON.stringify({
    ok: read.ok,
    command: exists ? 'rotate' : 'create',
    file,
    bytes: read.ok ? read.bytes : null,
    permissions: perms,
    backup: exists ? `${file}.bak-*` : null,
    note: 'a rotated secret takes effect on the NEXT request — no engine restart',
    thenOnTheDispatcher: 'the dispatcher reads its OWN node\'s file, so nothing else has to change',
  }, null, 2) + '\n');
  process.exit(read.ok ? 0 : 1);
}

function currentPermissions(file) {
  try {
    const mode = statSync(file).mode & 0o777;
    if (process.platform !== 'win32') return { mode: mode.toString(8).padStart(3, '0') };
    const result = spawnSync('icacls', [file], { encoding: 'utf8' });
    return { mode: 'ACL', acl: (result.stdout ?? '').split('\n').slice(0, 4).map((line) => line.trim()).filter(Boolean) };
  } catch (error) {
    return { error: String(error?.message ?? error) };
  }
}

function checkCommand({ flags }) {
  const file = String(flags.file ?? defaultSecretFile());
  const read = loadSecret(file);
  const mount = createMeshHttp({ config: { secretFile: file }, log: () => {} });
  const readout = mount.readout();
  const report = {
    ok: true,
    command: 'check',
    version: VERSION,
    plugin: HERE,
    repo: REPO,
    ...readout,
    secret: { usable: read.ok, reason: read.ok ? null : read.reason, permissions: existsSync(file) ? currentPermissions(file) : 'absent' },
    engineMount: {
      where: `${path.join(process.env.DSH_HOME ?? path.join(os.homedir(), '.dsh'), 'profiles', 'web', 'node_modules', 'dsh-plugin-mesh-http')}`,
      bundleListedIn: path.join(process.env.DSH_HOME ?? path.join(os.homedir(), '.dsh'), 'profiles', 'web', 'package.json'),
      howToInstall: `node ${path.relative(process.cwd(), path.join(HERE, 'install-mesh-http.mjs'))}`,
      restartNeeded: 'yes for a resident engine: a mounted bundle cannot hot-load (P210)',
    },
  };
  report.ok = read.ok && readout.dshBin !== null;
  if (flags.json === true) process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  else {
    process.stdout.write([
      `mesh-http ${VERSION} on ${readout.host} (node ${readout.node}, ${readout.nodeSource})`,
      `  route            ${readout.route}  +  ${DEFAULTS.healthPath}`,
      `  secret           ${read.ok ? `${read.bytes} bytes at ${read.path} (${JSON.stringify(report.secret.permissions)})` : `NOT USABLE: ${read.reason}`}`,
      `  dsh entry point  ${readout.dshBin ?? 'NOT FOUND — a run would answer 502'}`,
      `  profile          ${readout.profile} (subcommand headless)`,
      `  child cwd        ${readout.cwd}`,
      `  artifacts        ${readout.artifactDir}`,
      `  concurrency      ${readout.runner.limit} at once, ${Math.round(readout.runner.queueWaitBudgetMs / 1000)}s queue budget — ${readout.concurrency.note}`,
      `                   ${readout.concurrency.terms === null ? '(no arithmetic)' : `cpu=${readout.concurrency.terms.cpu} mem=${readout.concurrency.terms.mem} declared=${readout.concurrency.terms.declared} hard=${readout.concurrency.terms.hard}`}`,
      `  identity         ${readout.identityDegraded ? `DEGRADED: ${readout.identityReason}` : 'corroborated by the tailnet'}`,
      `  runs             started=${readout.runner.started} completed=${readout.runner.completed} failed=${readout.runner.failed} refused-busy=${readout.runner.refusedBusy} timed-out=${readout.runner.timedOut} queued=${readout.runner.queued} queue-peak=${readout.runner.queuePeak}`,
      `  verdict          ${report.ok ? 'ready to accept v2 work' : 'NOT ready'}`,
      '',
    ].join('\n'));
  }
  process.exit(report.ok ? 0 : 1);
}

function cleanCommand({ flags }) {
  const days = Number.isFinite(Number(flags.days)) ? Number(flags.days) : 14;
  const dir = String(flags.dir ?? path.join(process.env.DSH_HOME ?? path.join(os.homedir(), '.dsh'), 'mesh', 'http'));
  const mount = createMeshHttp({ config: { artifactDir: dir }, log: () => {} });
  const result = mount.runner.cleanupArtifacts({ days });
  process.stdout.write(`${JSON.stringify({ command: 'clean', days, ...result }, null, 2)}\n`);
}

async function serveCommand({ flags }) {
  const file = String(flags.file ?? defaultSecretFile());
  const logger = createLogger({ logFile: flags.log === true ? undefined : flags.log });
  const mount = createMeshHttp({ config: { secretFile: file, logFile: flags.log }, log: logger.write });
  const server = createServer((req, res) => mount.handler(req, res));
  const port = Number.isFinite(Number(flags.port)) ? Number(flags.port) : 3092;
  const host = String(flags.host ?? '127.0.0.1');
  await new Promise((resolve) => server.listen(port, host, resolve));
  process.stdout.write(`${JSON.stringify({
    command: 'serve',
    listening: `http://${host}:${server.address().port}`,
    route: mount.config.path,
    health: mount.config.healthPath,
    secretUsable: mount.readout().secretConfigured,
    note: 'this is the ROUTE, not the deployment: no engine is in this process',
  })}\n`);
}

async function probeCommand({ flags }) {
  const only = flags.node === true ? [] : String(flags.node ?? '').split(',').map((s) => s.trim()).filter(Boolean);
  const tailnet = process.env.MESH_TAILNET ?? 'tail93e6e6.ts.net';
  const names = only.length > 0 ? only : Object.keys(NODES);
  const out = [];
  for (const name of names) {
    const label = NODES[name]?.label ?? name;
    const base = `https://${label}.${tailnet}`;
    const started = Date.now();
    let record;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(new Error('timeout')), 8000);
      const response = await fetch(`${base}/mesh/health`, { signal: controller.signal });
      clearTimeout(timer);
      const text = await response.text();
      let json;
      try { json = JSON.parse(text); } catch { json = undefined; }
      record = {
        node: name, url: `${base}/mesh/health`, status: response.status, ms: Date.now() - started,
        service: json?.service ?? null,
        version: json?.version ?? null,
        secretConfigured: json?.auth?.secretConfigured ?? null,
        busy: json?.runner?.busy ?? null,
        nodeSaysItIs: json?.node ?? null,
        host: json?.host ?? null,
        fqdn: json?.fqdn ?? null,
        identityDegraded: json?.identityDegraded ?? null,
        identityReason: json?.identityReason ?? null,
        // What this node says it may run at once, and the arithmetic behind it — so a probe is a
        // capacity reading and not merely a reachability check.
        maxConcurrent: json?.limits?.maxConcurrent ?? json?.runner?.limit ?? null,
        queueDepth: json?.runner?.queueDepth ?? null,
        concurrencyNote: json?.concurrency?.note ?? null,
        verdict: response.ok && json?.service === 'mesh-http'
          ? (json.auth?.secretConfigured === true ? 'ACCEPTS v2' : 'route present, NO SECRET')
          : `not v2 (HTTP ${response.status})`,
      };
    } catch (error) {
      record = { node: name, url: `${base}/mesh/health`, ms: Date.now() - started, error: String(error?.cause?.code ?? error?.message ?? error), verdict: 'unreachable or no route' };
    }
    out.push(record);
    process.stdout.write(`${JSON.stringify(record)}\n`);
  }
  process.exit(out.every((r) => r.verdict === 'ACCEPTS v2') ? 0 : 1);
}

const parsed = parse(process.argv.slice(2));
switch (parsed.command) {
  case 'secret': secretCommand(parsed); break;
  case 'check': checkCommand(parsed); break;
  case 'clean': cleanCommand(parsed); break;
  case 'serve': await serveCommand(parsed); break;
  case 'probe': await probeCommand(parsed); break;
  default:
    process.stdout.write('mesh-http <secret|check|clean|serve|probe> [options]   (see the file header)\n');
    process.exit(2);
}
