/**
 * plugin-mesh-http — the node half of mesh transport v2.
 *
 * WHAT IT IS, IN ONE SENTENCE
 * One HTTP route on the node itself (`POST /mesh/run`, plus an unauthenticated `GET /mesh/health`)
 * that runs ONE agent turn locally and answers with its exit code and output, HMAC-authenticated
 * with a shared secret that lives in a file outside every repository.
 *
 * WHY IT EXISTS
 * Transport v1 is `ssh <node> dsh --profile headless`. It works and it is fragile in three
 * measured ways that have each cost a night:
 *   * a Windows node's sshd session could not traverse its own profile junctions until an
 *     in-session relink (`70-remote-fanout-proof.md` §4.4);
 *   * Win32-OpenSSH's client does not exit when its stdout is a pipe (`70` §4.1) and can hold a
 *     session open after the work is done (`70` §4.2);
 *   * the Mac Mini's tailnet path is relayed and drops (`81` §2).
 * An HTTP route on the target, reached through the gate that already exists and already
 * authenticates by device, needs none of ssh, of the remote shell's identity, or of a session
 * that is trusted by sshd. The child becomes a child of the ENGINE, whose own logon session is
 * the one that already resolves the profile's bundles.
 *
 * WHY THIS FILE IS NOT THE WHOLE PLUGIN
 * The interesting parts are testable without an engine, so they are separate modules and the
 * unit suite drives them directly: `lib/auth.js` (the MAC and its replay ledger), `lib/body.js`
 * (bounded intake), `lib/runner.js` (the one-run slot and the timeout), `lib/handler.js` (the
 * contract), `lib/node-identity.js` (the name the caller is NOT allowed to supply).
 *
 * WHY THERE IS NO EVENT LISTENER ON THE SERVER SOCKET
 * A request that fails authentication must still be answered, and the only place that happens
 * reliably is inside the handler. So nothing here installs an `error` handler on the underlying
 * socket: an unhandled `error` on a socket would be an uncaught exception in the engine, and a
 * route is not allowed to be able to do that.
 */

