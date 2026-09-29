#!/usr/bin/env node
/**
 * dsh-update / lib/settings-effective.mjs — read the engine's own EFFECTIVE settings after a real
 * boot and assert that every settings key this deployment sets survived into it.
 *
 * WHY THIS EXISTS (SPEC §C2)
 * --------------------------
 * G4 proved only that the engine BOOTS with our `settings.yaml`. Measured 2026-09-23 on 0.1.5-rc.1:
 * an unknown top-level key, an unknown key inside a known section, a wrong value type, an
 * out-of-range number and an invalid enum value ALL boot with exit 0 and print NO diagnostic at all.
 * A settings key the newer version has quietly stopped honouring is therefore invisible to every
 * gate in this pipeline — the silent-loss class the subsystem exists to catch.
 *
 * THE MECHANISM, AND WHERE IT WAS READ FROM (all on the live install, 0.1.5-rc.1)
 * ------------------------------------------------------------------------------
 * The web profile is a server, and its settings controller answers a plain HTTP RPC. Every step
 * below is quoted from the installed package that implements it, not inferred:
 *
 *   1. The route shape. `@deepseek-ai/dsh-api-gateway/lib/index.js:455`
 *        `connectionCtx.connection.rpc.intercept("/api", (endpoint) => this.claimsEndpoint(endpoint), ...)`
 *      and `dsh-api-gateway/lib/client.js:49`
 *        `const REMOTE_STREAM_MUX_PATH = "/api/remote.mux";`
 *      so an endpoint `<namespace>/<method>` is addressed as `POST /api/<namespace>/<method>`.
 *
 *   2. The request envelope. `@deepseek-ai/dsh-client-connection/lib/index.js:502-507`
 *        `clientRequestSchema = z.object({ type: z.literal("client-request"), rpcId, method, payload })`
 *      with `payload` required to hold exactly one plain-object `args` field
 *      (`dsh-api-gateway/lib/index.js:929`, `remoteRequest`), and `content-type: application/json`
 *      required (`dsh-client-connection/lib/index.js:641`, measured: a wrong content type is a 415).
 *      The response is `{ type: "server-response", rpcId, result: { ok: true, value } | { ok: false, error } }`.
 *
 *   3. The endpoint and its payload. `@deepseek-ai/dsh-api-settings-controller/lib/index.js:412`
 *        `super(ctx, "settingsController", { namespace: "settings" });`
 *      and `:424` `describe()` -> `{ writable, hasDocument, namespaces: settings.describe({redactSecrets:true}).map(namespaceView) }`.
 *      `describe()` takes no arguments, so `args` is `{}`. Measured: `POST /api/settings/describe`
 *      with `{"args":{}}` returns 14 namespace descriptors; a bogus endpoint is a clean 404.
 *
 *   4. What a descriptor MEANS. `@deepseek-ai/dsh-settings/lib/index.js:351` (`describe`) returns,
 *      per registered namespace, `{ ns, schema, value, base?, user?, applies, revision, secrets? }`
 *      where `value` is the RESOLVED settings value. `:509` (`resolve`) is
 *      `schema(mergeLayers(base, section))` — the registered schema applied over the composition
 *      `base` over the raw user section. A key our document sets that the candidate no longer
 *      accepts is dropped by that schema application, so it is ABSENT from `value`, while a key it
 *      accepts is present with our value. That is the authoritative silent-loss signal.
 *
 *   5. The fence and the credential. `/api` is behind the `trustedHosts` fence but loopback is
 *      trusted by construction (`dsh-client-connection/lib/index.js:206`
 *      `if (!isLoopbackHostname(hostUrl.hostname) && !isTrustedAuthority(...)) return false;`), and
 *      the remaining 401 is browser authentication (`:553-555`). The running `dsh web` prints its own
 *      authenticated URL — `dsh-web-app/lib/index.js:203`
 *      `console.log(\`dsh web: ${authenticatedUrl}${...}\`)` — carrying the per-process launch token,
 *      which a GET `/` exchanges for the signed session cookie (`:392-408`). So the readback is:
 *      launch on 127.0.0.1, take the token from the engine's OWN stdout, exchange it, call the RPC.
 *
 * A HEADLESS MECHANISM WAS LOOKED FOR FIRST AND DOES NOT EXIST. `dsh --help` on this install
 * offers only `web`, `plugin`, `--dump-config`, `--dump-default-config` and `--from-default-profile`;
 * there is no settings subcommand, and `--dump-config` dumps the plugin TREE, which is composition,
 * never the settings document (SPEC §Verify gates: "`--dump-config` never reads the settings
 * document"). The `settings` service is in-process and unreachable without a host, so the HTTP
 * readback on the web profile is the only path, and it is the one SPEC §C2 names.
 *
 * SAFETY (implemented here, not described here)
 * ---------------------------------------------
 *  * Never points an engine at the live DSH_HOME: an isolated home is built under the OS temp
 *    directory from `settings.yaml`, `.agent-presets/` and `profiles/<name>/**` INCLUDING each
 *    profile's own `node_modules` but EXCLUDING the shared `profiles/node_modules` (SPEC §C5 —
 *    measured: `Copy-Item -Recurse` over `~/.dsh/profiles` walks a 187-package tree and times out,
 *    while dropping every `node_modules` makes the profile fail to resolve `dsh-plugin-attention`).
 *  * The credential is resolved from the live `$DSH_HOME/.credentials.yaml` and passed in the CHILD
 *    ENVIRONMENT ONLY. It is never copied into the isolated home, never printed, never logged: its
 *    length is the only thing this module ever reports. The launch token the engine prints is
 *    treated the same way, because it grants the same API.
 *  * The boot is on a port in 3400-3500, taken only after a pre-flight check that it is free, and
 *    the ONLY process ever killed is the exact pid this module started (`taskkill /PID <pid> /T /F`).
 *    Port 3099 and the live engine are never touched, never started, never stopped; they are only
 *    OBSERVED, before and after, so the run can prove it left them alone.
 *  * Writes go to `dsh-update/state/logs/` and to `--out` only, plus the OS temp directory.
 *    Nothing is deleted anywhere; there is no unlink/rm/rmdir call in this file.
 *  * A run that cannot establish the mechanism, cannot boot, or cannot resolve the credential
 *    reports `ran: false` with the verbatim reason and NEVER a passing verdict. An empty read is a
 *    failure, not an empty success (SPEC §Safety invariants 8).
 *
 * DETERMINISM. Keys are sorted; findings are sorted; `--generated-at` / `SOURCE_DATE_EPOCH` pins the
 * only clock in the artifact. Port, pid and the boot duration are live facts of one run and cannot
 * be byte-identical on a re-run; they are the four fields listed in `volatile` so a comparison can
 * exclude exactly those and nothing else.
 *
 * CLI: node lib/settings-effective.mjs [--engine <bin.js>] [--version <ver>] [--dsh-home <path>]
 *      [--settings <settings.yaml>] [--consumed <consumed.json>] [--port <n>]
 *      [--out <settings-effective.json>] [--generated-at <iso>] [--logs-dir <dir>]
 *      [--baseline-engine <bin.js>] [--timeout <ms>]
 */

import fs from 'node:fs';
import os from 'node:os';
import net from 'node:net';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import process from 'node:process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');                     // dsh-update/
const STATE = path.join(ROOT, 'state');
const DEFAULT_LOGS = path.join(STATE, 'logs');

/** The live engine's port. Never bound, never probed beyond a read-only listener lookup. */
const LIVE_PORT = 3099;
const PORT_RANGE = [3400, 3500];
const NEVER_BOUND = Object.freeze([LIVE_PORT]);

const DEFAULT_LIVE_HOME = process.env.DSH_HOME && process.env.DSH_HOME.trim() !== ''
  ? process.env.DSH_HOME
  : path.join(process.env.USERPROFILE ?? process.env.HOME ?? '.', '.dsh');

const DEFAULT_NPX_INSTALL = path.join(
  process.env.LOCALAPPDATA ?? path.join(process.env.USERPROFILE ?? '.', 'AppData', 'Local'),
  'npm-cache', '_npx', '1e7f6d9597241db0',
);

const SCHEMA_VERSION = 1;
const CLASS = 'S1';

const USAGE = `usage: node lib/settings-effective.mjs [--engine <bin.js>] [--version <ver>]
                                       [--dsh-home <path>] [--settings <settings.yaml>]
                                       [--consumed <consumed.json>] [--port <n>]
                                       [--out <settings-effective.json>] [--generated-at <ISO-8601>]
                                       [--logs-dir <dir>] [--baseline-engine <bin.js>]
                                       [--timeout <ms>]

Boots the web profile of an engine against an ISOLATED copy of DSH_HOME on a free port in
3400-3500, reads the engine's own effective settings through the web profile's settings
controller (POST /api/settings/describe), and asserts that every settings key this deployment
sets is present in that report with the value it set. A key that is absent or different is S1
(settings key silently lost) with severity BREAKS, because the engine's own report is
AUTHORITATIVE evidence about what it is actually running with.

When the mechanism cannot be established, the boot fails, or the credential is unavailable, the
artifact records ran:false with the verbatim reason and no passing verdict. Exit 0 whenever the
artifact was produced (verdict/ok tell you what it found); 2 on a usage or infrastructure error.

--engine defaults to the well-known npx install on this deployment. --baseline-engine adds a
second, opt-in boot of the CURRENT engine so 'namespace stopped being registered' can be told
apart from 'this key was never consumed in the first place'.`;

class UsageError extends Error {}

/* =================================================================== arguments */

const VALUED = new Set([
  '--engine', '--version', '--dsh-home', '--state-home', '--settings', '--consumed', '--port', '--out',
  '--generated-at', '--logs-dir', '--baseline-engine', '--timeout',
]);

function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') return { help: true };
    const eq = a.indexOf('=');
    const key = eq > 0 ? a.slice(0, eq) : a;
    if (!VALUED.has(key)) throw new UsageError(`unknown argument "${a}"`);
    const value = eq > 0 ? a.slice(eq + 1) : argv[++i];
    if (value === undefined) throw new UsageError(`missing value for ${key}`);
    flags[key] = value;
  }
  // A port outside the permitted range, or the LIVE engine's port, is a USAGE error: it must fail
  // before anything is built or started, not be discovered after an isolated home exists.
  if (flags['--port'] !== undefined) {
    const p = Number(flags['--port']);
    if (p === LIVE_PORT) {
      throw new UsageError(`--port ${LIVE_PORT} is the LIVE engine's port, and this module never binds it (the permitted range is ${PORT_RANGE[0]}-${PORT_RANGE[1]})`);
    }
    if (!Number.isInteger(p) || p < PORT_RANGE[0] || p > PORT_RANGE[1]) {
      throw new UsageError(`--port ${flags['--port']} is outside the permitted range ${PORT_RANGE[0]}-${PORT_RANGE[1]}`);
    }
  }
  return { flags };
}

