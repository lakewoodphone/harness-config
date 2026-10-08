// versions.mjs — registry queries, version precedence, candidate fetch, installed-engine detection.
//
// Owns exactly three things: how versions are DISCOVERED, how they are ORDERED, and how a candidate
// is FETCHED into a managed prefix. It never installs into the npx cache, never touches the live
// install, and never starts or stops an engine: the only engine invocations here are
// `--version` / `--help`, both read-only.
//
// Standalone: `node lib/versions.mjs --selftest` runs the precedence self-test (exit non-zero on any
// wrong pair); `node lib/versions.mjs --json` prints the discovered version picture.

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  PATHS, assertSafeVersion, ensureDir, readJson, sha256File, vendorPrefixPath, windowsJsonPath,
} from './store.mjs';

const PKG = '@deepseek-ai/dsh';
export const ENGINE_REL = path.join('node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');

// ── version precedence ──────────────────────────────────────────────────────

/**
 * Parse a version into semver precedence parts. Returns null when the string is not a version we
 * can reason about — an unparseable version is reported as such, never silently ordered.
 */
export function parseVersion(input) {
  const raw = String(input ?? '').trim();
  const m = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$/.exec(raw);
  if (!m) return null;
  const numeric = (s) => (/^\d+$/.test(s) ? Number(s) : null);
  return {
    raw, major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]),
    prerelease: m[4] ? m[4].split('.') : [],
    build: m[5] || null,
    numeric,
  };
}

function compareIdentifier(a, b) {
  const na = /^\d+$/.test(a) ? Number(a) : null;
  const nb = /^\d+$/.test(b) ? Number(b) : null;
  if (na !== null && nb !== null) return na === nb ? 0 : (na < nb ? -1 : 1);
  // numeric identifiers always have lower precedence than alphanumeric ones (semver §11.4.3)
  if (na !== null) return -1;
  if (nb !== null) return 1;
  // otherwise compare as ordinary identifiers, ASCII lexical: alpha < beta < rc
  return a === b ? 0 : (a < b ? -1 : 1);
}

/**
 * Semver precedence. Returns -1 / 0 / 1.
 * A prerelease is lower than its release (0.1.5-rc.3 < 0.1.5). Numeric identifiers compare
 * numerically, alphanumeric ones lexically, and `rc` vs `alpha` are ordinary identifiers.
 * Unparseable input falls back to a locale-independent string compare and never throws.
 */
export function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  if (!pa || !pb) {
    const sa = String(a ?? ''); const sb = String(b ?? '');
    return sa === sb ? 0 : (sa < sb ? -1 : 1);
  }
  for (const k of ['major', 'minor', 'patch']) {
    if (pa[k] !== pb[k]) return pa[k] < pb[k] ? -1 : 1;
  }
  const aPre = pa.prerelease; const bPre = pb.prerelease;
  if (aPre.length === 0 && bPre.length === 0) return 0;
  if (aPre.length === 0) return 1;   // release > prerelease
  if (bPre.length === 0) return -1;
  const n = Math.min(aPre.length, bPre.length);
  for (let i = 0; i < n; i += 1) {
    const c = compareIdentifier(aPre[i], bPre[i]);
    if (c !== 0) return c;
  }
  if (aPre.length === bPre.length) return 0;
  return aPre.length < bPre.length ? -1 : 1;   // fewer fields = lower precedence
}

export function isNewer(a, b) { return compareVersions(a, b) > 0; }

/** Published versions strictly greater than `version`, ascending (unparseable/duplicate input dropped). */
export function newerThan(version, list) {
  const seen = new Set();
  const out = [];
  for (const v of Array.isArray(list) ? list : []) {
    if (typeof v !== 'string' || seen.has(v)) continue;
    seen.add(v);
    if (compareVersions(v, version) > 0) out.push(v);
  }
  return out.sort(compareVersions);
}