import { MeshAuth } from './auth.js';
import {
  COMMIT_PER_TURN_MIB,
  CPU_PER_TURN,
  HARD_CEILING,
  LOGICAL_CPU_BUDGET_FRACTION,
  createDeclaredCapacityReader,
  declaredMaxChildren,
  deriveConcurrencyLimit,
  readLocalInputs,
} from './concurrency.js';
import { createMeshHealthHandler, createMeshRunHandler } from './handler.js';
import { createNodeIdentity } from './node-identity.js';
import { OneShotRunner, defaultArtifactDir, usableWorkdir } from './runner.js';
import { loadSecret } from './secret.js';
import { appendFileSync, existsSync, readdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** Cordis function-plugin name. */
export const name = 'mesh-http';

/** No hard service declaration: the route is contributed only when `webServer` exists. */
export const inject = [];

export const VERSION = '0.2.0';

/** The route this plugin owns, and the health route beside it. */
export const ROUTE = '/mesh/run';
export const HEALTH_ROUTE = '/mesh/health';

/**
 * Every key is optional with a working default, so a node that mounts this bundle with no
 * config at all still boots — and answers 503 to every run until a secret exists. There is no
 * `schemastery` import here on purpose: the package then has ZERO runtime dependencies, which
 * is what lets it be mounted from a profile that resolves bundles through junctions
 * (`dsh-plugin-remote-fanout`'s README makes the same argument).
 */
export const DEFAULTS = {
  path: ROUTE,
  healthPath: HEALTH_ROUTE,
  secretFile: undefined, // resolved per platform below
  skewSeconds: 120,
  maxBodyBytes: 256 * 1024,
  maxPromptChars: 32000,
  defaultTimeoutSec: 900,
  maxTimeoutSec: 3600,
  maxOutputBytes: 2 * 1024 * 1024,
  busyRetryAfterSec: 30,
  profile: 'headless',
  /** The subcommand that runs one turn and exits. `headless` is the one transport v1 uses. */
  subcommand: 'headless',
  nodeExe: process.execPath,
  dshBin: undefined, // located next to this plugin's own install or from MESH_LOCAL_DSH_BIN
  cwd: undefined, // resolved per platform below
  allowRequestWorkdir: false,
  meshHostLine: 'MESH-HOST:',
  nodeName: undefined, // MESH_NODE_NAME wins over the tailnet label when set
  artifactDir: undefined, // <DSH_HOME>/mesh/http by default
  logFile: undefined,
  probeTimeoutMs: 4000,
  requestTimeoutMs: 4000,
  // ---- how many turns at once, and what happens to the rest -------------------------------
  /** `undefined` = DERIVE it from this node's own capacity (`lib/concurrency.js`). An explicit
   *  number is honoured and clamped to `hardCeiling`; `MESH_HTTP_MAX_CONCURRENT` sets it too. */
  maxConcurrent: undefined,
  /** How long a queued request waits before `node-queue-wait-exceeded`. 780 s by default, which
   *  is deliberately SHORTER than a dispatcher's default 900 s POST budget, so the node answers
   *  before the caller gives up. */
  maxQueueWaitSec: 780,
  /** v0.1.0's `429 node-busy` instead of a queue. Off: a refusal has to be re-aimed by a caller,
   *  and the caller that re-aims is how work ends up on the wrong node (`70` §4.5). */
  refuseWhenFull: false,
  /** The node's own published capacity contract, read over loopback. `''` disables the read. */
  capacityUrl: 'http://127.0.0.1:3086/mesh/capacity',
  capacityTtlMs: 30000,
  capacityTimeoutMs: 1500,
  cpuBudgetFraction: LOGICAL_CPU_BUDGET_FRACTION,
  cpuPerTurn: CPU_PER_TURN,
  commitPerTurnMiB: COMMIT_PER_TURN_MIB,
  reserveMiB: undefined, // max(2 GiB, 12 % of physical) when undefined
  hardCeiling: HARD_CEILING,
  /** A DEGRADED tailnet reading is retried at this interval; a good one is cached for the process
   *  (`lib/node-identity.js` — a boot-time empty `Self.DNSName` must not become the node's name). */
  degradedRetryMs: 15000,
};

/** The platform's own secret location. Windows has no /etc, so ProgramData is its equivalent. */
export function defaultSecretFile(platform = process.platform) {
  return platform === 'win32' ? 'C:/ProgramData/dsh-mesh.env' : '/etc/dsh-mesh.env';
}

/**
 * Every knob a node operator may move without editing this file, and nothing else. Explicit
 * `config` wins over the environment, so a composition that pins a value is not overridable.
 */
export function readEnvConfig(env = process.env) {
  const out = {};
  const num = (name, target, transform = Number) => {
    if (env[name] === undefined || env[name] === '') return;
    const value = transform(env[name]);
    if (Number.isFinite(value)) out[target] = value;
  };
  num('MESH_HTTP_MAX_CONCURRENT', 'maxConcurrent', (v) => Number.parseInt(v, 10));
  num('MESH_HTTP_QUEUE_WAIT_SEC', 'maxQueueWaitSec', (v) => Number.parseInt(v, 10));
  num('MESH_HTTP_CAPACITY_TTL_MS', 'capacityTtlMs', (v) => Number.parseInt(v, 10));
  num('MESH_HTTP_CAPACITY_TIMEOUT_MS', 'capacityTimeoutMs', (v) => Number.parseInt(v, 10));
  num('MESH_HTTP_CPU_BUDGET_FRACTION', 'cpuBudgetFraction');
  num('MESH_HTTP_CPU_PER_TURN', 'cpuPerTurn');
  num('MESH_HTTP_COMMIT_PER_TURN_MIB', 'commitPerTurnMiB');
  num('MESH_HTTP_RESERVE_MIB', 'reserveMiB');
  num('MESH_HTTP_HARD_CEILING', 'hardCeiling');
  num('MESH_HTTP_DEGRADED_RETRY_MS', 'degradedRetryMs');
  if (env.MESH_HTTP_CAPACITY_URL !== undefined) out.capacityUrl = env.MESH_HTTP_CAPACITY_URL;
  if (env.MESH_HTTP_REFUSE_WHEN_FULL !== undefined) {
    out.refuseWhenFull = /^(1|true|yes|on)$/i.test(env.MESH_HTTP_REFUSE_WHEN_FULL);
  }
  return out;
}

/** The default working directory of a dispatched child: the machine's code root, if it exists. */
export function defaultCwd({ platform = process.platform, env = process.env, homedir = os.homedir() } = {}) {
  if (typeof env.MESH_CWD === 'string' && usableWorkdir(env.MESH_CWD)) return env.MESH_CWD;
  const candidates = platform === 'win32'
    ? [path.join(homedir, 'code'), homedir]
    : [path.join(homedir, 'code'), '/home/zabz/code', homedir];
  for (const candidate of candidates) if (usableWorkdir(candidate)) return candidate;
  return homedir;
}

/**
 * Locate the `dsh` entry point this node would run a child with. The order matters: an explicit
 * configuration or environment value first, then the installation the running engine was
 * launched from (the only one that is guaranteed to exist and to be the same version), then the
 * npx cache, and finally nothing at all — in which case the route answers 503 with a reason
 * instead of failing a run halfway.
 */
export function locateDshBin(explicit, { env = process.env, fs = { existsSync, readdirSync } } = {}) {
  const candidates = [];
  try {
    if (typeof explicit === 'string' && explicit.trim() !== '') candidates.push(explicit);
    if (typeof env.MESH_LOCAL_DSH_BIN === 'string' && env.MESH_LOCAL_DSH_BIN.trim() !== '') candidates.push(env.MESH_LOCAL_DSH_BIN);
    // The engine that is serving this request resolves bundles from its own installation. If the
    // process argv names it, that path is the same one `--profile <p>` will boot from a child.
    for (const arg of process.argv.slice(0, 4)) {
      if (typeof arg === 'string' && arg.endsWith(path.join('lib', 'bin.js'))) candidates.push(arg);
    }
    const cacheRoot = env.LOCALAPPDATA !== undefined
      ? path.join(env.LOCALAPPDATA, 'npm-cache', '_npx')
      : path.join(env.HOME ?? os.homedir(), '.npm', '_npx');
    for (const entry of fs.readdirSync(cacheRoot)) {
      candidates.push(path.join(cacheRoot, entry, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js'));
    }
  } catch { /* no npx cache on this node, and no argv hint: that is not a fault */ }
  for (const candidate of candidates) {
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch { /* unreadable path is not a candidate */ }
  }
  return undefined;
}

/** A logger that writes one JSON line per event to stdout and, optionally, to a file. */
export function createLogger({ logFile }) {
  const lines = [];
  const write = (line) => {
    const text = `${line}\n`;
    lines.push(text);
    if (lines.length > 4000) lines.shift();
    process.stdout.write(text);
    if (logFile === undefined) return;
    try {
      // Append per line: a crash of the engine must not lose the lines already written, and a
      // log file this route keeps is the node's own record that a dispatch arrived.
      appendFileSync(logFile, text);
    } catch { /* a log that cannot be written is not a reason to refuse work */ }
  };
  return { write, lines };
}

/**
 * Build the whole route. Exported so a test or a bare HTTP server (`bin/mesh-http.mjs`) can mount
 * exactly what the engine mounts, with no engine in the room.
 */
export function createMeshHttp({ config = {}, log = () => {}, identity = undefined, localInputs = undefined, env = process.env } = {}) {
  const merged = { ...DEFAULTS, ...readEnvConfig(env), ...Object.fromEntries(Object.entries(config).filter(([, value]) => value !== undefined)) };
  merged.secretFile = merged.secretFile ?? defaultSecretFile();
  merged.cwd = merged.cwd ?? defaultCwd();
  merged.artifactDir = merged.artifactDir ?? defaultArtifactDir();
  merged.dshBin = locateDshBin(merged.dshBin);

  const said = createNodeIdentity({ nodeNameOverride: merged.nodeName, degradedRetryMs: merged.degradedRetryMs });
  const who = identity ?? (() => said.describe());
  const auth = new MeshAuth({ resolveSecret: () => loadSecret(merged.secretFile), skewSeconds: merged.skewSeconds });

  // ---- the ceiling, derived from this node's own capacity --------------------------------
  // The LOCAL terms are read synchronously and are always available; the node's DECLARED ceiling
  // comes from its own capacity contract over loopback, cached and single-flight, and only ever
  // narrows the answer (`lib/concurrency.js` argues why it is a cap and not a source).
  const inputs = localInputs ?? readLocalInputs();
  const forced = Number.isFinite(Number(merged.maxConcurrent)) && Number(merged.maxConcurrent) >= 1
    ? Math.floor(Number(merged.maxConcurrent))
    : null;
  const capacity = createDeclaredCapacityReader({
    url: merged.capacityUrl,
    ttlMs: merged.capacityTtlMs,
    timeoutMs: merged.capacityTimeoutMs,
  });
  const resolution = {
    limit: 0, forced, terms: {}, inputs: {}, sources: {}, note: '', contract: { url: merged.capacityUrl, readAt: null, error: null },
  };
  const recompute = (declaredMax, contract) => {
    const derived = deriveConcurrencyLimit({
      ...inputs,
      declaredMax,
      cpuBudgetFraction: merged.cpuBudgetFraction,
      cpuPerTurn: merged.cpuPerTurn,
      commitPerTurnMiB: merged.commitPerTurnMiB,
      reserveMiB: merged.reserveMiB,
      hardCeiling: merged.hardCeiling,
    });
    Object.assign(resolution, derived);
    resolution.inputs = { ...derived.inputs, declaredMax };
    resolution.forced = forced;
    if (forced !== null) {
      resolution.terms = { ...derived.terms, forced, binding: 'forced' };
      resolution.limit = Math.min(forced, merged.hardCeiling);
      resolution.note = `MESH_HTTP_MAX_CONCURRENT (or config.maxConcurrent) forces ${resolution.limit}; the derived minimum was ${derived.limit}.`;
    }
    if (contract !== undefined) resolution.contract = contract;
    return resolution;
  };
  recompute(null, { url: merged.capacityUrl, readAt: null, error: 'not read yet' });

  const runner = new OneShotRunner({
    nodeExe: merged.nodeExe,
    dshBin: merged.dshBin,
    profile: merged.profile,
    subcommand: merged.subcommand,
    timeoutMs: merged.defaultTimeoutSec * 1000,
    maxOutputBytes: merged.maxOutputBytes,
    artifactDir: merged.artifactDir,
    log,
    maxConcurrent: resolution.limit,
    maxQueueWaitMs: merged.maxQueueWaitSec * 1000,
    refuseWhenFull: merged.refuseWhenFull,
    hardCeiling: merged.hardCeiling,
  });

  /** Re-read the declared ceiling and move the runner's limit. Never throws, never blocks a run. */
  const refreshLimit = async () => {
    const read = await capacity.read();
    const capacityNode = read.value ?? null;
    recompute(declaredMaxChildren(capacityNode), {
      url: merged.capacityUrl,
      readAt: read.at === null || read.at === 0 ? null : new Date(read.at).toISOString(),
      error: read.error ?? null,
      node: capacityNode?.node ?? null,
      maxChildren: declaredMaxChildren(capacityNode),
      cpuLogical: capacityNode?.cpu?.logical ?? null,
      cpuPhysical: capacityNode?.cpu?.physical ?? null,
      memFreeMiB: capacityNode?.mem?.freeMiB ?? null,
    });
    const moved = runner.setLimit(resolution.limit);
    if (moved.previous !== moved.limit) {
      log(`mesh-http concurrency ${moved.previous} -> ${moved.limit} (${resolution.note})`);
    }
    return resolution;
  };

  const run = createMeshRunHandler({ config: merged, auth, runner, identity: who, log, refreshLimit });
  const health = createMeshHealthHandler({
    config: merged,
    auth,
    runner,
    identity: who,
    log,
    version: VERSION,
    concurrency: resolution,
    refreshLimit,
  });

  return {
    config: merged,
    auth,
    runner,
    identity: who,
    /** The arithmetic behind the ceiling, exactly as `/mesh/health` publishes it. */
    concurrency: resolution,
    refreshLimit,
    handler: async (req, res) => {
      const url = safePath(req.url);
      if (url === merged.healthPath) return health(req, res);
      return run(req, res);
    },
    health,
    /** What `/mesh/health` answers, without an HTTP round trip (used by the CLI and the tests). */
    readout() {
      const resolved = auth.resolveSecret();
      return {
        service: 'mesh-http',
        version: VERSION,
        route: merged.path,
        ...who(),
        secretConfigured: resolved.ok === true,
        secretPath: resolved.path,
        secretReason: resolved.ok === true ? null : resolved.reason,
        dshBin: merged.dshBin ?? null,
        profile: merged.profile,
        cwd: merged.cwd,
        artifactDir: merged.artifactDir,
        concurrency: resolution,
        runner: runner.view(),
      };
    },
  };
}

/** `req.url` minus its query, with the character set rejected rather than echoed. */
function safePath(url) {
  const raw = typeof url === 'string' ? url : '';
  const cut = raw.indexOf('?');
  const onlyPath = cut === -1 ? raw : raw.slice(0, cut);
  return /^[\x20-\x7e]*$/.test(onlyPath) ? onlyPath : '';
}

/**
 * Cordis plugin entry. Registers both routes when the composition has a `webServer`, and does
 * nothing else — no timers, no samplers, no process of its own.
 *
 * `ctx.inject(['webServer'], …)` rather than a declared `inject`: plugin-health's reasoning
 * applies unchanged (`packages/plugin-health/lib/index.js:575-583`) — a row that declares a
 * service it does not get either waits for ever or fails the boot, and a mesh route must be
 * unable to make a node unbootable.
 */
export function apply(ctx, config = {}) {
  const engineLog = (line) => {
    try {
      ctx.logger?.info?.(line);
    } catch { /* a context without a logger still gets the line below */ }
    process.stdout.write(`${line}\n`);
  };
  const plugin = createMeshHttp({ config, log: engineLog });

  const mount = (webCtx) => {
    const webServer = webCtx.get('webServer');
    if (webServer === undefined || typeof webServer.register !== 'function') return;
    // The declared ceiling is read once at mount and then refreshed by every health read and every
    // dispatch. Not awaited: a route that cannot mount because a capacity contract was slow is
    // exactly the coupling `lib/concurrency.js` refuses, and the LOCAL terms already derived a
    // working ceiling before this call.
    plugin.refreshLimit().catch(() => {});
    webCtx.effect(() => webServer.register({
      kind: 'exact',
      path: plugin.config.path,
      handler: plugin.handler,
    }), `mesh-http: ${plugin.config.path}`);
    webCtx.effect(() => webServer.register({
      kind: 'exact',
      path: plugin.config.healthPath,
      handler: plugin.health,
    }), `mesh-http: ${plugin.config.healthPath}`);
    ctx.logger?.info?.(`mesh-http: ${plugin.config.path} and ${plugin.config.healthPath} registered on this node`
      + ` (secret ${plugin.readout().secretConfigured ? 'present' : `NOT CONFIGURED at ${plugin.config.secretFile}`})`
      + ` (concurrency ${plugin.runner.maxConcurrent}: ${plugin.concurrency.note})`);
  };

  if (typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], mount);
    return;
  }
  if (ctx.get?.('webServer') !== undefined) mount(ctx);
}

export { MeshAuth } from './auth.js';
export { OneShotRunner, composeTask, taskDisposition, childArgv, defaultArtifactDir } from './runner.js';
export { createNodeIdentity } from './node-identity.js';
export { loadSecret, parseEnvText } from './secret.js';
export {
  COMMIT_PER_TURN_MIB,
  CPU_PER_TURN,
  HARD_CEILING,
  LOGICAL_CPU_BUDGET_FRACTION,
  createDeclaredCapacityReader,
  declaredMaxChildren,
  deriveConcurrencyLimit,
  fetchJsonOnce,
  readAvailableMemoryMiB,
  readLocalInputs,
} from './concurrency.js';