function generatedAt(flags) {
  const raw = flags['--generated-at'] ?? process.env.SOURCE_DATE_EPOCH;
  // An empty string is "not supplied", not a date: `SOURCE_DATE_EPOCH=""` and a flag value that got
  // stringified to "undefined" by a caller must not become a usage error several steps later.
  if (raw === undefined || raw === null || String(raw).trim() === '') return new Date().toISOString();
  const pinned = String(raw).trim();
  const t = /^\d+$/.test(pinned) ? new Date(Number(pinned) * 1000) : new Date(pinned);
  if (Number.isNaN(t.getTime())) throw new UsageError(`--generated-at ${JSON.stringify(pinned)} is not a date`);
  return t.toISOString();
}

function assertSafeVersion(version) {
  const v = String(version ?? '').trim();
  if (!v || v === '.' || v === '..' || /[\\/]/.test(v) || v.includes('..') || !/^[0-9A-Za-z][0-9A-Za-z.+_-]*$/.test(v)) {
    throw new UsageError(`version ${JSON.stringify(version)} is not usable as a file name`);
  }
  return v;
}

/* =================================================================== small utilities */

const iso = (d = new Date()) => d.toISOString();

function readJsonIfPresent(file) {
  try {
    if (!fs.existsSync(file)) return null;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function sha256Hex(text) {
  return crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');
}

function itemCount(target) {
  const out = { files: 0, bytes: 0, links: 0 };
  if (!fs.existsSync(target)) return out;
  const head = fs.lstatSync(target);
  if (head.isSymbolicLink()) { out.links += 1; return out; }
  if (!head.isDirectory()) { out.files += 1; out.bytes = head.size; return out; }
  const stack = [target];
  while (stack.length > 0) {
    const d = stack.pop();
    let entries;
    try { entries = fs.readdirSync(d, { withFileTypes: true }); } catch { continue; }
    for (const e of entries) {
      const p = path.join(d, e.name);
      let st;
      try { st = fs.lstatSync(p); } catch { continue; }
      if (st.isSymbolicLink()) { out.links += 1; continue; }
      if (st.isDirectory()) { stack.push(p); continue; }
      out.files += 1;
      out.bytes += st.size;
    }
  }
  return out;
}

/**
 * Copy preserving links. A link that could not be recreated is RECORDED, not thrown: the profile
 * tree belongs to the deployment, and one unreadable junction must not turn the whole gate into
 * `ran: false` while every other file copied fine. The count surfaces in the artifact as
 * `linkFailures`, and the boot that follows is what decides whether it mattered.
 *
 * Measured case for that rule: `profiles/web/node_modules/dsh-mesh-broker` is a directory whose
 * link target is another part of this same repo, and a concurrent writer there makes
 * `fs.copyFileSync(fs.realpathSync(src), dst)` fail with EPERM — which, thrown, aborted the whole run.
 */
function copyTree(src, dst, stats) {
  const st = fs.lstatSync(src);
  if (st.isSymbolicLink()) {
    const target = fs.readlinkSync(src);
    let isDir = false;
    try { isDir = fs.statSync(src).isDirectory(); } catch { isDir = false; }
    let linkErr = null;
    try {
      fs.symlinkSync(target, dst, isDir ? 'junction' : 'file');
      stats.links += 1;
      return;
    } catch (err) { linkErr = err; }
    const record = (detail) => {
      stats.linkFailures += 1;
      stats.linkFailureDetail = stats.linkFailureDetail ?? [];
      stats.linkFailureDetail.push(detail);
    };
    let real = null;
    try { real = fs.realpathSync(src); } catch { /* the target itself may be gone */ }
    if (real === null || !fs.existsSync(real)) {
      record(`${src} -> ${dst}: symlink failed (${linkErr.code ?? linkErr.message}) and the link target could not be read`);
      return;
    }
    try {
      if (isDir) copyTree(real, dst, stats);
      else { fs.mkdirSync(path.dirname(dst), { recursive: true }); fs.copyFileSync(real, dst); }
      stats.copiedLinks += 1;
      return;
    } catch (copyErr) {
      record(`${src} -> ${dst}: symlink failed (${linkErr.code ?? linkErr.message}); copying the target failed (${copyErr.code ?? copyErr.message})`);
      return;
    }
  }
  if (st.isDirectory()) {
    fs.mkdirSync(dst, { recursive: true });
    for (const name of fs.readdirSync(src)) copyTree(path.join(src, name), path.join(dst, name), stats);
    return;
  }
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(src, dst);
  stats.files += 1;
  stats.bytes += st.size;
}

/* =================================================================== the isolated home */

/**
 * Build the isolated DSH_HOME. WHAT IS COPIED, AND WHY THAT EXACT SET (SPEC §C5):
 *   settings.yaml            the document under test — NOT necessarily the live one (see below)
 *   .agent-presets/          the deployment's preset roster
 *   profiles/<name>/**       each profile INCLUDING its own node_modules
 *   NOT profiles/node_modules   the shared 187-package engine tree; the measured timeout
 *
 * `settingsSrc` is a parameter rather than always `liveHome/settings.yaml` because the engine must
 * boot with the DOCUMENT UNDER TEST: a run that compared one document while booting another would
 * report the live file's keys and never see the tampered one at all — measured, and exactly the way
 * this gate would have looked like it worked while testing nothing.
 */
function buildIsolatedHome({ liveHome, home, profiles, logs, settingsSrc }) {
  const stats = { files: 0, bytes: 0, links: 0, copiedLinks: 0, linkFailures: 0 };
  const notes = [];
  const t0 = Date.now();
  fs.mkdirSync(home, { recursive: true });

  const documentSrc = settingsSrc ?? path.join(liveHome, 'settings.yaml');
  if (!fs.existsSync(documentSrc)) throw new Error(`the settings document ${documentSrc} does not exist`);
  copyTree(documentSrc, path.join(home, 'settings.yaml'), stats);
  notes.push(`the isolated home's settings.yaml is a copy of the DOCUMENT UNDER TEST (${documentSrc})${path.resolve(documentSrc) === path.resolve(path.join(liveHome, 'settings.yaml')) ? ', which is the live one for this run' : ', which is NOT the live one'}`);

  const presetsSrc = path.join(liveHome, '.agent-presets');
  if (fs.existsSync(presetsSrc)) copyTree(presetsSrc, path.join(home, '.agent-presets'), stats);
  else notes.push(`${presetsSrc} does not exist; the isolated home has no .agent-presets/`);

  for (const profile of profiles) {
    const src = path.join(liveHome, 'profiles', profile);
    if (!fs.existsSync(src)) { notes.push(`profile "${profile}" is not present at ${src}`); continue; }
    copyTree(src, path.join(home, 'profiles', profile), stats);
  }
  // the shared profiles/node_modules is deliberately NOT copied (SPEC §C5)
  const shared = path.join(liveHome, 'profiles', 'node_modules');
  if (fs.existsSync(shared)) {
    const size = itemCount(shared);
    notes.push(`excluded the shared profiles/node_modules on purpose (${size.files} files / ${size.bytes} bytes): copying it is the measured 120 s timeout, and it is not needed because the engine resolves its own upstream plugins from the install`);
  }
  notes.push(`.credentials.yaml was NOT copied from the live home: the isolated home contains no live credential file, by design (SPEC §C14)`);

  return { ...stats, durationMs: Date.now() - t0, notes, measured: itemCount(home) };
}

/* =================================================================== credential */

/**
 * Resolve a credential from the LIVE home's `.credentials.yaml` records map. The file is never
 * copied into the isolated home and its value is never returned to a caller that prints things: the
 * only fields this module ever publishes about a secret are `present` and `length`.
 */
function resolveCredential(liveHome, envName = 'DEEPSEEK_API_KEY') {
  const file = path.join(liveHome, '.credentials.yaml');
  if (!fs.existsSync(file)) {
    return { present: false, value: null, source: file, reason: `${file} does not exist, so ${envName} cannot be resolved for the boot` };
  }
  let text;
  try { text = fs.readFileSync(file, 'utf8'); }
  catch (err) { return { present: false, value: null, source: file, reason: `${file} could not be read: ${err.message}` }; }
  // `records:` is a flat map of NAME: value. Match the key only at a normal mapping position.
  const re = new RegExp(`(?:^|\\n)[ \\t]*${envName}[ \\t]*:[ \\t]*(.+?)[ \\t]*(?=\\r?\\n|$)`);
  const m = re.exec(text);
  if (!m) return { present: false, value: null, source: file, reason: `${file} holds no ${envName} record` };
  let value = m[1].trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  if (value === '') return { present: false, value: null, source: file, reason: `${file} records ${envName} but the value is empty` };
  return { present: true, value, source: file, reason: null, length: value.length };
}

/* =================================================================== ports and the live engine */

function portFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

async function choosePort(requested) {
  const [lo, hi] = PORT_RANGE;
  if (requested !== undefined && requested !== null) {
    const p = Number(requested);
    if (!Number.isInteger(p) || p < lo || p > hi) throw new UsageError(`--port ${requested} is outside the permitted range ${lo}-${hi}`);
    if (p === LIVE_PORT) throw new UsageError(`--port ${LIVE_PORT} is the LIVE engine's port and this module never binds it`);
    if (!(await portFree(p))) throw new UsageError(`--port ${p} is already in use; this module will not take a port that is not free`);
    return p;
  }
  for (let p = lo; p <= hi; p++) {
    if (p === LIVE_PORT) continue;
    if (await portFree(p)) return p;
  }
  return null;
}

/**
 * Read-only observation of any `dsh web` process on this machine. It starts nothing and kills
 * nothing; it exists so the artifact can PROVE the live engine was left alone, and so a boot this
 * module is about to start can be checked against a real conflict.
 */
function observeWebProcesses() {
  const ps = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const script = "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | ForEach-Object { [pscustomobject]@{ pid=$_.ProcessId; created=$_.CreationDate.ToString('o'); cmd=$_.CommandLine } } | ConvertTo-Json -Compress";
  const r = spawnSync(ps, ['-NoProfile', '-NonInteractive', '-Command', script], { encoding: 'utf8', timeout: 60000, windowsHide: true });
  if (r.status !== 0 || typeof r.stdout !== 'string') {
    return { checked: false, reason: `could not enumerate node processes (exit ${r.status}, ${String(r.error ?? r.stderr ?? '').slice(0, 200)})`, matched: [] };
  }
  let rows = [];
  try { const j = JSON.parse(r.stdout || '[]'); rows = Array.isArray(j) ? j : [j]; }
  catch { return { checked: false, reason: 'the process listing did not parse as JSON', matched: [] }; }
  const matched = rows.filter((x) => typeof x?.cmd === 'string' && /\bdsh(?:\.js)?["']?\s+web\b|bin\.js"?\s+web\b|--profile\s+web\b/.test(x.cmd));
  return { checked: true, reason: null, matched };
}

/** The identity of the live engine, as a read-only reading that a later reading can be compared to. */
function liveEngineReading() {
  const ps = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const script = `$c = Get-NetTCPConnection -State Listen -LocalPort ${LIVE_PORT} -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"; [pscustomobject]@{ listening=$true; pid=$c.OwningProcess; created=$p.CreationDate.ToString('o'); cmd=$p.CommandLine } | ConvertTo-Json -Compress } else { [pscustomobject]@{ listening=$false } | ConvertTo-Json -Compress }`;
  const r = spawnSync(ps, ['-NoProfile', '-NonInteractive', '-Command', script], { encoding: 'utf8', timeout: 60000, windowsHide: true });
  if (r.status !== 0 || typeof r.stdout !== 'string' || r.stdout.trim() === '') {
    return { read: false, reason: `could not read the live engine on port ${LIVE_PORT} (exit ${r.status}, ${String(r.error ?? r.stderr ?? '').slice(0, 200)})` };
  }
  try {
    const j = JSON.parse(r.stdout);
    return { read: true, reason: null, listening: j.listening === true, pid: j.pid ?? null, created: j.created ?? null, cmd: j.cmd ?? null };
  } catch {
    return { read: false, reason: 'the live-engine reading did not parse as JSON' };
  }
}

/* =================================================================== the boot and the readback */

function buildChildEnv({ home, credential }) {
  // A deliberate ALLOWLIST: nothing else from this process's environment reaches the child, so a
  // live credential sitting in our own environment cannot leak anywhere by inheritance, and
  // DSH_HOME can never be the live one.
  const keep = ['PATH', 'Path', 'SystemRoot', 'SystemDrive', 'windir', 'COMSPEC', 'PATHEXT',
    'TEMP', 'TMP', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA', 'APPDATA',
    'ProgramData', 'ProgramFiles', 'ProgramFiles(x86)', 'NUMBER_OF_PROCESSORS', 'OS', 'PROCESSOR_ARCHITECTURE'];
  const env = { DSH_HOME: home };
  for (const k of keep) if (typeof process.env[k] === 'string') env[k] = process.env[k];
  if (credential?.present) env[credential.name] = credential.value;   // environment only, never a file
  return env;
}

/** The exact token `dsh web` prints for itself, read out of its own stdout. Never written anywhere. */
function extractLaunchUrl(logText) {
  const m = /dsh web: (\S+)/.exec(logText ?? '');
  if (!m) return null;
  try {
    const url = new URL(m[1]);
    const token = url.searchParams.get('token');
    return token ? { url, token } : null;
  } catch {
    return null;
  }
}

function redactToken(text, token) {
  if (typeof text !== 'string' || !token) return text;
  return text.split(token).join('<redacted-launch-token>');
}

/**
 * THE ISOLATED HOME GETS A PLACEHOLDER CREDENTIALS DOCUMENT, AND THIS IS WHY.
 *
 * Measured on 0.1.5-rc.1 (two boots, both verbatim in the run that produced this module): when the
 * isolated home has NO `.credentials.yaml`, the engine's credential provider is created against that
 * path and, given `DEEPSEEK_API_KEY` in its environment, WRITES THE SECRET TO DISK — the isolated
 * home ends up holding a real API key in plaintext. That breaks the rule this module exists under
 * ("never write a secret to a log or artifact") without this module ever opening the file itself.
 *
 * The file the engine accepts is the versioned one. A boot with `records: {}` (the pre-release flat
 * layout) FAILS LOUDLY: "uses the pre-release flat layout. Add `version: 1` and nest the existing 1
 * entry under `refs:`". With `version: 1 / refs: {}` the engine boots, authenticates, answers the RPC
 * and persists ONLY its own generated `client-connection/browser-session` grant (20 -> 170 bytes,
 * measured) — the deployment key is never written, because it is already resolvable from the
 * environment and the provider has nothing to add.
 *
 * So the placeholder is written BEFORE the boot, contains no secret, and the key names are checked
 * against the file AFTER the boot. Nothing is ever deleted.
 */
const CREDENTIALS_PLACEHOLDER = 'version: 1\nrefs: {}\n';

function seedCredentialsPlaceholder(home) {
  const file = path.join(home, '.credentials.yaml');
  const existed = fs.existsSync(file);
  if (!existed) fs.writeFileSync(file, CREDENTIALS_PLACEHOLDER, 'utf8');
  return {
    file,
    createdByThisModule: !existed,
    bytesBeforeBoot: fs.existsSync(file) ? fs.statSync(file).size : 0,
    sha256BeforeBoot: fs.existsSync(file) ? sha256Hex(fs.readFileSync(file, 'utf8')) : null,
    containsAnySecretBeforeBoot: null,
  };
}

/**
 * After the boot: the placeholder's own content must not have acquired the deployment key. This is a
 * byte-level check of a file this module deliberately created in an isolated directory, so it is
 * reported as evidence rather than trusted as a promise.
 */
function auditCredentialsPlaceholder(seed, credential) {
  const exists = fs.existsSync(seed.file);
  const text = exists ? fs.readFileSync(seed.file, 'utf8') : '';
  const keyNames = credential?.present ? [credential.name] : [];
  const nameHits = keyNames.map((n) => ({ name: n, occurrences: text.split(n).length - 1 }));
  const valueHits = credential?.present ? text.split(credential.value).length - 1 : 0;
  const writtenKeys = [];
  const refRe = /^[ \t]{2}([^\s:][^\n:]*):[ \t]*$/gm;
  for (const m of text.matchAll(refRe)) writtenKeys.push(m[1]);
  return {
    file: seed.file,
    createdByThisModule: seed.createdByThisModule,
    bytesBeforeBoot: seed.bytesBeforeBoot,
    bytesAfterBoot: Buffer.byteLength(text, 'utf8'),
    deploymentKeyNamesPresent: nameHits.filter((h) => h.occurrences > 0).map((h) => h.name),
    deploymentKeyValueOccurrences: valueHits,
    keysWrittenByTheEngine: [...new Set(writtenKeys)].sort(),
    clean: valueHits === 0 && nameHits.every((h) => h.occurrences === 0),
  };
}

/**
 * Start the engine's web profile on `port` against the isolated home, wait for it, take its own
 * launch token, exchange it for the session cookie and call the settings controller. Returns the
 * verbatim evidence and the parsed descriptor set. Kills ONLY the pid it started.
 */
async function bootAndRead({ enginePath, home, cwd, port, credential, logsDir, version, timeoutMs, label }) {
  const result = {
    started: false, answered: false, pid: null, kill: null, killExitCode: null,
    bootDurationMs: null, tokenPresent: false, cookiePresent: false, httpStatus: null,
    rpcOk: null, rpcError: null, namespaces: null, raw: null, failure: null,
    preflightFree: false, postFree: null,
  };
  const logFile = path.join(logsDir, `settings-effective-${label}-engine.log`);
  fs.mkdirSync(logsDir, { recursive: true });
  result.engineLog = logFile;
  const seed = seedCredentialsPlaceholder(home);
  result.credentials = seed;

  const preflight = observeWebProcesses();
  result.otherWebProcesses = preflight;
  if (!preflight.checked) {
    result.failure = `refused before starting anything: could not prove no other dsh web process is running (${preflight.reason})`;
    return result;
  }
  const conflicts = preflight.matched.filter((x) => typeof x.cmd === 'string' && x.cmd.includes(String(port)));
  if (conflicts.length > 0) {
    result.failure = `refused: an existing dsh web process already names port ${port}: ${conflicts.map((c) => `pid ${c.pid}`).join(', ')}`;
    return result;
  }

  const out = fs.openSync(logFile, 'w');
  const child = spawn(process.execPath, [enginePath, 'web', '--port', String(port), '--no-open'], {
    env: buildChildEnv({ home, credential }),
    cwd,
    windowsHide: true,
    stdio: ['ignore', out, out],
  });
  const pid = child.pid;
  result.pid = pid ?? null;
  const bootPidForEvidence = pid ?? null;
  result.started = true;
  const t0 = Date.now();
  let exit = null;
  child.on('exit', (code) => { exit = code; });
  child.on('error', (err) => { result.failure = result.failure ?? `the engine could not be spawned: ${err.message}`; });

  let token = null;
  let cookie = null;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (exit !== null) break;
    let logText = '';
    try { logText = fs.readFileSync(logFile, 'utf8'); } catch { /* not written yet */ }
    if (token === null) {
      const found = extractLaunchUrl(logText);
      if (found) token = found.token;
    }
    if (token !== null) {
      result.tokenPresent = true;
      try {
        const hop = await fetch(`http://127.0.0.1:${port}/?token=${token}`, { redirect: 'manual' });
        if (hop.status === 303) {
          cookie = (hop.headers.getSetCookie?.() ?? []).map((c) => c.split(';')[0]).join('; ');
          if (cookie !== '') { result.answered = true; result.cookiePresent = true; break; }
        } else if (hop.status === 401) {
          // the server is up but this token was not accepted; keep waiting for a fresh line
          result.failure = `the engine answered HTTP 401 to its own launch token (a second token line may still be coming)`;
        }
      } catch { /* not listening yet */ }
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  result.bootDurationMs = Date.now() - t0;
  result.tokenForRedaction = token;

  if (!result.answered) {
    let logText = '';
    try { logText = fs.readFileSync(logFile, 'utf8'); } catch { /* nothing */ }
    const tail = logText.split(/\r?\n/).filter((l) => l.trim() !== '').slice(-25).join(' | ').slice(0, 1500);
    result.failure = result.failure
      ?? (exit !== null
        ? `the engine exited (code ${exit}) before its settings could be read; last output: ${tail || '(none)'}`
        : `the engine did not answer on 127.0.0.1:${port} within ${timeoutMs} ms${token === null ? ' (it never printed its launch URL)' : ` (its launch URL was read: ${result.tokenPresent})`}; last output: ${tail || '(none)'}`);
  }

  if (result.answered && cookie !== null) {
    const rpcId = 'settings-effective-1';
    const endpoint = 'settings/describe';
    const body = { type: 'client-request', rpcId, method: endpoint, payload: { args: {} } };
    let text = '';
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/${endpoint}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', cookie },
        body: JSON.stringify(body),
      });
      result.httpStatus = res.status;
      text = await res.text();
      if (res.status !== 200) {
        result.failure = `POST /api/${endpoint} answered HTTP ${res.status} rather than 200: ${text.slice(0, 400) || '(empty body)'}`;
      } else {
        let parsed = null;
        try { parsed = JSON.parse(text); } catch (err) {
          result.failure = `the RPC response was not JSON: ${err.message}`;
        }
        if (parsed !== null) {
          const envelopeOk = parsed?.type === 'server-response' && parsed.rpcId === rpcId;
          if (!envelopeOk) {
            result.failure = `the RPC response envelope was not the expected server-response for rpcId ${rpcId}`;
          } else if (parsed.result?.ok !== true) {
            result.rpcOk = false;
            result.rpcError = parsed.result?.error ?? null;
            result.failure = `the settings controller refused the call: ${parsed.result?.error?.code ?? '?'} ${parsed.result?.error?.message ?? ''}`.trim();
          } else {
            const value = parsed.result.value;
            if (!value || !Array.isArray(value.namespaces)) {
              result.failure = 'the settings controller answered ok but the payload carried no namespaces array — an empty read is a failure, not an empty success';
            } else {
              result.rpcOk = true;
              result.namespaces = value.namespaces;
              result.payload = { writable: value.writable, hasDocument: value.hasDocument, namespaceCount: value.namespaces.length };
            }
          }
        }
      }
    } catch (err) {
      result.failure = `the settings RPC failed: ${err.message}`;
    }
    result.raw = { request: body, status: result.httpStatus, bodyBytes: text.length, body: text };
    // Evidence for THIS boot, written under a name that carries the boot's own label so a baseline
    // boot and the candidate boot cannot overwrite each other's evidence.
    const evPath = path.join(logsDir, `settings-effective-${version}-${label}-rpc.json`);
    fs.mkdirSync(logsDir, { recursive: true });
    fs.writeFileSync(evPath, `${JSON.stringify({
      endpoint: 'POST /api/settings/describe',
      engine: enginePath,
      port,
      pid: bootPidForEvidence,
      httpStatus: result.httpStatus,
      request: body,
      responseBytes: result.raw.bodyBytes,
      response: redactToken(text, token),
      note: 'the per-process launch token was removed before this file was written; the deployment API key never appears in any engine output and was passed in the child environment only',
    }, null, 2)}\n`);
    result.rpcEvidence = evPath;
  }

  // ---- teardown: kill ONLY the pid this module started, and prove the port came back ----
  result.credentialsAudit = auditCredentialsPlaceholder(seed, credential);
  const killLog = [];
  if (result.started && pid) {
    const k = spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { encoding: 'utf8', windowsHide: true, timeout: 30000 });
    result.killExitCode = k.status;
    result.kill = `taskkill /PID ${pid} /T /F -> exit ${k.status}: ${String(k.stdout ?? '').trim() || String(k.stderr ?? '').trim()}`;
    try { child.kill('SIGKILL'); } catch { /* already gone */ }
    killLog.push(result.kill);
  } else {
    result.kill = 'not killed — no pid was started';
  }
  try { fs.closeSync(out); } catch { /* ignore */ }

  // the port must be free again; retry briefly because socket release is not instantaneous
  let free = false;
  for (let i = 0; i < 20 && !free; i++) {
    free = await portFree(port);
    if (!free) await new Promise((r) => setTimeout(r, 250));
  }
  result.postFree = free;
  if (!free) killLog.push(`port ${port} was STILL BOUND after the kill`);

  if (result.failure === null && !free) result.failure = `the engine was killed but port ${port} is still bound`;
  return result;
}