/**
 * Classify a candidate against what we run now.
 *   UPGRADE          different major.minor.patch and newer
 *   SAME_LINE_NEWER  same major.minor.patch, newer prerelease
 *   SAME             identical version
 *   DOWNGRADE        older than the pin
 * `distance` is how many published versions away (ascending distance, always >= 0),
 * `newerThanPin` is whether the candidate is strictly newer than the pin.
 */
export function classify(current, candidate, published = []) {
  const cmp = compareVersions(candidate, current);
  const pc = parseVersion(current);
  const pk = parseVersion(candidate);
  let classification;
  if (cmp === 0) classification = 'SAME';
  else if (cmp < 0) classification = 'DOWNGRADE';
  else if (pc && pk && pc.major === pk.major && pc.minor === pk.minor && pc.patch === pk.patch) classification = 'SAME_LINE_NEWER';
  else classification = 'UPGRADE';

  let distance = null;
  if (Array.isArray(published) && published.length) {
    const index = published.indexOf(candidate);
    const currentIndex = published.indexOf(current);
    if (index >= 0 && currentIndex >= 0) distance = Math.abs(index - currentIndex);
    else distance = newerThan(current, published).length + newerThan(candidate, published).length;
  }
  return { classification, distance, newerThanPin: cmp > 0, compare: cmp };
}

// ── registry ────────────────────────────────────────────────────────────────

const NPM_TIMEOUT_MS = Number(process.env.DSH_UPDATE_NPM_TIMEOUT_MS || 90000);

function npmBin() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm';
}

/**
 * npm.cmd is a batch file, and spawning a .cmd from Node 18.20+ without a shell fails outright
 * (measured here 2026-09-23: `spawnSync npm.cmd EINVAL`). We need a shell on Windows — but not an
 * implicit one, because Node 22+ deprecates passing an args array to `shell: true` and it is being
 * removed. So we build the ONE command line ourselves with cmd.exe's own quoting rules and pass it
 * as a single string. Windows-only; POSIX keeps the plain argv path.
 */