/* =================================================================== the comparison */

/** Read `settingsKeys` out of a consumed.json, tolerating the two shapes we have seen. */
function loadConsumedKeys(consumedPath) {  const doc = readJsonIfPresent(consumedPath);
  if (doc === null) return { ok: false, reason: `${consumedPath} is absent or does not parse as JSON`, keys: [] };
  const list = doc.settingsKeys;
  if (!Array.isArray(list) || list.length === 0) {
    return { ok: false, reason: `${consumedPath} carries no settingsKeys array (or it is empty) — with nothing to check this gate cannot pass`, keys: [] };
  }
  const keys = [];
  for (const entry of list) {
    if (!entry || typeof entry.key !== 'string' || entry.key.trim() === '') continue;
    keys.push({ key: entry.key.trim(), value: entry.value, file: entry.file ?? null, line: entry.line ?? null });
  }
  if (keys.length === 0) return { ok: false, reason: `${consumedPath} settingsKeys holds no usable "key" strings`, keys: [] };
  return { ok: true, reason: null, keys };
}

/**
 * Where consumed.json should be found when --consumed is not given: this version's candidate
 * directory first, then any other candidate's (the key inventory is a property of the DEPLOYMENT,
 * not of a version — every candidate's consumed.json is produced from the same config tree, and a
 * version the pipeline never fetched has no directory of its own).
 */
function defaultConsumedPath(version) {
  const exact = path.join(STATE, 'candidates', version, 'consumed.json');
  if (fs.existsSync(exact)) return exact;
  const dir = path.join(STATE, 'candidates');
  let found = [];
  try {
    found = fs.readdirSync(dir)
      .map((name) => path.join(dir, name, 'consumed.json'))
      .filter((p) => fs.existsSync(p))
      .sort();
  } catch { /* no candidates directory yet */ }
  return found.length > 0 ? found[found.length - 1] : exact;
}

/** Load the document under test, so a raw (pre-schema) value is available alongside the expected one. */
function loadSettingsDocument(settingsPath) {
  let text;
  try { text = fs.readFileSync(settingsPath, 'utf8'); } catch (err) {
    return { ok: false, reason: `${settingsPath} could not be read: ${err.message}`, text: null, doc: null };
  }
  const parsed = parseSimpleYaml(text);
  return parsed.ok
    ? { ok: true, reason: null, text, doc: parsed.doc, how: 'parsed by this module\'s YAML-subset reader' }
    : { ok: true, reason: null, text, doc: null, how: `the document was read as text only (${parsed.reason})` };
}

/**
 * A deliberately small YAML reader for the settings document: block maps, block sequences, plain and
 * quoted scalars, and the JSON-ish scalars YAML permits. It is not a general YAML implementation and
 * does not pretend to be one. It exists so the artifact can show what the DOCUMENT says next to what
 * the ENGINE resolved; the assertion never depends on it, and when it cannot parse the document the
 * gate says so and carries on with the consumed.json values, which is the interface's real input.
 */
function parseSimpleYaml(text) {
  const lines = String(text).split(/\r?\n/);
  const root = {};
  const stack = [{ indent: -1, node: root, kind: 'map' }];
  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    if (rawLine.trim() === '' || rawLine.trimStart().startsWith('#')) continue;
    const indent = rawLine.length - rawLine.trimStart().length;
    const line = rawLine.trim();
    if (line === '---' || line === '...') continue;
    const isItem = line.startsWith('- ');
    /*
     * Frame discipline for a document that mixes both YAML sequence spellings:
     *   `key:` then `  - x`           a deeper, indented sequence
     *   `key:` then `  - id: a` / `    name: b` / `  - id: c`    an INDENTATIONLESS sequence whose
     *                                 items are maps, each sitting at the key's own column
     * The second shape is why a frame cannot simply close on equal indentation: a `- ` at the current
     * frame's indent is the NEXT SIBLING of the previous item, so the previous item's map frame is
     * closed but the sequence frame it lives in is not.
     */
    if (isItem) {
      if (stack.length > 1) {
        const topFrame = stack[stack.length - 1];
        if (topFrame.kind === 'map' && topFrame.fromItem && topFrame.indent === indent) stack.pop();
      }
      while (stack.length > 1 && indent < stack[stack.length - 1].indent) stack.pop();
    } else {
      while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
    }
    const top = stack[stack.length - 1];
    if (line.startsWith('- ')) {
      if (top.kind !== 'seq') return { ok: false, reason: `line ${i + 1}: a sequence item outside a sequence` };
      const rest = line.slice(2).trim();
      const m = /^([^:]+):\s*(.*)$/.exec(rest);
      if (m && /^[A-Za-z_][\w.-]*$/.test(m[1].trim())) {
        const item = {};
        assign(item, m[1].trim(), m[2]);
        top.node.push(item);
        stack.push({ indent, node: item, kind: 'map', fromItem: true });
      } else {
        top.node.push(scalar(rest));
      }
      continue;
    }
    const m = /^([^:]+):\s*(.*)$/.exec(line);
    if (!m) return { ok: false, reason: `line ${i + 1}: not a mapping entry` };
    const key = m[1].trim();
    const rest = m[2];
    if (top.kind === 'seq') return { ok: false, reason: `line ${i + 1}: a mapping entry inside a sequence` };
    if (rest === '') {
      // decide map vs sequence by peeking at the next meaningful line
      let next = null;
      for (let j = i + 1; j < lines.length; j++) {
        const l = lines[j];
        if (l.trim() === '' || l.trimStart().startsWith('#')) continue;
        next = l;
        break;
      }
      const nextIndent = next === null ? -1 : next.length - next.trimStart().length;
      // YAML's own indentationless-sequence rule: `key:` followed at the SAME indentation by `- ` is
      // a sequence whose items belong to that key (this document uses exactly that shape under
      // `retryableCodes:`). A deeper `- ` is a sequence too; anything else is a nested map.
      const isSeq = next !== null && next.trim().startsWith('- ') && (nextIndent > indent || nextIndent === indent);
      if (isSeq) {
        top.node[key] = [];
        stack.push({ indent, node: top.node[key], kind: 'seq' });
      } else if (next !== null && nextIndent > indent) {
        top.node[key] = {};
        stack.push({ indent, node: top.node[key], kind: 'map' });
      } else {
        top.node[key] = null;
      }
      continue;
    }
    assign(top.node, key, rest);
  }
  return { ok: true, doc: root };
}