function quoteForCmd(s) {
  const str = String(s);
  if (str.length && !/[\s"^&|<>()%!]/.test(str)) return str;
  return `"${str.replace(/%/g, '%%').replace(/"/g, '""')}"`;
}

function npmCommandLine(argv) {
  if (process.platform !== 'win32') return { file: npmBin(), args: argv };
  const comspec = process.env.ComSpec || process.env.COMSPEC || 'cmd.exe';
  return { file: comspec, args: ['/d', '/s', '/c', [npmBin(), ...argv.map(quoteForCmd)].join(' ')] };
}

/**
 * Run `npm view <PKG> <field> --json`. Never throws: a failure is a structured object with the
 * real diagnostic, the elapsed time, and `ok:false`. An empty result is a FAILURE, not "no
 * versions" (invariant 8).
 */
function npmViewSync(field) {
  const started = Date.now();
  const argv = ['view', PKG, field, '--json'];
  let res;
  try {
    const cmd = npmCommandLine(argv);
    res = spawnSync(cmd.file, cmd.args, {
      encoding: 'utf8', timeout: NPM_TIMEOUT_MS, maxBuffer: 32 * 1024 * 1024, windowsHide: true,
    });
  } catch (err) {
    return { ok: false, field, argv: ['npm', ...argv], durationMs: Date.now() - started, error: `could not spawn npm: ${err.message}`, raw: null, value: null };
  }
  const durationMs = Date.now() - started;
  const stdout = res.stdout || '';
  const stderr = res.stderr || '';
  if (res.error) {
    return { ok: false, field, argv: ['npm', ...argv], durationMs, error: `npm did not complete: ${res.error.message}`, status: res.status, stderr: stderr.slice(0, 4000), raw: stdout.slice(0, 4000), value: null };
  }
  if (res.status !== 0) {
    return { ok: false, field, argv: ['npm', ...argv], durationMs, error: `npm exited ${res.status}: ${(stderr.trim() || '<no stderr>').slice(0, 1000)}`, status: res.status, stderr: stderr.slice(0, 4000), raw: stdout.slice(0, 4000), value: null };
  }
  const text = stdout.trim();
  if (!text) {
    return { ok: false, field, argv: ['npm', ...argv], durationMs, error: 'npm printed nothing — treating an empty registry read as a failure, not as "no versions"', status: 0, stderr: stderr.slice(0, 4000), raw: '', value: null };
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch (err) {
    return { ok: false, field, argv: ['npm', ...argv], durationMs, error: `npm output is not JSON: ${err.message}`, status: 0, raw: text.slice(0, 4000), value: null };
  }
  if (value === null || (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0)) {
    return { ok: false, field, argv: ['npm', ...argv], durationMs, error: 'npm returned an empty document — reported as a failure', status: 0, raw: text.slice(0, 4000), value: null };
  }
  return { ok: true, field, argv: ['npm', ...argv], durationMs, error: null, status: 0, stderr: stderr.slice(0, 4000), raw: text, value };
}

export function npmDistTags() {
  const r = npmViewSync('dist-tags');
  if (!r.ok) return r;
  if (typeof r.value !== 'object' || Array.isArray(r.value)) {
    return { ...r, ok: false, value: null, error: `dist-tags was not an object: ${JSON.stringify(r.value).slice(0, 200)}` };
  }
  return { ...r, tags: r.value, latest: r.value.latest ?? null };
}

export function npmVersions() {
  const r = npmViewSync('versions');
  if (!r.ok) return r;
  const list = Array.isArray(r.value) ? r.value.filter((v) => typeof v === 'string') : [];
  if (!list.length) return { ...r, ok: false, value: null, versions: [], error: `npm returned ${Array.isArray(r.value) ? 0 : typeof r.value} versions — reported as a failure` };
  return { ...r, versions: [...new Set(list)].sort(compareVersions), count: new Set(list).size };
}

/** A recorded source for a reading, so no number in an artifact is unsourced. */
export function registryPicture() {
  const tags = npmDistTags();
  const versions = npmVersions();
  return {
    pkg: PKG,
    queriedAt: new Date().toISOString(),
    distTags: tags.ok
      ? { ok: true, latest: tags.latest, tags: tags.tags, durationMs: tags.durationMs, source: `npm view ${PKG} dist-tags --json` }
      : { ok: false, error: tags.error, durationMs: tags.durationMs, source: `npm view ${PKG} dist-tags --json` },
    versions: versions.ok
      ? { ok: true, count: versions.count, list: versions.versions, durationMs: versions.durationMs, source: `npm view ${PKG} versions --json` }
      : { ok: false, error: versions.error, durationMs: versions.durationMs, source: `npm view ${PKG} versions --json`, list: [] },
  };
}

// ── the live engine ─────────────────────────────────────────────────────────

function npxInstallRoots() {
  const npx = path.join(process.env.LOCALAPPDATA || '', 'npm-cache', '_npx');
  const roots = [];
  try {
    for (const entry of fs.readdirSync(npx, { withFileTypes: true })) {
      if (entry.isDirectory()) roots.push(path.join(npx, entry.name));
    }
  } catch { /* an unreadable npx cache is simply no candidates, reported below */ }
  return roots;
}

/** Find `...\@deepseek-ai\dsh\lib\bin.js` in a process command line. Read-only, bounded output. */
function enginePathFromRunningProcess() {
  if (process.platform !== 'win32') {
    return { paths: [], error: 'process command lines can only be read on win32; this host has no reader installed', durationMs: 0 };
  }
  // Everything the probe can return is TEXT from a command line, and CommandLine is unquoted text:
  // the probe's own command line (and the search pattern typed elsewhere) contains the string
  // `@deepseek-ai/dsh/lib/bin.js`. Observed 2026-09-23: the same probe, run through this harness,
  // returned the search pattern and PowerShell's own command line beside the real engine path. So a
  // token is accepted only when it is an ABSOLUTE path that EXISTS on disk and ends in bin.js.
  const script = [
    "$ErrorActionPreference='SilentlyContinue';",
    "foreach ($p in (Get-CimInstance Win32_Process -Filter \"Name='node.exe'\")) {",
    "  $cl = $p.CommandLine; if (-not $cl) { continue }",
    "  $m = [regex]::Matches($cl, '[A-Za-z]:[\\\\/][^\\s\"]*?[\\\\/]lib[\\\\/]bin\\.js');",
    "  foreach ($x in $m) { $x.Value }",
    "}",
  ].join(' ');
  const started = Date.now();
  const candidates = [];
  try {
    const res = spawnSync('pwsh', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script], {
      encoding: 'utf8', timeout: 45000, windowsHide: true, maxBuffer: 4 * 1024 * 1024,
    });
    if (res.error) return { paths: [], error: `could not enumerate processes: ${res.error.message}`, durationMs: Date.now() - started };
    for (const line of (res.stdout || '').split(/\r?\n/)) {
      const token = line.trim().replace(/^["']|["']$/g, '');
      if (!token) continue;
      const lower = token.toLowerCase();
      if (!lower.endsWith('bin.js') || !lower.includes(`${path.sep}@deepseek-ai${path.sep}dsh${path.sep}lib${path.sep}`)) continue;
      if (!path.isAbsolute(token)) continue;
      if (!fs.existsSync(token)) continue;      // the pattern string and our own probe are not files
      candidates.push(path.resolve(token));
    }
    const note = res.status !== 0 ? `pwsh exited ${res.status} while enumerating processes; falling back to the configured/known paths` : null;
    return { paths: [...new Set(candidates)], error: note, durationMs: Date.now() - started };
  } catch (err) {
    return { paths: [], error: `could not enumerate processes: ${err.message}`, durationMs: Date.now() - started };
  }
}

/** `node <bin.js> --version` — the only way a version is ever determined. Read-only. */
export function engineVersion(enginePath, { timeoutMs = 60000 } = {}) {
  const started = Date.now();
  if (!enginePath || !fs.existsSync(enginePath)) {
    return { ok: false, error: `engine binary not found at ${enginePath || '<none>'}`, version: null, durationMs: 0, command: null };
  }
  const command = `node ${enginePath} --version`;
  const res = spawnSync(process.execPath, [enginePath, '--version'], {
    encoding: 'utf8', timeout: timeoutMs, windowsHide: true, maxBuffer: 4 * 1024 * 1024,
  });
  const durationMs = Date.now() - started;
  if (res.error) return { ok: false, error: `could not run the engine: ${res.error.message}`, version: null, durationMs, command, stderr: (res.stderr || '').slice(0, 2000) };
  const stdout = (res.stdout || '').trim();
  const stderr = (res.stderr || '').trim();
  if (res.status !== 0) return { ok: false, error: `engine --version exited ${res.status}`, version: null, durationMs, command, stdout: stdout.slice(0, 2000), stderr: stderr.slice(0, 2000) };
  const m = /(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)/.exec(stdout);
  if (!m) return { ok: false, error: `engine --version printed no version: ${JSON.stringify(stdout.slice(0, 200))}`, version: null, durationMs, command, stdout: stdout.slice(0, 2000), stderr: stderr.slice(0, 2000) };
  return { ok: true, version: m[1], raw: stdout, durationMs, command, stderr: stderr.slice(0, 2000) };
}

/** The `dshInstall` knob from windows.json, read the same way the launcher's Get-ConfigValue does. */
export function configuredInstallRoot() {
  const env = process.env.DSH_INSTALL;
  if (env && String(env).trim()) {
    return { value: path.resolve(String(env).trim()), source: '$env:DSH_INSTALL', configPath: windowsJsonPath() };
  }
  const cfgPath = windowsJsonPath();
  const cfg = readJson(cfgPath, null);
  if (cfg && typeof cfg.dshInstall === 'string' && cfg.dshInstall.trim()) {
    return { value: path.resolve(cfg.dshInstall.trim()), source: `dshInstall in ${cfgPath}`, configPath: cfgPath };
  }
  return { value: null, source: null, configPath: cfgPath, configExists: cfg !== null };
}

/**
 * Locate the engine we are actually running, and read its version by RUNNING it.
 *
 * Order, per SPEC: the configured `dshInstall` / $env:DSH_INSTALL prefix, then the engine path
 * parsed out of the live dsh process, then the well-known npx path, then a scan of the npx cache.
 * When several npx installs exist we report all of them and prefer the one the running process
 * names; if that cannot be decided, we say so instead of guessing.
 */
export function detectInstalledEngine({ probe = true } = {}) {
  const configured = configuredInstallRoot();
  const notes = [];
  const seen = new Set();
  const candidates = [];

  const push = (enginePath, source) => {
    if (!enginePath) return;
    const abs = path.resolve(enginePath);
    if (seen.has(abs.toLowerCase())) return;
    seen.add(abs.toLowerCase());
    candidates.push({
      enginePath: abs,
      installRoot: path.resolve(path.dirname(abs), '..', '..', '..', '..'),  // <root>/node_modules/@deepseek-ai/dsh/lib/bin.js -> <root>
      source,
      exists: fs.existsSync(abs),
    });
  };

  if (configured.value) push(path.join(configured.value, ENGINE_REL), configured.source);

  const running = enginePathFromRunningProcess();
  if (running.error) notes.push(`could not read the live dsh command line: ${running.error}`);
  for (const p of running.paths) push(p, 'running dsh process command line');

  push(path.join(PATHS.npxInstallRoot, ENGINE_REL), 'well-known npx path for this deployment');

  const scanned = [];
  for (const root of npxInstallRoots()) {
    const p = path.join(root, ENGINE_REL);
    if (fs.existsSync(p)) { scanned.push(p); push(p, 'npx cache scan'); }
  }

  const existing = candidates.filter((c) => c.exists);
  let primary = null;
  let ambiguity = null;
  if (existing.length === 1) {
    primary = existing[0];
  } else if (existing.length > 1) {
    const runningMatch = existing.find((c) => running.paths.some((p) => path.resolve(p).toLowerCase() === c.enginePath.toLowerCase()));
    if (runningMatch) {
      primary = runningMatch;
      notes.push(`chose ${runningMatch.enginePath} because a live dsh process is running it; other candidates: ${existing.filter((c) => c !== runningMatch).map((c) => c.enginePath).join(', ')}`);
    } else {
      // Decidable without guessing when exactly one npx install is the newest by install mtime AND
      // the configured/known-path candidates are absent. Otherwise we refuse to guess.
      primary = existing[0];
      ambiguity = `several engine installs exist and none of them is the one the running process names: ${existing.map((c) => c.enginePath).join(' | ')}. Reporting the first configured/known candidate; this is ambiguous and must not be treated as authoritative.`;
      notes.push(ambiguity);
    }
  } else {
    notes.push(`no engine binary found. Install candidates checked: ${candidates.map((c) => c.enginePath).join(' | ') || '(none)'}`);
  }

  const all = existing.map((c) => {
    const v = probe ? engineVersion(c.enginePath) : { ok: false, version: null, error: 'not probed' };
    return {
      enginePath: c.enginePath, installRoot: c.installRoot, source: c.source,
      version: v.version, versionOk: v.ok, versionError: v.error || null,
      versionCommand: v.command || null, versionDurationMs: v.durationMs ?? null,
    };
  });

  const picked = primary ? all.find((c) => c.enginePath === primary.enginePath) : null;
  return {
    enginePath: picked ? picked.enginePath : null,
    installRoot: picked ? picked.installRoot : null,
    version: picked ? picked.version : null,
    versionOk: picked ? picked.versionOk : false,
    versionError: picked ? picked.versionError : (primary ? 'unprobed' : 'no engine binary found on this machine'),
    versionCommand: picked ? picked.versionCommand : null,
    probedAt: new Date().toISOString(),
    source: primary ? primary.source : null,
    configuredInstall: configured,
    ambiguous: ambiguity,
    candidates: all,
    npxInstalls: scanned,
    notes,
  };
}

// ── candidate fetch ─────────────────────────────────────────────────────────

/**
 * Install exactly one candidate version into `vendor/prefix/<version>` — a managed npm prefix that
 * is not the npx cache and not any global prefix. Verify by running the fetched binary; a fetch
 * that cannot print the requested version is a FAILED fetch, never a success.
 */
export function fetchCandidate(version, { prefixRoot = PATHS.prefixRoot, timeoutMs = Number(process.env.DSH_UPDATE_FETCH_TIMEOUT_MS || 900000) } = {}) {
  const ver = assertSafeVersion(version);
  const prefix = path.join(prefixRoot, ver);
  const enginePath = path.join(prefix, ENGINE_REL);
  ensureDir(prefix);
  const argv = ['install', '--prefix', prefix, '--no-audit', '--no-fund', '--loglevel=error', `${PKG}@${ver}`];
  const command = ['npm', ...argv].join(' ');
  const started = Date.now();

  return new Promise((resolve) => {
    const npmCmd = npmCommandLine(argv);
    const child = spawn(npmCmd.file, npmCmd.args, { cwd: prefix, windowsHide: true });
    let stdout = ''; let stderr = ''; let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill(); } catch { /* a failed kill is reported through the exit code below */ }
    }, timeoutMs);

    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('error', (err) => {
      clearTimeout(timer);
      resolve(finish({ status: null, spawnError: err.message }));
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve(finish({ status: code }));
    });

    function finish({ status, spawnError = null }) {
      const durationMs = Date.now() - started;
      const exists = fs.existsSync(enginePath);
      const probe = exists ? engineVersion(enginePath) : { ok: false, version: null, error: 'bin.js does not exist after install' };
      const versionMatches = probe.ok && probe.version === ver;
      const ok = !spawnError && !timedOut && status === 0 && exists && versionMatches;
      const reasons = [];
      if (spawnError) reasons.push(`could not run npm: ${spawnError}`);
      if (timedOut) reasons.push(`npm install timed out after ${timeoutMs} ms`);
      if (!spawnError && status !== 0) reasons.push(`npm install exited ${status}`);
      if (!exists) reasons.push(`expected ${enginePath} after install, and it is not there`);
      if (exists && !probe.ok) reasons.push(`fetched binary would not run: ${probe.error}`);
      if (exists && probe.ok && !versionMatches) reasons.push(`fetched binary reports ${probe.version}, not the requested ${ver}`);
      return {
        ok, version: ver, prefix, enginePath, command, argv,
        exitCode: status, timedOut, durationMs,
        engineExists: exists,
        printedVersion: probe.version || null,
        versionMatches,
        stdout: stdout.slice(-4000),
        stderr: stderr.slice(-4000),
        error: ok ? null : reasons.join('; '),
      };
    }
  });
}

// ── self-test ───────────────────────────────────────────────────────────────

/** Pairs that must order exactly as semver says. Wrong pair => exit non-zero. */
export const SELF_TEST_PAIRS = [
  ['0.1.7-alpha.2', '0.1.7-rc.1', -1],
  ['0.1.5-rc.1', '0.1.5-rc.3', -1],
  ['0.1.5-rc.3', '0.1.6-alpha.1', -1],
  ['0.1.5-alpha.2', '0.1.5-rc.1', -1],
  ['0.1.5-alpha.1', '0.1.5-alpha.2', -1],
  ['0.1.7-rc.1', '0.1.7-rc.2', -1],
  ['0.1.7-rc.2', '0.1.7', -1],
  ['0.1.4', '0.1.5-rc.1', -1],
  ['0.0.9', '0.1.0-alpha.1', -1],
  ['2.0.0', '10.0.0', -1],
  ['1.0.0-alpha.1', '1.0.0-alpha.beta', -1],
  ['1.0.0-beta.11', '1.0.0-rc.1', -1],
  ['0.1.5-rc.3', '0.1.5-rc.3', 0],
  ['0.1.5-rc.3', '0.1.5-rc.1', 1],
  ['0.1.7-rc.1', '0.1.7-alpha.2', 1],
  ['1.0.0', '1.0.0-rc.1', 1],
  ['0.1.5-rc.10', '0.1.5-rc.9', 1],
];

export function runSelfTest({ log = () => {} } = {}) {
  const results = [];
  for (const [a, b, expected] of SELF_TEST_PAIRS) {
    const actual = compareVersions(a, b);
    const ok = actual === expected;
    results.push({ a, b, expected, actual, ok, relation: expected < 0 ? '<' : (expected === 0 ? '==' : '>') });
    log(`${ok ? 'ok  ' : 'FAIL'}  ${a} ${expected < 0 ? '<' : (expected === 0 ? '==' : '>')} ${b}   (compareVersions = ${actual})`);
  }
  const failed = results.filter((r) => !r.ok);
  return { ok: failed.length === 0, total: results.length, failed: failed.length, results };
}

export function classificationSelfTest({ log = () => {} } = {}) {
  const published = ['0.1.4', '0.1.5-alpha.1', '0.1.5-alpha.2', '0.1.5-rc.1', '0.1.5-rc.2', '0.1.5-rc.3', '0.1.6-alpha.1'];
  const checks = [
    ['0.1.5-rc.1', '0.1.5-rc.3', 'SAME_LINE_NEWER'],
    ['0.1.5-rc.1', '0.1.6-alpha.1', 'UPGRADE'],
    ['0.1.5-rc.1', '0.1.5-rc.1', 'SAME'],
    ['0.1.5-rc.1', '0.1.4', 'DOWNGRADE'],
  ];
  const out = [];
  for (const [cur, cand, expected] of checks) {
    const got = classify(cur, cand, published);
    const ok = got.classification === expected;
    out.push({ cur, cand, expected, got: got.classification, distance: got.distance, newerThanPin: got.newerThanPin, ok });
    log(`${ok ? 'ok  ' : 'FAIL'}  classify(${cur}, ${cand}) = ${got.classification} (expected ${expected}), distance=${got.distance}`);
  }
  const newer = newerThan('0.1.5-rc.1', published);
  const expectedNewer = ['0.1.5-rc.2', '0.1.5-rc.3', '0.1.6-alpha.1'];
  const newerOk = JSON.stringify(newer) === JSON.stringify(expectedNewer);
  log(`${newerOk ? 'ok  ' : 'FAIL'}  newerThan(0.1.5-rc.1) = ${JSON.stringify(newer)} (expected ${JSON.stringify(expectedNewer)})`);
  out.push({ name: 'newerThan', ok: newerOk });
  const failed = out.filter((r) => !r.ok);
  return { ok: failed.length === 0, total: out.length, failed: failed.length, results: out };
}

function main(argv) {
  const args = argv.slice(2);
  if (args.includes('--selftest')) {
    const a = runSelfTest({ log: (l) => console.log(l) });
    const b = classificationSelfTest({ log: (l) => console.log(l) });
    const ok = a.ok && b.ok;
    console.log(`\nversions.mjs self-test: ${a.total - a.failed}/${a.total} precedence pairs and ${b.total - b.failed}/${b.total} classification checks correct.`);
    console.log(ok ? 'RESULT: PASS' : 'RESULT: FAIL');
    return ok ? 0 : 1;
  }
  if (args.includes('--engine') || args.includes('--installed')) {
    const det = detectInstalledEngine();
    console.log(JSON.stringify(det, null, 2));
    return det.enginePath ? 0 : 2;
  }
  const reg = registryPicture();
  const det = detectInstalledEngine();
  console.log(JSON.stringify({ registry: reg, installed: det }, null, 2));
  return (reg.distTags.ok || reg.versions.ok) ? 0 : 3;
}

const SELF = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(SELF)) {
  process.exitCode = main(process.argv);
}