function assign(node, key, rest) {
  const inline = rest.trim();
  if (inline.startsWith('[') || inline.startsWith('{')) {
    try { node[key] = JSON.parse(inline.replace(/'/g, '"')); return; } catch { /* fall through */ }
  }
  node[key] = scalar(inline);
}

function scalar(token) {
  const s = String(token).trim();
  if (s === '' || s === '~' || s === 'null' || s === 'Null' || s === 'NULL') return null;
  if (s === 'true' || s === 'True' || s === 'TRUE') return true;
  if (s === 'false' || s === 'False' || s === 'FALSE') return false;
  if (s.startsWith('"') && s.endsWith('"') && s.length >= 2) {
    try { return JSON.parse(s); } catch { return s.slice(1, -1); }
  }
  if (s.startsWith("'") && s.endsWith("'") && s.length >= 2) return s.slice(1, -1).replace(/''/g, "'");
  if (/^-?\d+$/.test(s)) { const n = Number(s); if (Number.isSafeInteger(n)) return n; }
  if (/^-?\d*\.\d+(?:[eE][-+]?\d+)?$/.test(s) || /^-?\d+[eE][-+]?\d+$/.test(s)) { const n = Number(s); if (Number.isFinite(n)) return n; }
  return s;
}

/**
 * Walk a dotted path into a descriptor's resolved value. `models[]` names an element of an array:
 * it matches when any element carries the trailing value, which is how `consumed.json` spells the
 * repeated entries it found in a sequence.
 */
function walkPath(root, segments) {
  let cursor = root;
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const array = seg.endsWith('[]');
    const name = array ? seg.slice(0, -2) : seg;
    if (cursor === null || typeof cursor !== 'object') return { found: false, at: i };
    if (!(name in cursor)) return { found: false, at: i };
    let node = cursor[name];
    if (array) {
      if (!Array.isArray(node)) return { found: false, at: i };
      if (i === segments.length - 1) return { found: true, value: node, container: 'array-element' };
      // an array element path: match the FIRST element that has the remaining path — later the
      // comparison tries every element, so this is only the display value
      for (const el of node) {
        const sub = walkPath(el, segments.slice(i + 1));
        if (sub.found) return { found: true, value: sub.value, container: 'array-element' };
      }
      return { found: false, at: i };
    }
    cursor = node;
  }
  return { found: true, value: cursor, container: null };
}

/** Every value an array-element path can resolve to, so a repeated entry is checked against all of them. */
function walkAll(root, segments) {
  const out = [];
  const rec = (node, i) => {
    if (i === segments.length) { out.push({ value: node, remaining: [] }); return; }
    if (node === null || typeof node !== 'object') return;
    const seg = segments[i];
    const array = seg.endsWith('[]');
    const name = array ? seg.slice(0, -2) : seg;
    if (!(name in node)) return;
    if (array) {
      if (!Array.isArray(node[name])) return;
      for (const el of node[name]) rec(el, i + 1);
      return;
    }
    rec(node[name], i + 1);
  };
  rec(root, 0);
  return out;
}

function setAt(root, pathSegments, value) {
  let node = root;
  for (let i = 0; i < pathSegments.length - 1; i++) {
    const name = pathSegments[i];
    if (node[name] === undefined) node[name] = {};
    node = node[name];
  }
  node[pathSegments[pathSegments.length - 1]] = value;
}

function isPlainRecord(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** A dotted settings key as path segments; the single place that decision is made. */
function segmentsOf(key) {
  return String(key).split('.').filter((s) => s !== '');
}

/**
 * Enumerate the leaf paths of a parsed document, the way this module and `consumed.json` both spell
 * them: dotted, with `[]` marking an element of an array of maps. An array of maps contributes one
 * path per distinct field name — the same shape `consumed.json` records for a repeated entry. The
 * tests use this to build a consumed.json from a document.
 */
function leafPaths(doc, prefix = '', into) {
  const out = into ?? [];
  if (!isPlainRecord(doc)) return out;
  for (const key of Object.keys(doc)) {
    const next = prefix === '' ? key : `${prefix}.${key}`;
    const value = doc[key];
    if (isPlainRecord(value)) { leafPaths(value, next, out); continue; }
    if (Array.isArray(value) && value.every(isPlainRecord)) {
      const names = [];
      for (const el of value) for (const n of Object.keys(el)) if (!names.includes(n)) names.push(n);
      for (const name of names) out.push({ key: `${next}[].${name}`, value: null });
      continue;
    }
    out.push({ key: next, value });
  }
  return out;
}

function typeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value;
}

/** Structural equality with a stable key order, so two runs and two element orders compare the same. */
function canonical(value) {
  if (value === undefined) return 'undefined';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
}

function equalJson(a, b) {
  return canonical(a) === canonical(b);
}

function describeValue(value, max = 300) {
  const text = canonical(value);
  return text.length <= max ? text : `${text.slice(0, max)}…(${text.length} chars)`;
}

/* =================================================================== main */

async function main(argvInput = process.argv.slice(2), injected = {}) {
  let parsed;
  try { parsed = parseArgs(argvInput); }
  catch (err) {
    process.stderr.write(`settings-effective: ${err.message}\n\n${USAGE}\n`);
    return 2;
  }
  if (parsed.help) { process.stdout.write(`${USAGE}\n`); return 0; }
  const flags = parsed.flags;

  const liveHome = path.resolve(flags['--dsh-home'] ?? DEFAULT_LIVE_HOME);

  // WHERE RUNTIME STATE LIVES, separately from the config under test.
  //
  // `--dsh-home` names the config under test, and a staged run points it at a migrated copy under
  // %TEMP%. The model credential does NOT live there: whichever home the engine is given, it writes
  // its OWN credential file into it, and that file carries no deployment key. Measured 2026-09-28:
  // with `--dsh-home <staged>` this module reported
  //   `unverified: credential: <staged>\.credentials.yaml holds no DEEPSEEK_API_KEY record`
  // and `ran=false` with zero keys compared -- a correct refusal that produced no reading at all.
  // `verify.mjs` has the same split for the same reason; this is the settings readback's copy of it.
  //
  // Order: `--state-home`, then `$DSH_STATE_HOME`, then the operator's real home when `--dsh-home` is
  // plainly a staged location (under %TEMP% or under `dsh-update/state`), then `--dsh-home` itself.
  const realHome = path.join(process.env.USERPROFILE ?? process.env.HOME ?? '.', '.dsh');
  const stateEnv = process.env.DSH_STATE_HOME && process.env.DSH_STATE_HOME.trim() !== ''
    ? process.env.DSH_STATE_HOME
    : null;
  const looksStaged = liveHome !== path.resolve(realHome)
    && /(\\temp\\|\\dsh-update\\state\\)/i.test(liveHome + path.sep);
  const stateHome = path.resolve(
    flags['--state-home'] ?? stateEnv ?? (looksStaged && fs.existsSync(realHome) ? realHome : liveHome),
  );
  const logsDir = path.resolve(flags['--logs-dir'] ?? DEFAULT_LOGS);
  if (!fs.existsSync(liveHome)) {
    process.stderr.write(`settings-effective: --dsh-home "${liveHome}" does not exist\n`);
    return 2;
  }

  const enginePath = path.resolve(flags['--engine'] ?? path.join(DEFAULT_NPX_INSTALL, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js'));
  if (!fs.existsSync(enginePath)) {
    process.stderr.write(`settings-effective: engine "${enginePath}" does not exist (pass --engine <bin.js>)\n`);
    return 2;
  }
  const manifestPath = path.resolve(path.dirname(enginePath), '..', 'package.json');
  const manifest = readJsonIfPresent(manifestPath) ?? {};
  let version;
  try { version = assertSafeVersion(flags['--version'] ?? manifest.version ?? 'unknown'); }
  catch (err) { process.stderr.write(`settings-effective: ${err.message}\n`); return 2; }

  const settingsPath = path.resolve(flags['--settings'] ?? path.join(liveHome, 'settings.yaml'));
  const consumedPath = path.resolve(flags['--consumed'] ?? defaultConsumedPath(version));
  const timeoutMs = flags['--timeout'] ? Number(flags['--timeout']) : 120000;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    process.stderr.write('settings-effective: --timeout must be a positive number of milliseconds\n');
    return 2;
  }
  const genAt = (() => { try { return generatedAt(flags); } catch (err) { process.stderr.write(`settings-effective: ${err.message}\n`); return null; } })();
  if (genAt === null) return 2;

  const mechanism = {
    source: 'readback',
    why: 'the web profile is a server and its settings controller answers over HTTP; `dsh --help` on this install offers no settings subcommand and `--dump-config` never reads the settings document, so a boot plus an readback is the only path that can see a key the engine dropped',
    route: 'POST /api/settings/describe',
    requestEnvelope: '{type:"client-request", rpcId, method:"settings/describe", payload:{args:{}}}',
    quotedFrom: [
      "node_modules/@deepseek-ai/dsh-api-gateway/lib/index.js:455  connectionCtx.connection.rpc.intercept(\"/api\", (endpoint) => this.claimsEndpoint(endpoint), ...)",
      "node_modules/@deepseek-ai/dsh-client-connection/lib/index.js:502  clientRequestSchema = z.object({ type: z.literal(\"client-request\"), rpcId, method, payload })",
      "node_modules/@deepseek-ai/dsh-api-settings-controller/lib/index.js:412  super(ctx, \"settingsController\", { namespace: \"settings\" });",
      "node_modules/@deepseek-ai/dsh-api-settings-controller/lib/index.js:424  describe() -> { writable, hasDocument, namespaces: settings.describe({ redactSecrets: true }).map(namespaceView) }",
      "node_modules/@deepseek-ai/dsh-settings/lib/index.js:509  resolve(schema, base, section) { const value = schema(mergeLayers(base, section)); ... }   <- a key the schema no longer has is dropped here, silently",
      "node_modules/@deepseek-ai/dsh-client-connection/lib/index.js:206  if (!isLoopbackHostname(hostUrl.hostname) && !isTrustedAuthority(hostUrl, trustedHosts)) return false;",
      "node_modules/@deepseek-ai/dsh-web-app/lib/index.js:203  console.log(`dsh web: ${authenticatedUrl}${...}`)",
    ],
    credential: 'resolved from the live DSH_HOME/.credentials.yaml and passed in the child environment only: never copied into the isolated home, never printed, never written to a log',
    headlessAlternativesTried: [
      '`node <bin.js> --help` — the only subcommands on this install are `web` and `plugin`; no settings verb exists.',
      '`--dump-config` / `--dump-default-config` — these dump the composed plugin TREE, which is composition; per the SPEC they never read the settings document.',
      'the settings SERVICE (`ctx.settings`) is in-process and has no out-of-process surface except the web profile it is composed into.',
    ],
  };

  const notes = [];
  notes.push(`this gate answers the hole SPEC §C2 measured: on 0.1.5-rc.1 an unknown key, a wrong type, an out-of-range number and an invalid enum value all boot with exit 0 and no diagnostic, so only the engine's own effective settings can see a silently dropped key`);
  notes.push(`engine ${enginePath} (manifest @deepseek-ai/dsh@${manifest.version ?? '?'})`);

  const liveBefore = liveEngineReading();
  notes.push(liveBefore.read
    ? `the live engine on port ${LIVE_PORT} before this run: ${liveBefore.listening ? `listening, pid ${liveBefore.pid}, started ${liveBefore.created}` : 'nothing was listening'} (this module never binds or signals it)`
    : `the live engine on port ${LIVE_PORT} could not be read before this run: ${liveBefore.reason}`);

  const credential = resolveCredential(stateHome, 'DEEPSEEK_API_KEY');
  notes.push(`the model credential was looked for in the STATE home ${stateHome}`
    + (stateHome === liveHome ? ' (which is also the config under test for this run)' : ` (--dsh-home is the config under test, ${liveHome}; runtime state is read from the operator's home)`)
    + '. A reading that does not say where it came from is not a reading.');
  credential.name = 'DEEPSEEK_API_KEY';

  const out = {
    schemaVersion: SCHEMA_VERSION,
    generatedAt: genAt,
    kind: 'settings-effective',
    version,
    engine: { path: enginePath, manifestVersion: manifest.version ?? null, manifestPath },
    settings: { path: settingsPath, sha256: fs.existsSync(settingsPath) ? crypto.createHash('sha256').update(fs.readFileSync(settingsPath)).digest('hex') : null },
    consumed: { path: consumedPath, sha256: fs.existsSync(consumedPath) ? crypto.createHash('sha256').update(fs.readFileSync(consumedPath)).digest('hex') : null },
    mechanism,
    ran: false,
    ok: false,
    verdict: null,
    counts: {
      keys: 0, consumedEntries: 0, distinctKeys: 0, activeKeys: 0, inactiveKeys: 0,
      present: 0, absent: 0, different: 0, unverified: 0, BREAKS: 0, RISKY: 0, INFO: 0,
    },
    keys: [],
    findings: [],
    unverified: [],
    isolatedHome: null,
    credential: { name: credential.name, present: credential.present, length: credential.present ? credential.length : 0, source: credential.source, copiedIntoIsolatedHome: false },
    run: { port: null, pid: null, kill: null, killExitCode: null, postFree: null, bootDurationMs: null, startedAt: null, finishedAt: null, wallClockMs: null },
    // The LIVE facts of one run. Everything OUTSIDE this list is a pure function of the inputs plus
    // the engine's own answers, so a re-run under a pinned --generated-at differs in exactly these
    // fields and nowhere else; tests/settings-effective/run.mjs proves that mechanically.
    volatile: [
      'isolatedHome.path',
      'isolatedHome.copied.durationMs',
      'isolatedHome.durationMs',
      'isolatedHome.copied.linkFailures',
      'isolatedHome.copied.linkFailureDetail',
      'isolatedHome.credentialsPlaceholder.file',
      'isolatedHome.credentialsPlaceholder.bytesBeforeBoot',
      'isolatedHome.credentialsPlaceholder.bytesAfterBoot',
      'run.port',
      'run.pid',
      'run.kill',
      'run.killExitCode',
      'run.bootDurationMs',
      'run.startedAt',
      'run.finishedAt',
      'run.wallClockMs',
      'run.engineLog',
      'run.rpcEvidence',
      'run.otherWebProcessesBefore',
      'liveEngineBefore',
      'liveEngineAfter',
      'liveEngineUnchanged',
      'secretHygiene.examinedBytes',
      'notes',
    ],
    notes,
    unverifiedChecks: [],
  };

  const t0 = Date.now();
  out.run.startedAt = iso(new Date(t0));
  let bootLogPath = null;
  let rpcEvidencePath = null;

  const emit = (value) => {
    const text = `${JSON.stringify(value, null, 2)}\n`;
    const outPath = flags['--out'] ? path.resolve(flags['--out']) : null;
    if (outPath) {
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      const tmp = `${outPath}.tmp-${process.pid}`;
      fs.writeFileSync(tmp, text);
      fs.renameSync(tmp, outPath);
    }
    process.stdout.write(text);
  };

  const finish = (extraNotes = []) => {
    out.notes.push(...extraNotes);
    out.run.finishedAt = iso();
    out.run.wallClockMs = Date.now() - t0;
    out.generatedAtNote = out.generatedAt;
    const liveAfter = liveEngineReading();
    out.liveEngineBefore = liveBefore;
    out.liveEngineAfter = liveAfter;
    out.liveEngineUnchanged = Boolean(
      liveBefore.read && liveAfter.read &&
      liveBefore.listening === liveAfter.listening &&
      liveBefore.pid === liveAfter.pid,
    );
    out.notes.push(`the live engine on port ${LIVE_PORT} after this run: ${liveAfter.read ? (liveAfter.listening ? `listening, pid ${liveAfter.pid}, started ${liveAfter.created}` : 'nothing is listening') : `unreadable (${liveAfter.reason})`}; unchanged by this run: ${out.liveEngineUnchanged ? 'yes' : 'NOT CONFIRMED'}`);

    // Secret hygiene, measured rather than asserted: string-match the resolved credential against
    // every byte this run produced. Nothing here can print the value (only a count), and a NONZERO
    // count is a failure of this module, so it is reported as such rather than swallowed.
    const filesToScan = [];
    const outPathForScan = flags['--out'] ? path.resolve(flags['--out']) : null;
    if (outPathForScan) filesToScan.push(outPathForScan);
    if (bootLogPath) filesToScan.push(bootLogPath);
    if (rpcEvidencePath) filesToScan.push(rpcEvidencePath);
    const scan = { credentialLength: credential.present ? credential.length : 0, files: filesToScan.length, examinedBytes: 0, matches: 0 };
    if (credential.present) {
      for (const f of filesToScan) {
        let text = '';
        try { text = fs.readFileSync(f, 'utf8'); } catch { continue; }
        scan.examinedBytes += Buffer.byteLength(text, 'utf8');
        const occurrences = text.split(credential.value).length - 1;
        scan.matches += occurrences;
      }
    }
    // the artifact just being emitted is scanned as text, so a leak in ANY field is caught
    if (credential.present) {
      scan.matches += (JSON.stringify(out, null, 2).split(credential.value).length - 1);
    }
    out.secretHygiene = {
      ...scan,
      credentialValuePrinted: false,
      credentialsFileInIsolatedHome: fs.existsSync(path.join(out.isolatedHome?.path ?? '\u0000', '.credentials.yaml')),
      credentialsFileCarriesDeploymentKey: out.isolatedHome?.credentialsPlaceholder ? !out.isolatedHome.credentialsPlaceholder.clean : null,
      note: 'the resolved credential was matched as a literal string against the artifact, the engine log and the RPC evidence, and its NAME against the isolated-home credentials file; matches must be 0',
    };
    if (scan.matches > 0 || out.secretHygiene.credentialsFileCarriesDeploymentKey === true) {
      out.ok = false;
      out.verdict = 'BREAKS';
      out.notes.push(`SECRET LEAK DETECTED: the resolved credential appears ${scan.matches} time(s) in this run's own output${out.secretHygiene.credentialsFileCarriesDeploymentKey ? ' and the isolated home\'s credentials file carries it' : ''} — this is a bug in this module, not a finding about the engine`);
    } else {
      out.notes.push(`secret hygiene: the resolved ${credential.name} (${scan.credentialLength} characters) appears 0 times across ${scan.files} written file(s) + the artifact text (${scan.examinedBytes} bytes examined); the isolated home's own credentials file (placeholder + the engine's browser-session grant only) does not carry the key name or value`);
    }
    emit(out);
    return 0;
  };

  /* ---- inputs ---- */
  const consumed = loadConsumedKeys(consumedPath);
  const document = loadSettingsDocument(settingsPath);
  out.settings.present = fs.existsSync(settingsPath);
  out.settings.how = document.ok ? (document.how ?? null) : null;
  if (!consumed.ok) {
    out.ran = false;
    out.verdict = null;
    out.unverified.push({ check: 'consumed settingsKeys', reason: consumed.reason });
    return finish([`ran:false — ${consumed.reason}`]);
  }
  if (!document.ok) out.notes.push(`the settings document could not be read (${document.reason}); the comparison uses consumed.json's recorded values only`);
  else if (document.doc === null) out.notes.push(document.how);

  const keys = [...consumed.keys].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  out.counts.keys = keys.length;

  /* ---- port ---- */
  let port;
  try { port = await choosePort(flags['--port']); }
  catch (err) {
    out.unverified.push({ check: 'port', reason: err.message });
    return finish([`ran:false — ${err.message}`]);
  }
  if (port === null) {
    const reason = `no free port in ${PORT_RANGE[0]}-${PORT_RANGE[1]}; nothing was started`;
    out.unverified.push({ check: 'port', reason });
    return finish([`ran:false — ${reason}`]);
  }
  out.run.port = port;
  out.run.portRange = PORT_RANGE;
  out.notes.push(`port ${port} chosen from ${PORT_RANGE[0]}-${PORT_RANGE[1]} after confirming it was free; port ${LIVE_PORT} is never a candidate`);

  /* ---- credential ---- */
  if (!credential.present) {
    out.unverified.push({ check: 'credential', reason: credential.reason });
    out.notes.push(`credential DEEPSEEK_API_KEY: absent (${credential.reason})`);
    return finish([`ran:false — ${credential.reason}; the engine cannot reach a model without it and this gate will not report health it did not observe`]);
  }
  out.notes.push(`credential DEEPSEEK_API_KEY: present, ${credential.length} characters, resolved from ${credential.source}; passed in the child environment only`);

  /* ---- isolated home ----
   * The directory is FRESH PER RUN (its name carries this process's pid), and that is deliberate:
   * each engine boot writes its own state into its home (`health/`, `spend-guard/`, `storages/`, and
   * its own `.credentials.yaml` grant), and two boots sharing one home is the state-corruption shape
   * `multi-window/windows.json` already records for session logs. A fresh home costs 0.24 MB and
   * ~65 ms to copy and cannot be contaminated by a previous run's state.
   *
   * The cost is that each run abandons one temporary directory: this module can never delete
   * anything, so cleaning those up is an operator action (`%TEMP%\dsh-settings-effective-<ver>-*`),
   * and the artifact names the exact directory it used so the set is easy to enumerate.
   */
  const isolatedHome = injected.isolatedHome ?? path.join(os.tmpdir(), `dsh-settings-effective-${version}-${process.pid}`);
  const cwd = injected.cwd ?? path.join(os.tmpdir(), `dsh-settings-effective-${version}-cwd-${process.pid}`);
  let homeStats;
  try {
    fs.mkdirSync(cwd, { recursive: true });
    homeStats = buildIsolatedHome({ liveHome, home: isolatedHome, profiles: injected.profiles ?? ['web', 'headless'], logs: logsDir, settingsSrc: settingsPath });
  } catch (err) {
    out.unverified.push({ check: 'isolated home', reason: err.message });
    return finish([`ran:false — the isolated DSH_HOME could not be built: ${err.message}`]);
  }
  out.isolatedHome = {
    path: isolatedHome,
    source: liveHome,
    copied: {
      files: homeStats.files, bytes: homeStats.bytes, links: homeStats.links,
      copiedLinks: homeStats.copiedLinks, linkFailures: homeStats.linkFailures,
      linkFailureDetail: homeStats.linkFailureDetail ?? [],
    },
    measured: homeStats.measured,
    durationMs: homeStats.durationMs,
    includes: ['settings.yaml', '.agent-presets/', 'profiles/<name>/** (including each profile\'s own node_modules)'],
    excludes: ['profiles/node_modules (the shared engine tree — SPEC §C5)', 'the live .credentials.yaml: the credential travels in the child ENVIRONMENT only'],
    liveCredentialsCopied: false,
    credentialsPlaceholder: null,
    containsCredentialsFileBeforeBoot: fs.existsSync(path.join(isolatedHome, '.credentials.yaml')),
  };
  out.notes.push(...homeStats.notes);
  out.notes.push(`isolated DSH_HOME ${isolatedHome}: ${homeStats.files} files / ${homeStats.bytes} bytes / ${homeStats.links} links copied in ${homeStats.durationMs} ms; re-measured ${homeStats.measured.files} files / ${homeStats.measured.bytes} bytes`);
  if (homeStats.linkFailures > 0) {
    // Not fatal by construction — the engine fails loudly on a bundle it cannot resolve — but never
    // silent: a copy that dropped a link must be visible next to the boot it fed.
    out.notes.push(`${homeStats.linkFailures} profile link(s) could NOT be recreated into the isolated home: ${(homeStats.linkFailureDetail ?? []).join(' | ')}`.slice(0, 1200));
  }
  // The placeholder is NOT a copied credential and the log says so, because "a .credentials.yaml
  // exists in the isolated home" must never be mistaken for "the live credential was copied in".
  out.notes.push(`a placeholder .credentials.yaml is written into the isolated home before the boot (contents: "${CREDENTIALS_PLACEHOLDER.trim().replace(/\n/g, ' ')}" — no secret, and NOT the live file); measured necessity: with no such file the engine persists the environment key to disk inside that home, and with the pre-release flat layout it refuses to boot at all`);

  /* ---- boot and read back ---- */
  const boot = await bootAndRead({ enginePath, home: isolatedHome, cwd, port, credential, logsDir, version, timeoutMs, label: 'candidate' });
  bootLogPath = boot.engineLog;
  out.isolatedHome.credentialsPlaceholder = boot.credentialsAudit ?? null;
  if (boot.credentialsAudit) {
    out.notes.push(boot.credentialsAudit.clean
      ? `isolated home credentials file after the boot: ${boot.credentialsAudit.bytesBeforeBoot} -> ${boot.credentialsAudit.bytesAfterBoot} bytes; the deployment key name appears ${boot.credentialsAudit.deploymentKeyNamesPresent.length} time(s) and its value ${boot.credentialsAudit.deploymentKeyValueOccurrences} time(s); keys the engine wrote: ${boot.credentialsAudit.keysWrittenByTheEngine.join(', ') || '(none)'}`
      : `CREDENTIALS FILE IN THE ISOLATED HOME CARRIES THE DEPLOYMENT KEY: name present ${JSON.stringify(boot.credentialsAudit.deploymentKeyNamesPresent)}, value occurrences ${boot.credentialsAudit.deploymentKeyValueOccurrences} — this is a failure of this module, not a finding about the engine`);
  }
  out.run.pid = boot.pid;
  out.run.kill = boot.kill;
  out.run.killExitCode = boot.killExitCode;
  out.run.bootDurationMs = boot.bootDurationMs;
  out.run.postFree = boot.postFree;
  out.run.portFreeAfter = boot.postFree;
  out.run.tokenFromEngineStdout = boot.tokenPresent;
  out.run.cookieExchanged = boot.cookiePresent;
  out.run.httpStatus = boot.httpStatus;
  out.run.engineLog = path.relative(ROOT, boot.engineLog).split(path.sep).join('/');
  out.run.otherWebProcessesBefore = boot.otherWebProcesses?.checked
    ? (boot.otherWebProcesses.matched.length === 0 ? [] : boot.otherWebProcesses.matched.map((m) => `pid ${m.pid}: ${m.cmd}`))
    : [`CHECK FAILED: ${boot.otherWebProcesses?.reason ?? 'unknown'}`];

  if (boot.raw) {
    out.run.rpcEvidence = boot.rpcEvidence ? path.relative(ROOT, boot.rpcEvidence).split(path.sep).join('/') : null;
    rpcEvidencePath = boot.rpcEvidence ?? null;
    out.notes.push('evidence written: the engine log and the raw RPC response, both under state/logs/ (string-matched for the secret, and the launch token removed before the file was written)');
  }

  if (boot.failure !== null || boot.namespaces === null) {
    out.unverifiedChecks.push({ check: 'boot + settings readback', reason: boot.failure ?? 'the settings controller returned no namespaces' });
    out.unverified.push({ check: 'effective settings', reason: boot.failure ?? 'no namespaces were returned' });
    out.ran = false;
    out.verdict = null;
    out.notes.push(`ran:false — ${boot.failure ?? 'the readback produced no namespaces'}`);
    return finish();
  }

  /* ---- compare ---- */
  const byNs = new Map();
  for (const ns of boot.namespaces) byNs.set(ns.ns, ns);
  const registered = [...byNs.keys()].sort();
  out.run.namespaceCount = registered.length;
  out.run.namespaces = registered;

  const rows = [];
  const findings = [];
  const unverified = [];
  let findingsSeq = 0;
  let findingsInfo = 0;

  /*
   * KEY SET, AND WHY THIS IS NOT JUST `consumed.settingsKeys` VERBATIM.
   *
   * `consumed.json` records a settings key once per FILE that sets it, and this deployment's config
   * tree holds a machine's own document plus per-machine overlays, so the same key appears up to
   * seven times, with values that differ BETWEEN machines (measured here: `agent-presets.default` is
   * `zabz` in settings.yaml and `yocheved` in a sibling machine's overlay; `llm-pi-ai` names three
   * providers across the tree while the live document carries one). Checking those verbatim would
   * invent findings for values this machine never set — the false-positive class SPEC §C13 records
   * as the most expensive failure in this system's history.
   *
   * So the AUTHORITY for "what this deployment set" is the live merged document that is actually
   * booted (`--settings`), the same file the isolated home is built from, and each key is checked
   * ONCE. Entries from other files are kept as `sources` for provenance and a key that exists only
   * there is reported as out-of-scope for this machine rather than as a loss. When the document
   * cannot be parsed, the comparison falls back to the consumed.json values and says so.
   */
  const livePathNames = new Set(['settings.yaml', 'settings.yml']);
  const byKey = new Map();
  for (const entry of keys) {
    const base = entry.file ? path.basename(String(entry.file)) : '';
    const isLive = livePathNames.has(base) || (entry.file && path.resolve(String(entry.file)) === settingsPath);
    let group = byKey.get(entry.key);
    if (group === undefined) {
      group = { key: entry.key, consumedValues: [], sources: [], liveValues: [] };
      byKey.set(entry.key, group);
    }
    const dup = group.sources.some((s) => s.file === entry.file && s.line === entry.line);
    if (!dup) group.sources.push({ file: entry.file, line: entry.line, value: entry.value });
    if (isLive) group.liveValues.push(entry.value);
    if (!group.consumedValues.includes(entry.value)) group.consumedValues.push(entry.value);
  }
  const groups = [...byKey.values()].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

  const inDocument = new Map();          // key -> array of {value, remaining}
  if (document.doc !== null) {
    for (const g of groups) {
      const hits = walkAll(document.doc, g.key.split('.').filter((s) => s !== ''));
      if (hits.length > 0) inDocument.set(g.key, hits);
    }
  }
  const documentUsable = document.doc !== null;
  const active = [];
  const inactive = [];
  for (const g of groups) {
    if (documentUsable) {
      const hits = inDocument.get(g.key);
      if (hits && hits.length > 0) { g.document = hits[0]; g.scope = 'exact'; active.push(g); continue; }
      /*
       * The key is not spelled in the document. Two very different situations look identical from
       * here, and conflating them is the false-positive class this pipeline has already paid for:
       *
       *   `llm-pi-ai.providers.deepseek-proxy.baseURL`  — the PARENT path is absent from the
       *       document too, so this key is set by another machine's or another layer's file. It is
       *       not part of what this machine boots and asserting it would invent a loss.
       *   `permission.defaultPreset` with the document carrying `defaultPresetWeRenamed` — the
       *       PARENT (`permission`) IS in the document, and consumed.json says this deployment sets
       *       this key. The key is in scope and the engine must be asked about it.
       *
       * So the test is the PARENT path, not the leaf: an in-scope namespace whose leaf the document
       * does not set is exactly the silent-loss shape, and it gets asserted like any other key.
       */
      const parent = walkAll(document.doc, segmentsOf(g.key).slice(0, -1));
      const nsPresent = walkAll(document.doc, [segmentsOf(g.key)[0]]);
      if (parent.length > 0 || (segmentsOf(g.key).length === 1 && nsPresent.length > 0)) {
        g.document = { value: g.liveValues.length > 0 ? g.liveValues[0] : g.consumedValues[0], remaining: [] };
        g.scope = 'parent-in-document';
        active.push(g);
        continue;
      }
      inactive.push(g);
    } else if (g.liveValues.length > 0) {
      g.document = { value: g.liveValues[0], remaining: [] };
      g.scope = 'live-value-from-consumed';
      active.push(g);
    } else {
      // no usable document: assert only the values the live settings file itself recorded
      g.document = null;
      g.scope = 'unknown';
      inactive.push(g);
    }
  }
  out.counts.consumedEntries = consumed.keys.length;
  out.counts.distinctKeys = groups.length;
  out.counts.activeKeys = active.length;
  out.counts.inactiveKeys = inactive.length;
  out.counts.assertedFromParentScope = active.filter((g) => g.scope === 'parent-in-document').length;
  if (inactive.length > 0) {
    out.notes.push(`${inactive.length} key(s) recorded in consumed.json are NOT in the document under test (${settingsPath}) and have no parent path there either, so this run cannot assert them: ${documentUsable ? 'they belong to another machine\'s or another layer\'s file, and asserting them would report a loss for a value this machine is not running with' : 'the document could not be parsed'}`);
  }
  if (out.counts.assertedFromParentScope > 0) out.notes.push(`${out.counts.assertedFromParentScope} key(s) are in scope but not spelled in the document — the document's own section carries the parent, consumed.json says this deployment sets the key, so the engine is asked about it and an absence is reported as a loss`);
  if (!documentUsable) out.notes.push(`the document under test could not be parsed, so the comparison fell back to the values consumed.json recorded for the live document; ${inactive.length} key(s) with no such value were not asserted`);

  for (const g of groups) {
    const segments = segmentsOf(g.key);
    const ns = segments[0];
    const rest = segments.slice(1);
    const descriptor = byNs.get(ns);
    const isActive = active.includes(g);
    const expected = isActive ? g.document.value : (g.liveValues.length > 0 ? g.liveValues[0] : g.consumedValues[0]);
    const expectedFrom = isActive
      ? (g.scope === 'parent-in-document'
        ? `consumed.json's recorded value for this key (the document under test sets its namespace and parent path but not this leaf, so the key is asserted against the value consumed.json says this deployment sets)`
        : `the document under test (${path.basename(settingsPath)})`)
      : 'consumed.json';

    const row = {
      key: g.key,
      namespace: ns,
      path: rest.join('.'),
      consumedValues: g.consumedValues,
      expected,
      expectedType: typeOf(expected),
      expectedFrom,
      scope: g.scope ?? null,
      sources: g.sources,
      documentValue: g.document ? g.document.value : null,
      documentHas: Boolean(g.document),
      status: 'unverified',
      actual: null,
      actualType: null,
      namespaceRegistered: descriptor !== undefined,
      userLayerHas: null,
      note: null,
    };

    if (!isActive) {
      row.status = 'unverified';
      row.note = `consumed.json records this key with ${g.sources.length} location(s) outside the document that was booted (${[...new Set(g.sources.map((s) => path.basename(String(s.file))))].join(', ')}); this run cannot assert a key the loaded document does not set, and reporting it would be a claim about a value this machine is not running with`;
      unverified.push({ key: g.key, kind: 'not-in-document-under-test', namespace: ns, reason: row.note, sources: g.sources });
      // An INFO finding, not a BREAKS: this is the one deliberate non-assertion in the gate, and
      // leaving it out of `findings` entirely would hide which keys were excluded from the check.
      findings.push({
        id: `I${String(++findingsInfo).padStart(3, '0')}`,
        class: CLASS,
        severity: 'INFO',
        subject: g.key,
        evidence: `consumed.json records this key at ${g.sources.length} location(s): ${g.sources.map((s) => `${s.file}:${s.line}`).join(', ')}; the booted document ${settingsPath} does not set it`,
        evidenceTier: 'AUTHORITATIVE',
        consumers: g.sources.filter((s) => s && s.file).map((s) => ({ file: s.file, line: s.line })),
        why: 'this key belongs to another layer or another machine\'s document, so it is not part of what THIS machine boots; asserting it here would report a loss for a value this deployment is not running with',
        suggested: 'nothing, unless this key should be active on this machine — in which case it belongs in the document that was booted, and the gate will then assert it',
      });
      rows.push(row);
      continue;
    }

    if (descriptor === undefined) {
      row.status = 'unverified';
      row.note = `the engine registered no settings namespace "${ns}" at all in this boot, so nothing could have read this key`;
      unverified.push({ key: g.key, kind: 'namespace-not-registered', namespace: ns, reason: row.note, sources: g.sources });
      rows.push(row);
      continue;
    }

    const hits = rest.length === 0 ? [{ value: descriptor.value, remaining: [] }] : walkAll(descriptor.value, rest);
    if (hits.length === 0 || hits.every((h) => h.value === undefined)) {
      row.status = 'absent';
      const userHits = descriptor.user === undefined ? [] : (rest.length === 0 ? [{ value: descriptor.user, remaining: [] }] : walkAll(descriptor.user, rest));
      row.userLayerHas = userHits.length > 0;
      row.note = userHits.length > 0
        ? `the stored "${ns}" section still carries this key, but it is NOT in the engine's resolved value — the engine dropped it`
        : `the key is absent from the engine's resolved value for "${ns}"`;
      const f = finding({
        seq: ++findingsSeq,
        key: g.key,
        expected,
        actual: null,
        actualLabel: '(absent from the engine\'s resolved settings)',
        descriptor,
        row,
        sources: g.sources,
        why: `the settings namespace "${ns}" is registered in this boot but the engine's resolved value does not carry "${rest.join('.') || '(the section root)'}", so the key this deployment sets is being silently discarded — the value reverts to a schema default or to undefined with no error anywhere (SPEC §C2)`,
      });
      findings.push(f);
      rows.push(row);
      continue;
    }

    // prefer the hit that equals our value; a repeated entry (models[]) may have several
    const equal = hits.find((h) => equalJson(h.value, expected));
    const chosen = equal ?? hits[0];
    row.actual = chosen.value;
    row.actualType = typeOf(chosen.value);
    row.actualPath = [ns, ...rest.slice(0, rest.length - chosen.remaining.length)].join('.');
    const userHits = descriptor.user === undefined ? [] : (rest.length === 0 ? [{ value: descriptor.user, remaining: [] }] : walkAll(descriptor.user, rest));
    row.userLayerHas = userHits.length > 0;

    if (equal) {
      row.status = 'present';
      rows.push(row);
      continue;
    }

    row.status = 'present-with-a-different-value';
    const normalisation = proveNormalisation({ descriptor, rest, expected, actual: chosen.value });
    row.note = normalisation
      ? `the difference is a documented normalisation, not a loss: ${normalisation}`
      : `the engine's resolved value for this path is not the value this deployment sets`;
    const f = finding({
      seq: ++findingsSeq,
      key: g.key,
      expected,
      actual: chosen.value,
      actualLabel: describeValue(chosen.value),
      descriptor,
      row,
      sources: g.sources,
      why: normalisation
        ? `the engine reports a different value than the document sets, and the difference is accounted for by the namespace's own schema at this path: ${normalisation}`
        : `the engine resolved a different value for a key this deployment sets, so the document's value is not the one in force — either the key is no longer honoured at that path or a schema default/another layer now wins (SPEC §C2)`,
      severity: normalisation ? 'RISKY' : 'BREAKS',
    });
    findings.push(f);
    rows.push(row);
  }

  rows.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  findings.sort((a, b) => (a.subject < b.subject ? -1 : a.subject > b.subject ? 1 : 0));

  out.keys = rows;
  out.findings = findings;
  out.unverified = unverified.slice().sort((a, b) => (String(a.key) < String(b.key) ? -1 : 1));
  out.counts.present = rows.filter((r) => r.status === 'present').length;
  out.counts.absent = rows.filter((r) => r.status === 'absent').length;
  out.counts.different = rows.filter((r) => r.status === 'present-with-a-different-value').length;
  out.counts.unverified = rows.filter((r) => r.status === 'unverified').length;
  out.counts.BREAKS = findings.filter((f) => f.severity === 'BREAKS').length;
  out.counts.RISKY = findings.filter((f) => f.severity === 'RISKY').length;
  out.counts.INFO = findings.filter((f) => f.severity === 'INFO').length;
  out.counts.namespacesRegistered = registered.length;
  out.counts.namespacesOurs = new Set(rows.map((r) => r.namespace)).size;

  out.ran = true;
  // A difference that is only a documented normalisation is RISKY, not BREAKS; an unverifiable key is
  // RISKY because the gate cannot vouch for it. Only a real absence or a real difference is BREAKS.
  const asserted = out.counts.absent + out.counts.different + out.counts.present;
  out.verdict = out.counts.BREAKS > 0 ? 'BREAKS' : (out.counts.RISKY > 0 || out.counts.unverified > 0) ? 'RISKY' : 'SAFE';
  // a gate that ran but could not check a key is not a pass, and a gate that did not run never is
  out.ok = out.ran && out.counts.BREAKS === 0 && out.counts.unverified === 0 && asserted > 0;
  if (!out.ok && out.counts.BREAKS === 0) {
    out.notes.push(`ok is false without a BREAKS finding because ${out.counts.unverified} key(s) could not be asserted for this machine${asserted === 0 ? ' and no key at all was asserted' : ''}; a partially checked gate must never read as a pass`);
  }

  out.notes.push(`asserted ${asserted} of ${out.counts.distinctKeys} distinct key(s) (${out.counts.consumedEntries} consumed.json entries) against the engine's own report: ${out.counts.present} present with our value, ${out.counts.absent} absent (S1), ${out.counts.different} present with a different value, ${out.counts.unverified} not assertable for this machine`);
  out.notes.push(`the engine registered ${registered.length} settings namespaces in this boot, ${out.counts.namespacesOurs} of which this deployment's active keys name`);

  /* ---- opt-in baseline: was this namespace EVER registered here? ---- */
  if (flags['--baseline-engine']) {
    const basePath = path.resolve(flags['--baseline-engine']);
    if (!fs.existsSync(basePath)) {
      out.unverifiedChecks.push({ check: 'baseline boot', reason: `--baseline-engine "${basePath}" does not exist` });
    } else {
      let basePort = null;
      for (let p = PORT_RANGE[0]; p <= PORT_RANGE[1]; p++) {
        if (p === LIVE_PORT) continue;
        if (await portFree(p)) { basePort = p; break; }
      }
      if (basePort === null) {
        out.unverifiedChecks.push({ check: 'baseline boot', reason: `no second free port in ${PORT_RANGE[0]}-${PORT_RANGE[1]}` });
      } else {
        const baseManifest = readJsonIfPresent(path.resolve(path.dirname(basePath), '..', 'package.json')) ?? {};
        const baseBoot = await bootAndRead({
          enginePath: basePath, home: isolatedHome, cwd, port: basePort, credential, logsDir,
          version, timeoutMs, label: 'baseline',
        });
        out.baseline = {
          engine: basePath,
          manifestVersion: baseManifest.version ?? null,
          port: basePort,
          pid: baseBoot.pid,
          kill: baseBoot.kill,
          bootDurationMs: baseBoot.bootDurationMs,
          ran: baseBoot.namespaces !== null,
          reason: baseBoot.failure,
          namespaces: baseBoot.namespaces === null ? [] : baseBoot.namespaces.map((n) => n.ns).sort(),
        };
        if (baseBoot.namespaces !== null) {
          const baseNames = new Set(out.baseline.namespaces);
          const baseByNs = new Map(baseBoot.namespaces.map((n) => [n.ns, n]));
          for (const row of out.keys) {
            if (row.status !== 'unverified') continue;
            const baseDesc = baseByNs.get(row.namespace);
            if (baseDesc === undefined) {
              row.note = `${row.note}; the CURRENT engine (${baseManifest.version ?? '?'}) registers no settings namespace "${row.namespace}" either, so this key is not newly lost by the candidate — it was never consumed by this namespace`;
              row.baselineNamespaceRegistered = false;
            } else {
              row.note = `${row.note}; but the CURRENT engine (${baseManifest.version ?? '?'}) does register "${row.namespace}" — so the candidate LOSING it is a regression, not a pre-existing gap`;
              row.baselineNamespaceRegistered = true;
            }
          }
          out.notes.push(`baseline boot: the current engine registered ${out.baseline.namespaces.length} namespaces on port ${basePort} (pid ${baseBoot.pid}, killed: ${baseBoot.kill}); ${[...new Set(rows.map((r) => r.namespace))].filter((n) => !baseNames.has(n) && !registered.includes(n)).length || 0} namespace(s) named by our keys are absent from BOTH engines`);
        } else {
          out.unverifiedChecks.push({ check: 'baseline boot', reason: baseBoot.failure });
        }
      }
    }
  }

  return finish();
}

function finding({ seq, key, expected, actual, actualLabel, descriptor, row, sources, why, severity = 'BREAKS' }) {
  return {
    id: `S${String(seq).padStart(3, '0')}`,
    class: CLASS,
    severity,
    subject: key,
    evidence: `engine's own settings report (POST /api/settings/describe): the document sets ${key} = ${describeValue(expected)}; the namespace "${descriptor.ns}" resolved ${row.path || '(section root)'} to ${actualLabel}${descriptor.user === undefined ? ' (the namespace carries no user layer at all)' : ''}`,
    evidenceTier: 'AUTHORITATIVE',
    consumers: (sources ?? (row.sources ?? [])).filter((s) => s && s.file).map((s) => ({ file: s.file, line: s.line })),
    why,
    suggested: severity === 'BREAKS'
      ? 'find the key in the candidate\'s version of the plugin that owns this settings namespace (its schema is what drops an unrecognised key) and either move the value to the path the candidate now uses or delete the key from settings/*.yaml so the loss is deliberate instead of silent'
      : 'confirm the normalisation is intended; if it is not, treat it as a lost key',
  };
}

/**
 * Decide whether a value difference is a documented normalisation. The only case this claims is the
 * one the namespace's OWN SCHEMA proves: the resolved value's type at that path is not the type the
 * document wrote, and the schema declares a different (non-string) type there — a schema-driven
 * coercion, not a loss. Anything else is reported as a plain difference rather than explained away.
 */
function proveNormalisation({ descriptor, rest, expected, actual }) {
  if (equalJson(expected, actual)) return null;
  let node = descriptor.schema;
  for (const seg of rest) {
    if (node === undefined || node === null) return null;
    const name = seg.replace(/\[\]$/, '');
    const props = node.dict ?? node.properties ?? node.inner ?? null;
    if (props !== null && typeof props === 'object' && name in props) node = props[name];
    else if (node.type === 'dict' && node.inner) node = node.inner;
    else return null;
  }
  const declared = node?.type ?? null;
  const expectedType = typeOf(expected);
  const actualType = typeOf(actual);
  if (declared === null) return null;
  if (expectedType === actualType) return null;
  const numericTargets = new Set(['number', 'natural', 'percent', 'float']);
  if (numericTargets.has(declared) && expectedType === 'string' && actualType === 'number' && Number.isFinite(Number(expected))) {
    return `the schema declares a ${declared} at this path, and the engine coerced the document's string ${JSON.stringify(expected)} to the number ${String(actual)}`;
  }
  if (declared === 'boolean' && expectedType === 'string' && actualType === 'boolean') {
    return `the schema declares a boolean at this path, and the engine coerced ${JSON.stringify(expected)} to ${String(actual)}`;
  }
  if (declared === 'array' && expectedType !== 'array' && actualType === 'array') {
    return `the schema declares an array at this path and the engine wrapped the document's scalar`;
  }
  return null;
}

/* =================================================================== standalone */

const invokedDirectly = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (invokedDirectly) {
  main().then((code) => { process.exitCode = code; }).catch((err) => {
    process.stderr.write(`settings-effective: unexpected failure: ${err?.stack ?? err}\n`);
    process.exitCode = 1;
  });
}

export {
  main,
  parseArgs,
  generatedAt,
  buildIsolatedHome,
  resolveCredential,
  choosePort,
  portFree,
  loadConsumedKeys,
  defaultConsumedPath,
  leafPaths,
  setAt,
  parseSimpleYaml,
  walkPath,
  walkAll,
  canonical,
  equalJson,
  describeValue,
  proveNormalisation,
  extractLaunchUrl,
  redactToken,
  ROOT,
  DEFAULT_LOGS,
  PORT_RANGE,
};
