#!/usr/bin/env node
/**
 * dsh-update / lib/verify.mjs — the five gates (plus the opt-in web boot), run against an ISOLATED
 * DSH_HOME. This module runs engines, so the safety rules are implemented here, not described here:
 *
 *   * It never points a candidate engine at the live DSH_HOME. It copies settings.yaml, profiles/,
 *     .agent-presets/ and .credentials.yaml into state/candidates/<ver>/home/ and sets DSH_HOME to
 *     that copy for every child process. Two engines on one home have corrupted session logs before
 *     (harness-config/multi-window/windows.json).
 *   * It never starts, stops or restarts the live engine. `--profile web --dump-config`,
 *     `--profile headless --dump-config` and a headless turn are engine runs of their own, with
 *     neither a port nor the live home.
 *   * The only process it ever kills is the one it started itself: the --full web boot, killed with
 *     `taskkill /PID <its own pid> /T /F`, on a port in 3400-3500, only after a pre-flight check.
 *   * It writes only inside dsh-update/ (state/candidates, state/logs) and never deletes anything.
 *   * A gate that did not run is `ran:false, ok:false` — never a fabricated pass, and `pass` is
 *     false when no gate ran at all.
 *
 * `--no-boot` skips the two boot gates (G4, G5) and the --full web boot. G1-G3 are not boots: they
 * compose a profile (`--dump-config`) and read the result, so they still run and still report real
 * exit codes.
 *
 * Interpretations recorded deliberately (see the final report):
 *  1. G2/G3 read the tree that G1 just produced by parsing the engine's own stdout, and cross-check
 *     it against the engine's own `yaml` implementation resolved from the engine's tree. A
 *     state/candidates/<ver>/tree.json is loaded too and any disagreement is reported, but the
 *     artifact under test in a verify run is the engine that was just booted.
 *  2. consumed.patchRowTargets comes from --consumed, else state/candidates/<ver>/consumed.json,
 *     else state/consumed.json, else it is derived from the deployment's own host-plane patch file
 *     (~/.dsh/profiles/web/cordis.patch.yml) so this module still works standalone.
 *  3. --full refuses to start only on a REAL conflict (the port it picked is taken, or another
 *     `dsh web` is using its isolated home). Other `dsh web` processes — including the live engine
 *     on 3099, which this module must never touch — are listed verbatim in the gate detail.
 */

import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import process from 'node:process';
import { parseYaml } from './yaml.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');            // dsh-update/
const STATE = path.join(ROOT, 'state');
const DEFAULT_LOGS = path.join(STATE, 'logs');
const DEFAULT_LIVE_HOME = process.env.DSH_HOME && process.env.DSH_HOME.trim() !== ''
  ? process.env.DSH_HOME
  : path.join(process.env.USERPROFILE ?? process.env.HOME ?? '.', '.dsh');

/* resolved per run in main(): --dsh-home / --logs-dir override them */
let LIVE_HOME = DEFAULT_LIVE_HOME;
let LOGS = DEFAULT_LOGS;

const GATES = [
  ['G1', 'dump-config composes'],
  ['G2', 'every patch target still applies'],
  ['G3', 'our profile bundles resolve'],
  ['G4', 'settings document accepted (boot)'],
  ['G5', 'headless agent turn completes'],
  ['GFULL', 'web profile boots (--full)'],
  ['G8', 'session-format compatibility (the one-way door)'],
];

/**
 * Where the CREDENTIAL lives, so that a boot inside the isolated home can reach a model without a
 * secret ever being written anywhere. SPEC C14: resolved from the LIVE home at gate time and
 * passed into the child process ENVIRONMENT only — never copied into the isolated home, never
 * written to state/logs/ (plain text, live secret), never printed, never put in verify.json.
 */
const CREDENTIAL_KEY = 'DEEPSEEK_API_KEY';
const CREDENTIAL_BASENAME = '.credentials.yaml';

/** The package that declares the session format version and the physical codec list (SPEC C8). */
const SESSION_FORMAT_CATALOG_REL = path.join(
  'node_modules', '@deepseek-ai', 'dsh-session-format-catalog', 'lib', 'index.js',
);
/** `@deepseek-ai/*` package directories whose name describes a session-format codec or migration. */
const SESSION_FORMAT_PKG_RE = /^(@deepseek-ai\/)?dsh-session-format(?:-(v(\d+)-to-v(\d+))|-(v(\d+)))?$/;
/**
 * The engine's own canonical raw-log basename rule, quoted from
 * `@deepseek-ai/dsh-session-format/lib/index.js` (v0.1.5-rc.2):
 *   `const CANONICAL_LOG_FILENAME = /^session(?:\.v([1-9][0-9]*))?\.jsonl$/u;`
 * Version zero is the bare `session.jsonl`; every later generation is `session.vN.jsonl`. The
 * physical artifact on disk carries a compression suffix (`.zstd`), so the suffix is optional here.
 */
const SESSION_LOG_RE = /^session(?:\.v([1-9][0-9]*))?\.jsonl(?:\.zst(?:d)?|\.gz|\.br|\.lz4|\.xz)?$/i;

/**
 * The engine's own vocabulary for a settings document it will not accept. Measured on 0.1.5-rc.1
 * (2026-09-23, isolated home, verbatim stderr in tests/canary-g4-settings.mjs):
 *   "settings-file: invalid document at <path>: DUPLICATE_KEY at line 47, column 1"
 *   "dsh: plugin tree failed to load: failed to apply loader entry settings (@deepseek-ai/dsh-settings-file): ..."
 * An unknown key, a wrong value type, an out-of-range number and an invalid enum value all boot
 * cleanly with exit 0 and NO diagnostic — see MEASURED_SETTINGS_LIMITATION below.
 */
const CANDIDATE_SETTING_PATTERNS = [
  { id: 'settings-file-invalid', re: /settings-file:[^\n]*invalid document/i },
  { id: 'duplicate-key', re: /\bDUPLICATE_KEY\b/ },
  { id: 'loader-entry-settings', re: /failed to apply loader entry settings/i },
  { id: 'plugin-tree-load', re: /plugin tree failed to load/i },
  { id: 'unknown-key', re: /unknown\s+(?:key|option|setting|field|property|config)/i },
  { id: 'unrecognized', re: /unrecognized\s+(?:key|option|setting|field|property)/i },
  { id: 'not-allowed', re: /(?:is\s+not\s+allowed|must\s+NOT\s+have\s+additional\s+propert|additional\s+properties)/i },
  { id: 'invalid-settings', re: /invalid\s+(?:settings|configuration|config|option|value)/i },
  { id: 'schema-validation', re: /(?:failed|error|cannot|unable)[^\n]{0,40}validat/i },
  { id: 'settings-rejected', re: /settings[^\n]{0,40}(?:rejected|not\s+accepted|ignored|unrecognized)/i },
];

const MEASURED_SETTINGS_LIMITATION =
  'measured 2026-09-23 against 0.1.5-rc.1 in an isolated home: an unknown top-level key, an unknown key inside a known ' +
  'section, a wrong value type, an out-of-range number and an invalid enum value ALL boot with exit 0 and print no ' +
  'diagnostic at all. The engine only rejects a document it cannot PARSE (measured: DUPLICATE_KEY -> exit 1, ' +
  '"settings-file: invalid document ..."). So G4 (and B6) can catch a malformed settings document and a hard boot ' +
  'failure, but a settings key the candidate has quietly stopped honouring is invisible to every gate in this pipeline.';

const USAGE = `usage: node lib/verify.mjs --version <ver> [--prefix <installRoot> | --engine <bin.js>]
                          [--out <verify.json>] [--consumed <consumed.json>] [--contract <contract.json>]
                          [--tree <tree.json>] [--diff <diff.json>] [--logs-dir <dir>] [--dsh-home <dir>]
                          [--baseline-engine <bin.js>] [--sessions-dir <dir>]
                          [--full] [--no-boot] [--turn-timeout <ms>] [--generated-at <ISO-8601>]

Runs the dsh-update gates against an isolated copy of DSH_HOME (state/candidates/<ver>/home),
saving the verbatim output of every engine invocation under --logs-dir (default state/logs/).
--no-boot skips the two boot gates (G4, G5); it does NOT skip G8. --full adds a real web-profile
boot on a free port in 3400-3500, killed by pid immediately after. Exit 0 when the gates completed
(pass tells you whether they were ok); non-zero on a usage or infrastructure failure, with the
diagnostic on stderr.

G8 reads the session-format version and the physical codec list out of BOTH installs — the pinned
engine (state/pin.json's enginePath, or --baseline-engine) and the candidate — and compares what
the candidate would WRITE with the format of the session logs that are already on disk under
--dsh-home (default the live home). A candidate that writes a newer format with no codec that
reads it back makes rollback destroy access to the operator's real history.

The model credential for the boot gates (G4/G5/--full) is resolved from the LIVE
<dsh-home>/.credentials.yaml and passed to the child process ENVIRONMENT only. It is never
written into the isolated home, never written to state/logs/, never printed and never recorded in
verify.json. If it cannot be resolved, G4/G5 are ran:false and pass is false.

The dispatcher (lib/cli.mjs) calls this module with --engine/--contract/--tree/--diff/--logs-dir/
--dsh-home, so those flags are part of the interface: --engine is the candidate bin.js, --contract is
the artifact its sha256 is recorded from, and --tree is the candidate tree used for G2/G3 (the dump
G1 just produced is always parsed too and any disagreement is reported).`;

class UsageError extends Error {}

/* ------------------------------------------------------------------ arguments */

const VALUED_FLAGS = new Set([
  '--version', '--prefix', '--engine', '--out', '--consumed', '--contract', '--tree', '--diff',
  '--logs-dir', '--dsh-home', '--turn-timeout', '--generated-at', '--baseline-engine', '--sessions-dir',
]);

function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') return { help: true };
    if (a === '--full' || a === '--no-boot') { flags[a] = true; continue; }
    const eq = a.indexOf('=');
    const key = eq > 0 ? a.slice(0, eq) : a;
    if (!VALUED_FLAGS.has(key)) throw new UsageError(`unknown argument "${a}"`);
    const value = eq > 0 ? a.slice(eq + 1) : argv[++i];
    if (value === undefined) throw new UsageError(`missing value for ${key}`);
    flags[key] = value;
  }
  if (!flags['--version']) throw new UsageError('missing required --version <ver>');
  if (/[\\/:*?"<>|]/.test(flags['--version'])) throw new UsageError(`--version "${flags['--version']}" is not a version string`);
  return { flags };
}

function generatedAt(flags) {
  const pinned = flags['--generated-at'] ?? process.env.SOURCE_DATE_EPOCH;
  if (pinned === undefined) return new Date().toISOString();
  const t = /^\d+$/.test(pinned) ? new Date(Number(pinned) * 1000) : new Date(pinned);
  if (Number.isNaN(t.getTime())) throw new UsageError(`--generated-at "${pinned}" is not a date`);
  return t.toISOString();
}

/* ------------------------------------------------------------------ small utilities */

const iso = () => new Date().toISOString();

function sha256File(file) {
  try { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); } catch { return null; }
}

function readJsonIfPresent(file) {
  try {
    if (!fs.existsSync(file)) return null;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch { return null; }
}

/** Read a YAML text file. Returns {ok:true,text} | {ok:false,reason} — never an empty success. */
function readYamlTextChecked(file) {
  if (!fs.existsSync(file)) return { ok: false, reason: `there is no file at ${file}` };
  try {
    const text = fs.readFileSync(file, 'utf8');
    if (text.trim() === '') return { ok: false, reason: `${file} is empty` };
    return { ok: true, text };
  } catch (err) {
    return { ok: false, reason: `${file} could not be read: ${err.message}` };
  }
}

/* ------------------------------------------------------------------ the model credential (SPEC C14) */

/**
 * Walk a parsed YAML document for a key named `DEEPSEEK_API_KEY` and return its value.
 *
 * The file is a `records` map and the install on this machine keeps the key at `refs.DEEPSEEK_API_KEY`,
 * but the path is not assumed: every nested map is searched, deepest-first is not needed because the
 * first accepted candidate wins and a real key is unambiguously a non-empty string without whitespace
 * or control characters. A wrapper object (a `{ secret }` payload) is unwrapped one level.
 *
 * The VALUE is returned to the caller and never logged, never written, never serialised.
 */
function findCredentialValue(doc, keyName) {
  const wrappers = ['secret', 'value', 'key', 'token', 'apiKey', 'api_key'];
  const seen = new Set();
  const visit = (node, depth) => {
    if (depth > 12 || node === null || typeof node !== 'object') return null;
    if (seen.has(node)) return null;
    seen.add(node);
    if (node instanceof Map) {
      if (node.has(keyName)) {
        const v = unwrapCredential(node.get(keyName), wrappers, keyName);
        if (v) return v;
      }
      for (const v of node.values()) { const hit = visit(v, depth + 1); if (hit) return hit; }
      return null;
    }
    if (Array.isArray(node)) {
      for (const v of node) { const hit = visit(v, depth + 1); if (hit) return hit; }
      return null;
    }
    for (const [k, v] of Object.entries(node)) {
      if (k === keyName) {
        const w = unwrapCredential(v, wrappers, keyName);
        if (w) return w;
      }
      const hit = visit(v, depth + 1);
      if (hit) return hit;
    }
    return null;
  };
  return visit(doc, 0);
}

function unwrapCredential(value, wrappers, keyName) {
  if (typeof value === 'string') return usableCredential(value);
  if (value === null || typeof value !== 'object') return null;
  const map = value instanceof Map ? value : (Array.isArray(value) ? null : new Map(Object.entries(value)));
  if (!map) return null;
  for (const w of wrappers) {
    if (!map.has(w)) continue;
    const inner = map.get(w);
    const candidate = typeof inner === 'string' ? inner : null;
    if (candidate !== null) { const u = usableCredential(candidate); if (u) return u; }
  }
  if (map.has(keyName)) {
    const inner = map.get(keyName);
    if (typeof inner === 'string') return usableCredential(inner);
  }
  return null;
}

/** A credential is usable only when it is a non-empty single token: whitespace here means we misread. */
function usableCredential(s) {
  if (typeof s !== 'string') return null;
  const t = s.trim();
  if (t === '' || t.length < 8 || t.length > 512) return null;
  if (/\s/.test(t)) return null;
  return t;
}

/**
 * Resolve the model credential from the LIVE home's `.credentials.yaml`, with the harness's own yaml
 * implementation (`lib/yaml.mjs`), never a regex.
 *
 * Returns `{ ok:true, value, key, file, bytes, sha256 }` or `{ ok:false, reason, file }`. The caller
 * must never print `value`, never write it, and never serialise it — only its length is reportable.
 */
function resolveCredential(home) {
  const file = path.join(home, CREDENTIAL_BASENAME);
  const read = readYamlTextChecked(file);
  if (!read.ok) return { ok: false, file, reason: read.reason };
  let doc;
  try {
    doc = parseYaml(read.text, { logLevel: 'silent' });
  } catch (err) {
    return { ok: false, file, reason: `${file} is not parseable YAML: ${String(err.message).slice(0, 200)}` };
  }
  if (doc === null || doc === undefined) return { ok: false, file, reason: `${file} parsed to nothing` };
  const value = findCredentialValue(doc, CREDENTIAL_KEY);
  if (!value) {
    return { ok: false, file, reason: `no usable ${CREDENTIAL_KEY} value was found in ${file} (searched every nested map for a key named ${CREDENTIAL_KEY})` };
  }
  return {
    ok: true, value, key: CREDENTIAL_KEY, file,
    bytes: Buffer.byteLength(read.text),
    sha256: crypto.createHash('sha256').update(read.text).digest('hex'),
  };
}

/* ------------------------------------------------------------------ session formats (SPEC C8) */

/**
 * Where does `@deepseek-ai` live for this install?
 *
 * Accepts an install root, a `node_modules` directory, a scope directory, or an engine path
 * (`…\@deepseek-ai\dsh\lib\bin.js`), and returns the `…/node_modules/@deepseek-ai` directory that
 * actually exists — walking up from the path given. Returns a list of candidates that were tried
 * when none exists, so a failure can name everywhere it looked.
 */
function resolveScopeDir(p) {
  if (!p) return { scope: null, tried: ['(no path given)'] };
  const tried = [];
  let cur = path.resolve(p);
  for (let up = 0; up < 6; up += 1) {
    const direct = path.join(cur, 'node_modules', '@deepseek-ai');
    tried.push(direct);
    if (fs.existsSync(direct)) return { scope: direct, tried };
    /* `cur` may itself be a `node_modules` directory */
    const asModules = path.join(cur, '@deepseek-ai');
    if (path.basename(path.dirname(cur)) === 'node_modules' || path.basename(cur) === 'node_modules') {
      tried.push(asModules);
      if (fs.existsSync(asModules)) return { scope: asModules, tried };
    }
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  /* last resort: the path may itself be inside the scope directory */
  const inside = path.resolve(p, 'node_modules', '@deepseek-ai');
  if (!tried.includes(inside)) tried.push(inside);
  return { scope: null, tried };
}

/**
 * Read the session-format version and the physical codec list from ONE install, by reading the real
 * files under `<installRoot>/node_modules/@deepseek-ai/`:
 *
 *   * `dsh-session-format-catalog/lib/index.js` — the generated catalog: `currentVersion: N`,
 *     `codecs: [releasedV0…, …]`, `currentEncoder: releasedVE…`, `migrations: [sessionFormatVaToVb, …]`;
 *   * the sibling `dsh-session-format-*` package directories — a package whose name is
 *     `…-format-vA-to-vB` is a migration edge, `…-format-vN` a codec.
 *
 * Nothing is hardcoded: the version is whatever the file declares. A read that cannot be made returns
 * `{ok:false, reason}` — it never becomes a guess.
 */
function readSessionFormatCatalog(installRoot) {
  const { scope, tried } = resolveScopeDir(installRoot);
  let catalogFile = null;
  if (scope) {
    const f = path.join(scope, 'dsh-session-format-catalog', 'lib', 'index.js');
    if (fs.existsSync(f)) catalogFile = f;
  }
  if (!catalogFile) {
    return {
      ok: false, installRoot, lookedIn: tried,
      reason: `no @deepseek-ai/dsh-session-format-catalog/lib/index.js under ${tried.join(' or ')}`,
    };
  }

  let text;
  try { text = fs.readFileSync(catalogFile, 'utf8'); } catch (err) {
    return { ok: false, installRoot, catalogFile, reason: `${catalogFile} could not be read: ${err.message}` };
  }
  const lines = text.split(/\r?\n/);

  const currentVersion = readCatalogCurrentVersion(text);
  const codecVersions = codecVersionsFromCatalog(text);
  const encoderVersion = readCatalogCurrentEncoder(text, lines);
  /* the codec keys this install can actually READ directly (a header whose generation has a codec) */
  const codecSet = new Set(codecVersions);
  /* sidecar packages: a directory is treated as a real codec only when the catalog imports it */
  const formatPackages = [];
  try {
    for (const e of fs.readdirSync(scope, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      if (!SESSION_FORMAT_PKG_RE.test(e.name)) continue;
      const pj = readJsonIfPresent(path.join(scope, e.name, 'package.json'));
      formatPackages.push({ name: e.name, version: pj?.version ?? null });
    }
  } catch { /* an unreadable scope is reported by the reason below if the catalog itself was fine */ }
  const importedSources = new Set();
  for (const m of text.matchAll(/from\s+"(@deepseek-ai\/dsh-session-format-[\w-]+)"/g)) importedSources.add(m[1]);

  const migrations = migrationEdgesFromCatalog(text);
  const edgeSet = new Set(migrations.map((m) => `${m.from}->${m.to}`));
  /* usable for rollback: a real, IMPORTED sibling package whose edge goes from the newer version back */
  const downMigrations = migrations.filter(
    (m) => m.from > m.to && importedSources.has(`@deepseek-ai/dsh-session-format-v${m.from}-to-v${m.to}`),
  );

  const packageVersions = {};
  for (const p of formatPackages) packageVersions[p.name] = p.version;

  return {
    ok: true,
    installRoot, catalogFile, scope,
    currentVersion,
    codecs: codecVersions,
    codecSet,
    currentEncoder: encoderVersion,
    /** derived: the higher of the declared currentVersion and the declared codecs — a disagreement is a finding of its own */
    highestCodec: codecVersions.length > 0 ? Math.max(...codecVersions) : null,
    migrations,
    migrationEdges: edgeSet,
    downMigrations,
    canRead: (n) => codecSet.has(n),
    formatPackages, packageVersions, importedSources,
    manifestVersion: readJsonIfPresent(path.join(scope, 'dsh-session-format-catalog', 'package.json'))?.version ?? null,
  };
}

function readCatalogCurrentVersion(text) {
  const m = /currentVersion\s*:\s*(\d+)\s*[,}]/g;
  const vals = [...text.matchAll(m)].map((x) => Number(x[1]));
  if (vals.length === 0) return null;
  /* the generated catalog is the primary export; the largest declared value is the engine's current */
  return Math.max(...vals);
}

function readCatalogCurrentEncoder(text, lines) {
  for (const line of lines) {
    const m = /currentEncoder\s*:\s*(releasedV(\d+)SessionFormatCodec)/.exec(line);
    if (m) return Number(m[2]);
  }
  return null;
}

function codecVersionsFromCatalog(text) {
  const set = new Set();
  const block = /codecs\s*:\s*\[([^\]]*)\]/s.exec(text);
  if (block) {
    for (const m of block[1].matchAll(/releasedV(\d+)SessionFormatCodec/gi)) set.add(Number(m[1]));
  }
  if (set.size === 0) {
    for (const m of text.matchAll(/releasedV(\d+)SessionFormatCodec/gi)) set.add(Number(m[1]));
  }
  return [...set].sort((a, b) => a - b);
}

function migrationEdgesFromCatalog(text) {
  const edges = [];
  const block = /migrations\s*:\s*\[([^\]]*)\]/s.exec(text);
  const add = (a, b) => { if (!edges.some((e) => e.from === a && e.to === b)) edges.push({ from: a, to: b }); };
  if (block) {
    for (const m of block[1].matchAll(/sessionFormatV(\d+)ToV(\d+)/gi)) add(Number(m[1]), Number(m[2]));
  }
  if (edges.length === 0) {
    for (const m of text.matchAll(/sessionFormatV(\d+)ToV(\d+)/gi)) add(Number(m[1]), Number(m[2]));
  }
  return edges.sort((a, b) => a.from - b.from || a.to - b.to);
}

/**
 * Count the session files in a home and say which format each is in, from the NAME only.
 *
 * The rule quoted from the engine: `session.jsonl` is generation 0, `session.vN.jsonl` generation N,
 * and the physical artifact adds a compression suffix. Nothing is opened: a session log is the
 * operator's history and this gate must never read or touch one.
 *
 * `ok:false` when the directory cannot be walked — a partial walk is a wrong count, and a wrong count
 * is worse than an admission. Never reports 0 as though it had looked.
 */
function snapshotSessionFormats(sessionsDir) {
  const out = {
    dir: sessionsDir, exists: false, walked: false, ok: false, reason: null, walkErrors: [],
    total: 0, byVersion: {}, byName: {}, oldestMtime: null, newestMtime: null, maxDepth: 0,
  };
  if (!fs.existsSync(sessionsDir)) {
    out.reason = `there is no sessions directory at ${sessionsDir}`;
    return out;
  }
  out.exists = true;
  const stack = [[sessionsDir, 0]];
  const bump = (bag, k) => { bag[k] = (bag[k] ?? 0) + 1; };
  while (stack.length > 0) {
    const [dir, depth] = stack.pop();
    if (depth > out.maxDepth) out.maxDepth = depth;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (err) {
      out.walkErrors.push(`${dir}: ${err.code ?? err.message}`);
      continue;
    }
    for (const e of entries) {
      const p = path.join(dir, e.name);
      let st;
      try { st = fs.lstatSync(p); } catch (err) { out.walkErrors.push(`${p}: ${err.code ?? err.message}`); continue; }
      if (st.isSymbolicLink()) continue;               // links are never traversed anywhere in this module
      if (st.isDirectory()) { stack.push([p, depth + 1]); continue; }
      const m = SESSION_LOG_RE.exec(e.name);
      if (!m) continue;
      const version = m[1] === undefined ? 0 : Number(m[1]);
      out.total += 1;
      bump(out.byVersion, String(version));
      bump(out.byName, e.name);
      const t = st.mtime.toISOString();
      if (out.oldestMtime === null || t < out.oldestMtime) out.oldestMtime = t;
      if (out.newestMtime === null || t > out.newestMtime) out.newestMtime = t;
    }
  }
  out.walked = true;
  out.ok = out.walkErrors.length === 0;
  if (!out.ok) out.reason = `${out.walkErrors.length} directory/entry read error(s) while walking ${sessionsDir}; the count is partial and is not reported as a reading`;
  return out;
}

function formatCounts(map, keyName) {
  const keys = Object.keys(map).sort((a, b) => Number(a) - Number(b));
  return keys.map((k) => `${keyName === 'version' ? `v${k}` : k} x${map[k]}`).join(', ');
}

/** Walk without following links: links are counted, never traversed. Handles a plain file too. */
function measure(target) {
  const out = { files: 0, bytes: 0, links: 0, dirs: 0 };
  if (!fs.existsSync(target)) return out;
  const head = fs.lstatSync(target);
  if (head.isSymbolicLink()) { out.links += 1; return out; }
  if (!head.isDirectory()) { out.files += 1; out.bytes += head.size; return out; }
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
      if (st.isDirectory()) { out.dirs += 1; stack.push(p); continue; }
      out.files += 1;
      out.bytes += st.size;
    }
  }
  return out;
}

/**
 * Copy preserving links. Windows file symlinks need privileges this pipeline does not assume, so a
 * file link that cannot be recreated is copied as bytes and counted as `copiedLinks` — the copy is
 * then slightly larger, which is recorded rather than hidden.
 *
 * Idempotent: a destination link is re-pointed, an existing plain file is overwritten, and a real
 * destination DIRECTORY where the source is a link is left untouched (nothing is ever deleted
 * recursively — the engine heals its own module fallback inside the isolated copy).
 */
function copyTree(src, dst, stats) {
  const st = fs.lstatSync(src);
  if (st.isSymbolicLink()) {
    const target = fs.readlinkSync(src);
    const isDir = fs.statSync(src).isDirectory();
    let existing = null;
    try { existing = fs.lstatSync(dst); } catch { /* nothing there */ }
    if (existing) {
      if (existing.isDirectory() && !existing.isSymbolicLink()) {
        stats.linkTargetsLeftAsDirs += 1;
        return;
      }
      try {
        if (existing.isSymbolicLink() && existing.isDirectory()) fs.rmdirSync(dst);
        else fs.unlinkSync(dst);
        stats.replacedLinks += 1;
      } catch (err) {
        throw new Error(`cannot replace ${dst}: ${err.message}`);
      }
    }
    try {
      fs.symlinkSync(target, dst, isDir ? 'junction' : 'file');
    } catch (err) {
      if (isDir) throw err;
      fs.copyFileSync(fs.realpathSync(src), dst);
      stats.copiedLinks += 1;
    }
    stats.links += 1;
    return;
  }
  if (st.isDirectory()) {
    fs.mkdirSync(dst, { recursive: true });
    stats.dirs += 1;
    for (const name of fs.readdirSync(src)) copyTree(path.join(src, name), path.join(dst, name), stats);
    return;
  }
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(src, dst);
  stats.files += 1;
  stats.bytes += st.size;
}

/* ------------------------------------------------------------------ engine resolution */

function binFor(prefix) {
  const candidates = [
    path.join(prefix, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js'),
    path.join(prefix, 'lib', 'bin.js'),
  ];
  if (prefix.endsWith('.js')) candidates.unshift(prefix);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

function npxCacheEngines() {
  const root = path.join(process.env.LOCALAPPDATA ?? '', 'npm-cache', '_npx');
  const found = [];
  let dirs = [];
  try { dirs = fs.readdirSync(root); } catch { return found; }
  for (const d of dirs) {
    const pj = path.join(root, d, 'node_modules', '@deepseek-ai', 'dsh', 'package.json');
    const manifest = readJsonIfPresent(pj);
    if (!manifest) continue;
    const bin = path.join(root, d, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
    if (fs.existsSync(bin)) found.push({ enginePath: bin, version: manifest.version ?? null, installRoot: path.join(root, d) });
  }
  return found;
}

/** Resolve the engine for this version, and say where it came from. */
function resolveEngine(version, prefixFlag, engineFlag) {
  if (engineFlag) {
    const abs = path.resolve(engineFlag);
    if (!fs.existsSync(abs)) throw new UsageError(`--engine "${abs}" does not exist`);
    return { enginePath: abs, source: `--engine ${abs}` };
  }
  if (prefixFlag) {
    const abs = path.resolve(prefixFlag);
    const bin = binFor(abs);
    if (!bin) throw new UsageError(`--prefix "${abs}" has no @deepseek-ai/dsh/lib/bin.js (and no lib/bin.js)`);
    return { enginePath: bin, source: `--prefix ${abs}` };
  }
  const vendor = path.join(ROOT, 'vendor', 'prefix', version);
  const vendorBin = binFor(vendor);
  if (vendorBin) return { enginePath: vendorBin, source: `vendor/prefix/${version}` };

  const pin = readJsonIfPresent(path.join(STATE, 'pin.json'));
  if (pin && String(pin.version) === String(version)) {
    if (pin.enginePath && fs.existsSync(pin.enginePath)) return { enginePath: pin.enginePath, source: 'state/pin.json enginePath' };
    if (pin.installRoot) {
      const b = binFor(pin.installRoot);
      if (b) return { enginePath: b, source: 'state/pin.json installRoot' };
    }
  }
  if (process.env.DSH_INSTALL) {
    const b = binFor(process.env.DSH_INSTALL);
    if (b) return { enginePath: b, source: 'DSH_INSTALL' };
  }
  const hit = npxCacheEngines().find((e) => String(e.version) === String(version));
  if (hit) return { enginePath: hit.enginePath, source: `npx cache ${hit.installRoot} (found, not fetched by this pipeline)` };
  return { enginePath: null, source: null };
}

function dshManifest(enginePath) {
  const pj = path.resolve(path.dirname(enginePath), '..', 'package.json');
  return readJsonIfPresent(pj) ?? {};
}

/* ------------------------------------------------------------------ the profile dump parser */

/**
 * The composed profile tree is a YAML sequence of maps whose rows are attributed by the comment
 * lines that precede them (`# == <layer>[, patched by <path>]`). The attribution is in the comments,
 * which a YAML parser discards, so attribution comes from the text and the row identity is
 * cross-checked against the engine's own `yaml` implementation when it is reachable.
 */
function parseDump(text) {
  const lines = text.split(/\r?\n/);
  const rows = [];
  const layerComments = [];
  let attribution = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = /^#\s*==\s*(.*)$/.exec(line);
    if (m) {
      attribution = m[1].trim();
      layerComments.push(attribution);
      continue;
    }
    // a top-level row is a column-0 sequence item whose inline remainder is empty or `key: value`
    const row = /^-(?:\s+(.*))?$/.exec(line);
    if (!row) continue;
    const inline = (row[1] ?? '').trim();
    if (inline !== '' && !/^[A-Za-z_][\w.-]*:/.test(inline)) continue; // a bare scalar: not a composed row
    const inlineId = /^id:\s*(.*)$/.exec(inline);
    let id = inlineId ? stripScalar(inlineId[1]) : null;
    let name = /^name:\s*(.*)$/.exec(inline) ? stripScalar(/^name:\s*(.*)$/.exec(inline)[1]) : null;
    let disabled = false;
    // row fields live at exactly two spaces of indentation; deeper keys belong to `config`
    for (let j = i + 1; j < lines.length; j++) {
      if (/^-(?:\s|$)/.test(lines[j]) || /^#\s*==/.test(lines[j])) break;
      const nm = /^ {2}name:\s*(.*)$/.exec(lines[j]);
      if (nm && name === null) name = stripScalar(nm[1]);
      const idm = /^ {2}id:\s*(.*)$/.exec(lines[j]);
      if (idm && id === null) id = stripScalar(idm[1]);
      const dm = /^ {2}disabled:\s*(.*)$/.exec(lines[j]);
      if (dm) disabled = stripScalar(dm[1]) === 'true';
    }
    const patchedBy = attribution && /patched by\s+(.+)$/.exec(attribution) ? /patched by\s+(.+)$/.exec(attribution)[1].trim() : null;
    rows.push({ index: rows.length, id, name, disabled, patchedBy, layers: attribution ? [attribution] : [] });
  }
  const names = rows.map((r) => r.name).filter(Boolean);
  const rowIds = rows.map((r) => r.id).filter(Boolean);
  const patchedRowIds = rows.filter((r) => r.patchedBy !== null).map((r) => r.id).filter(Boolean);
  return { rows, names, rowIds, patchedRowIds, layerComments, attributions: [...new Set(rows.map((r) => (r.layers[0] ?? null)))].filter(Boolean) };
}

function stripScalar(v) {
  let s = String(v).trim();
  if (s.startsWith('"') && s.endsWith('"')) s = s.slice(1, -1);
  else if (s.startsWith("'") && s.endsWith("'")) s = s.slice(1, -1);
  return s;
}

/** Cross-check with the engine's own yaml implementation, resolved from the engine's tree. */
function yamlParse(enginePath, text) {
  try {
    const req = createRequire(enginePath);
    const yaml = req('yaml');
    const doc = yaml.parse(text, { logLevel: 'silent' });
    if (!Array.isArray(doc)) return { ok: false, reason: 'the dump did not parse to a sequence' };
    return { ok: true, doc, rows: doc.length };
  } catch (err) {
    return { ok: false, reason: `the engine's own yaml module could not cross-check this dump: ${err.message}` };
  }
}

/** Structures (id/name/disabled) from YAML when reachable; attribution only ever from the comments. */
function mergeStructures(textRows, cross) {
  if (!cross.ok || cross.doc.length !== textRows.length) return textRows;
  return textRows.map((row, i) => {
    const y = cross.doc[i] ?? {};
    return {
      ...row,
      id: typeof y.id === 'string' ? y.id : row.id,
      name: typeof y.name === 'string' ? y.name : row.name,
      disabled: y.disabled === true,
      config: y.config ?? null,
    };
  });
}

/* ------------------------------------------------------------------ log writing */

function writeEvidence(name, body) {
  fs.mkdirSync(LOGS, { recursive: true });
  const file = path.join(LOGS, name);
  fs.writeFileSync(file, body);
  return path.relative(ROOT, file).split(path.sep).join('/');
}

function evidenceBody({ command, cwd, env, result, extra }) {
  const lines = [];
  lines.push(`command: ${command}`);
  lines.push(`cwd: ${cwd}`);
  lines.push(`DSH_HOME: ${env.DSH_HOME}`);
  lines.push(`startedAt: ${result.startedAt}`);
  lines.push(`durationMs: ${result.durationMs}`);
  lines.push(`exitCode: ${result.exitCode}`);
  lines.push(`signal: ${result.signal ?? 'none'}`);
  lines.push(`timedOut: ${result.timedOut ? 'yes' : 'no'}`);
  if (extra) lines.push(`note: ${extra}`);
  lines.push('', '=== STDOUT (verbatim) ===', result.stdout ?? '', '=== STDERR (verbatim) ===', result.stderr ?? '');
  return lines.join('\n') + '\n';
}

/* ------------------------------------------------------------------ running an engine */

/**
 * Run one engine invocation inside the isolated home.
 *
 * `extraEnv` carries the model credential (SPEC C14). It goes into the child process's environment
 * and NOWHERE else: the evidence file records `DSH_HOME` and the command, never the environment, and
 * the returned result carries only exit code, streams and timings. Nothing here can write a secret.
 */
function runEngine({ enginePath, args, home, cwd, timeoutMs, label, extraEnv }) {
  const env = { ...process.env, DSH_HOME: home, ...(extraEnv ?? {}) };
  const startedAt = iso();
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [enginePath, ...args], {
    env, cwd, encoding: 'utf8', timeout: timeoutMs, maxBuffer: 128 * 1024 * 1024, windowsHide: true,
  });
  const durationMs = Date.now() - t0;
  const result = {
    command: `node ${enginePath} ${args.join(' ')}`,
    startedAt, durationMs,
    exitCode: r.status === null ? null : r.status,
    signal: r.signal ?? null,
    timedOut: r.error?.code === 'ETIMEDOUT' || r.signal === 'SIGTERM',
    stdout: r.stdout ?? '',
    stderr: r.stderr ?? '',
    error: r.error ? String(r.error.message ?? r.error) : null,
  };
  const evidence = writeEvidence(label, evidenceBody({ command: result.command, cwd, env, result }));
  return { result, evidence };
}

/* ------------------------------------------------------------------ gate collection */

function makeGates() {
  const recorded = new Map();
  function gate(id, fields) {
    const [defaultName] = GATES.find(([g]) => g === id)?.slice(1) ?? [];
    recorded.set(id, {
      id,
      name: fields.name ?? defaultName ?? id,
      ran: Boolean(fields.ran),
      ok: Boolean(fields.ok),
      exitCode: fields.exitCode === undefined ? null : fields.exitCode,
      durationMs: fields.durationMs === undefined ? null : fields.durationMs,
      detail: fields.detail ?? '',
      evidence: fields.evidence ?? null,
    });
  }
  function finish() {
    // fixed order, and a gate that never ran is still reported as ran:false — never omitted
    return GATES.map(([id, name]) => recorded.get(id) ?? { id, name, ran: false, ok: false, exitCode: null, durationMs: null, detail: 'this gate was not reached', evidence: null });
  }
  return { gate, finish };
}

/* ------------------------------------------------------------------ inputs for G2/G3 */

function patchTargets(version, consumedFlag) {
  if (consumedFlag) {
    const j = readJsonIfPresent(path.resolve(consumedFlag));
    if (!j) throw new UsageError(`--consumed "${consumedFlag}" is not readable JSON`);
    return { targets: (j.patchRowTargets ?? []).map((t) => String(t.id)), source: `--consumed ${consumedFlag}` };
  }
  for (const p of [path.join(STATE, 'candidates', version, 'consumed.json'), path.join(STATE, 'consumed.json')]) {
    const j = readJsonIfPresent(p);
    if (j && Array.isArray(j.patchRowTargets)) {
      return { targets: j.patchRowTargets.map((t) => String(t.id)), source: path.relative(ROOT, p).split(path.sep).join('/') };
    }
  }
  const patchFile = path.join(LIVE_HOME, 'profiles', 'web', 'cordis.patch.yml');
  let text;
  try { text = fs.readFileSync(patchFile, 'utf8'); } catch {
    return { targets: [], source: null, error: `no consumed.json available and ${patchFile} could not be read` };
  }
  const targets = [];
  for (const line of text.split(/\r?\n/)) {
    const m = /^\s*\{?\s*id:\s*(.+?)\s*,?\s*$/.exec(line);
    if (m) targets.push(stripScalar(m[1]));
  }
  return { targets: [...new Set(targets)], source: `${patchFile} (parsed directly; no consumed.json available)` };
}

function profileBundles(profile) {
  const pj = path.join(LIVE_HOME, 'profiles', profile, 'package.json');
  const j = readJsonIfPresent(pj);
  const bundles = j?.dsh?.profile?.bundles;
  if (!Array.isArray(bundles)) return { bundles: [], source: null, error: `could not read dsh.profile.bundles from ${pj}` };
  return { bundles: bundles.map(String), source: pj };
}

/* ------------------------------------------------------------------ gates G1..G3 */

function gateG1({ version, enginePath, home, cwd, g, extraEnv }) {
  const { result, evidence } = runEngine({
    enginePath, args: ['--profile', 'web', '--dump-config'], home, cwd, timeoutMs: 120000,
    label: `verify-${version}-G1.txt`, extraEnv,
  });
  if (result.exitCode !== 0) {
    g('G1', {
      ran: true, ok: false, exitCode: result.exitCode, durationMs: result.durationMs, evidence,
      detail: `\`--profile web --dump-config\` exited ${result.exitCode}${result.timedOut ? ' (timed out)' : ''}; stderr: ${(result.stderr || result.error || '').split(/\r?\n/).slice(0, 3).join(' / ').slice(0, 400)}`,
    });
    return null;
  }
  const parsed = parseDump(result.stdout);
  const cross = yamlParse(enginePath, result.stdout);
  if (cross.ok && cross.doc.length === parsed.rows.length) parsed.rows = mergeStructures(parsed.rows, cross);
  parsed.names = parsed.rows.map((r) => r.name).filter(Boolean);
  parsed.rowIds = parsed.rows.map((r) => r.id).filter(Boolean);
  parsed.patchedRowIds = parsed.rows.filter((r) => r.patchedBy !== null).map((r) => r.id).filter(Boolean);
  const rowCount = parsed.rows.length;
  const agreement = cross.ok ? (cross.rows === rowCount) : null;
  const ok = rowCount > 0 && agreement !== false;
  const detail = rowCount === 0
    ? 'the dump exited 0 but produced no rows — an empty result is a refusal, not health'
    : `${rowCount} rows, exit 0, ${result.durationMs} ms; text parse and the engine's own yaml ` +
      (cross.ok ? `AGREE (${cross.rows} rows)` : `cross-check unavailable (${cross.reason})`) +
      `; patched rows: ${parsed.patchedRowIds.length} (${parsed.patchedRowIds.slice(0, 8).join(', ')}${parsed.patchedRowIds.length > 8 ? ', …' : ''})`;
  g('G1', { ran: true, ok, exitCode: result.exitCode, durationMs: result.durationMs, evidence, detail });
  return { parsed, cross, rowCount, durationMs: result.durationMs };
}

/**
 * Is this row's patch attribution one of OUR layers? Ours are the deployment's own patch files:
 * $DSH_HOME/profiles/<profile>/cordis.patch.yml and $DSH_HOME/cordis.patch.yml. A bundle's own patch
 * (`@deepseek-ai/dsh-web-app`, `dsh-plugin-remote-fanout`) is upstream/shipped and is NOT ours —
 * counting it would let G2 pass while our own layer applied nothing.
 */
function attributionIsOurs(patchedBy, home) {
  if (!patchedBy) return false;
  if (/cordis\.patch\.yml$/i.test(patchedBy)) return true;
  const normalized = patchedBy.replace(/\//g, '\\').toLowerCase();
  return normalized.startsWith(home.replace(/\//g, '\\').toLowerCase());
}

/**
 * Which tree do the tree-based gates read?
 *
 * The dispatcher passes the candidate tree it produced with --tree (and the same artifact lives at
 * state/candidates/<ver>/tree.json), and the rest of the pipeline reads that file, so consistency
 * matters. But this module also just composed the very same profile, so it always parses the fresh
 * dump as well: the dispatcher's artifact is the tree under test, the fresh dump is the cross-check,
 * and any disagreement between them is reported rather than swallowed. If the artifact is a failure
 * or empty, the fresh dump is used and the gate says why.
 */
function treeForGates({ g1, artifact, artifactPath }) {
  const fromDump = g1 ? {
    rowIds: g1.parsed.rowIds,
    names: g1.parsed.names,
    patchedRowIds: g1.parsed.patchedRowIds,
    oursPatchedRowIds: g1.parsed.rows.filter((r) => attributionIsOurs(r.patchedBy, LIVE_HOME)).map((r) => r.id),
    layerComments: g1.parsed.layerComments,
    durationMs: g1.durationMs,
    source: 'the dump G1 just produced',
    problem: null,
  } : null;
  if (!artifact) return { used: fromDump, crossCheck: null, note: null };
  const rows = Array.isArray(artifact.rows) ? artifact.rows : [];
  const bad = artifact.failure
    || (typeof artifact.exitCode === 'number' && artifact.exitCode !== 0)
    || rows.length === 0;
  const fromArtifact = {
    rowIds: Array.isArray(artifact.rowIds) ? artifact.rowIds : rows.map((r) => r?.id).filter(Boolean),
    names: [...new Set((Array.isArray(artifact.names) ? artifact.names : rows.map((r) => r?.name)).filter(Boolean))],
    patchedRowIds: Array.isArray(artifact.patchedRowIds) ? artifact.patchedRowIds : [],
    // Layer attribution comes from the engine's own comment lineage in the fresh dump whenever it
    // exists: a tree artifact built by another module may mark only the first row after a patch
    // comment, which would make G2 report a lost patch target that was never lost.
    oursPatchedRowIds: fromDump ? fromDump.oursPatchedRowIds : null,
    layerComments: Array.isArray(artifact.layerComments) ? artifact.layerComments : [],
    durationMs: typeof artifact.durationMs === 'number' ? artifact.durationMs : (fromDump?.durationMs ?? null),
    source: `${artifactPath} (engineVersion ${artifact.engineVersion ?? '?'}, exitCode ${artifact.exitCode ?? '?'}, ${rows.length} rows)`,
    problem: bad ? `${artifactPath} is a refusal, not a tree: ${artifact.failure ? `failure="${artifact.failure}"` : `exitCode ${artifact.exitCode}`}, ${rows.length} rows` : null,
  };
  const note = bad
    ? `the supplied tree artifact is a failure/empty (${fromArtifact.problem}); the tree-based gates used the dump G1 just produced instead`
    : `G2/G3 read the supplied tree artifact (${fromArtifact.source}); the fresh dump is the cross-check`;
  const crossCheck = fromDump ? {
    agreePatched: JSON.stringify([...new Set(fromArtifact.patchedRowIds)].sort()) === JSON.stringify([...new Set(fromDump.patchedRowIds)].sort()),
    agreeRows: fromArtifact.rowIds.length === fromDump.rowIds.length,
  } : null;
  return { used: bad && fromDump ? { ...fromDump, problem: fromArtifact.problem } : fromArtifact, crossCheck, note };
}

function gateG2({ version, tree, targets, patchSource, treeNote, g }) {
  const ourPatchRows = tree?.oursPatchedRowIds ?? tree?.patchedRowIds ?? null;
  const evidence = writeEvidence(`verify-${version}-G2.txt`, [
    `patch targets source: ${patchSource}`,
    `targets: ${JSON.stringify(targets)}`,
    `tree source: ${tree?.source ?? '(none)'}`,
    treeNote ? `note: ${treeNote}` : null,
    `tree.patchedRowIds: ${JSON.stringify(tree?.patchedRowIds ?? null)}`,
    `tree rows patched by our layer (from the fresh dump only): ${JSON.stringify(ourPatchRows)}`,
  ].filter(Boolean).join('\n') + '\n');
  if (!tree) {
    g('G2', { ran: false, ok: false, evidence, detail: 'no usable tree was produced (G1 did not compose and no tree artifact was supplied), so no patch target could be checked' });
    return;
  }
  if (targets.length === 0) {
    g('G2', {
      ran: true, ok: false, exitCode: null, durationMs: tree.durationMs, evidence,
      detail: `no patch row targets were available (${patchSource ?? 'no source'}); with nothing to check this gate cannot pass`,
    });
    return;
  }
  const our = new Set(ourPatchRows);
  const any = new Set(tree.patchedRowIds);
  const lost = targets.filter((t) => !our.has(t));
  const lostNotAnywhere = lost.filter((t) => !any.has(t));
  const ok = lost.length === 0;
  const attributionNote = tree.oursPatchedRowIds === null
    ? ' (no fresh dump was available, so the supplied artifact\'s patchedRowIds was used as-is)'
    : (tree.source.startsWith('the dump') ? '' : ' (layer attribution read from the fresh dump, not from the supplied artifact)');
  // when the artifact and the fresh dump disagree, say which ids and why — silently preferring one
  // would hide a real difference between the two extractors
  const artifactOnly = (tree.patchedRowIds ?? []).filter((id) => !new Set(tree.oursPatchedRowIds ?? tree.patchedRowIds ?? []).has(id));
  const dumpOnly = (tree.oursPatchedRowIds ?? []).filter((id) => !any.has(id));
  const disagreement = tree.oursPatchedRowIds !== null && artifactOnly.length + dumpOnly.length > 0
    ? `; the supplied artifact's patchedRowIds contains ${artifactOnly.length} id(s) the fresh dump does not attribute to our layer (${artifactOnly.slice(0, 6).join(', ') || 'none'}) and omits ${dumpOnly.length} the fresh dump does (${dumpOnly.slice(0, 6).join(', ') || 'none'})`
    : '';
  const detail = ok
    ? `all ${targets.length} patch target(s) still carry our patch attribution: ${targets.join(', ')}${attributionNote}${disagreement}`
    : `LOST (our patch silently stopped applying): ${lost.join(', ')}` +
      (lostNotAnywhere.length > 0 ? ` — of those, ${lostNotAnywhere.join(', ')} carry no patch attribution from ANY layer` : '') +
      `; our-layer patched rows in this tree: ${ourPatchRows.join(', ') || '(none)'}${attributionNote}${disagreement}`;
  g('G2', { ran: true, ok, exitCode: null, durationMs: tree.durationMs, evidence, detail });
}

function gateG3({ version, tree, bundles, bundleSource, treeNote, g }) {
  const evidence = writeEvidence(`verify-${version}-G3.txt`, [
    `bundles source: ${bundleSource ?? 'unavailable'}`,
    `bundles (${bundles.length}): ${JSON.stringify(bundles)}`,
    `tree source: ${tree?.source ?? '(none)'}`,
    treeNote ? `note: ${treeNote}` : null,
    `row names in the tree: ${JSON.stringify(tree?.names ?? null)}`,
    `layer comments in the tree: ${JSON.stringify(tree?.layerComments ?? null)}`,
  ].filter(Boolean).join('\n') + '\n');
  if (!tree) {
    g('G3', { ran: false, ok: false, evidence, detail: 'no usable tree was produced, so no bundle could be checked' });
    return;
  }
  if (bundles.length === 0) {
    g('G3', {
      ran: true, ok: false, exitCode: null, durationMs: tree.durationMs, evidence,
      detail: `no profile bundles were available (${bundleSource ?? 'no source'}); with nothing to check this gate cannot pass`,
    });
    return;
  }
  const names = new Set(tree.names);
  const layers = new Set(tree.layerComments);
  const resolved = [];
  const missing = [];
  for (const b of bundles) {
    const asRow = names.has(b);
    const asLayer = layers.has(b) || [...layers].some((l) => l.startsWith(`${b},`) || l.startsWith(`${b} `));
    if (asRow) resolved.push({ bundle: b, how: 'row name' });
    else if (asLayer) resolved.push({ bundle: b, how: 'bundle layer comment' });
    else missing.push(b);
  }
  const local = bundles.filter((b) => b.startsWith('dsh-plugin-'));
  const upstream = bundles.filter((b) => b.startsWith('@deepseek-ai/'));
  const ok = missing.length === 0;
  g('G3', {
    ran: true, ok, exitCode: null, durationMs: tree.durationMs, evidence,
    detail: ok
      ? `${resolved.length}/${bundles.length} bundles resolve in the candidate tree ` +
        `(${local.length} local dsh-plugin-* as row names, ${upstream.length} upstream as layer comments)` +
        `; resolved: ${resolved.map((r) => `${r.bundle}[${r.how}]`).join(', ')}`
      : `${resolved.length}/${bundles.length} resolved; MISSING: ${missing.join(', ')}`,
  });
}

/* ------------------------------------------------------------------ G4/G5 (boots) */

function scanSettingsDiagnostics(text) {
  const hits = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    for (const p of CANDIDATE_SETTING_PATTERNS) {
      if (p.re.test(lines[i])) hits.push({ pattern: p.id, line: i + 1, text: lines[i].trim().slice(0, 400) });
    }
  }
  return hits;
}

/** How the model credential reached the child, stated without ever showing it. */
function credentialProvenance(credential) {
  if (!credential || !credential.ok) return 'the model credential was NOT available, so this boot could not have reached a model';
  return `model credential: ${credential.key} passed through the child ENVIRONMENT only ` +
    `(present: yes, ${credential.valueLength ?? '?'} characters${credential.sha256 ? `, resolved from the live <dsh-home>/${CREDENTIAL_BASENAME}` : ''}` +
    `; never written into the isolated home, never written to any log, never printed, never recorded in verify.json)`;
}

function gateG4({ version, headlessDump, boot, diagnostics, g, credential }) {
  const scannedBytes = (headlessDump.result.stdout || '').length + (headlessDump.result.stderr || '').length +
    (boot.result.stdout || '').length + (boot.result.stderr || '').length;
  const evidence = writeEvidence(`verify-${version}-G4.txt`, [
    `settings document scanned: ${path.join(LIVE_HOME, 'settings.yaml')} (copied into the isolated home)`,
    `${credentialProvenance(credential)}`,
    credential?.ok ? null : `the credential could not be resolved: ${credential?.reason ?? 'no credential object'}`,
    `headless dump-config: exit ${headlessDump.result.exitCode}, ${headlessDump.result.durationMs} ms, ${(headlessDump.result.stdout || '').length} stdout bytes, ${(headlessDump.result.stderr || '').length} stderr bytes`,
    `headless boot for the settings scan: ${boot.result.command} (exit ${boot.result.exitCode}, ${boot.result.durationMs} ms) — this is the same single process G5 reports`,
    `scanned: ${scannedBytes} bytes of combined engine stdout+stderr from both invocations`,
    '',
    '=== diagnostics matched (unknown-key / unrecognized / schema / validation / rejected) ===',
    diagnostics.length === 0 ? '(none)' : diagnostics.map((d) => `[${d.pattern}] line ${d.line}: ${d.text}`).join('\n'),
    '',
    '=== headless --dump-config stdout+stderr (verbatim) ===',
    headlessDump.result.stdout || '', headlessDump.result.stderr || '',
    '=== headless boot stdout+stderr (verbatim) ===',
    boot.result.stdout || '', boot.result.stderr || '',
  ].filter((l) => l !== null).join('\n') + '\n');
  const dumpOk = headlessDump.result.exitCode === 0;
  const bootOk = boot.result.exitCode === 0;
  const ok = dumpOk && bootOk && diagnostics.length === 0;
  const parts = [];
  parts.push(`headless --dump-config exit ${headlessDump.result.exitCode}`);
  parts.push(`boot exit ${boot.result.exitCode}`);
  parts.push(credentialProvenance(credential));
  parts.push(diagnostics.length === 0
    ? `no unknown-key / unrecognized / schema / validation diagnostics in ${scannedBytes} bytes of combined engine output from both invocations`
    : `${diagnostics.length} diagnostic line(s) matched: ${diagnostics.slice(0, 5).map((d) => `[${d.pattern}] ${d.text.slice(0, 120)}`).join(' | ')}`);
  parts.push('NOTE: a settings key the candidate silently ignores cannot be seen by any gate here (measured: unknown keys, wrong types, out-of-range numbers and invalid enum values all boot with exit 0 and no diagnostic); this gate catches a malformed document and a hard boot failure');
  g('G4', { ran: true, ok, exitCode: boot.result.exitCode, durationMs: headlessDump.result.durationMs + boot.result.durationMs, evidence, detail: parts.join('; ') });
}

function extractAssistantText(stdout) {
  const text = (stdout ?? '').trim();
  if (text === '') return null;
  if (text.length <= 4000) {
    // a headless turn prints the answer; if it looks like one JSON object, prefer a text-ish field
    if (text.startsWith('{') && text.endsWith('}')) {
      try {
        const j = JSON.parse(text);
        for (const k of ['text', 'answer', 'result', 'content', 'message', 'output']) {
          if (typeof j?.[k] === 'string' && j[k].trim() !== '') return j[k].trim();
        }
      } catch { /* not JSON: fall through */ }
    }
    return text;
  }
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  return lines.length > 0 ? lines[lines.length - 1].slice(0, 2000) : null;
}

function gateG5({ version, boot, g, credential }) {
  const reply = extractAssistantText(boot.result.stdout);
  const ok = boot.result.exitCode === 0 && reply !== null && reply !== '';
  const expected = reply !== null && /\bok\b/i.test(reply);
  const detail = ok
    ? `exit 0, assistant text ${JSON.stringify(reply.slice(0, 200))}, ${boot.result.durationMs} ms` +
      `; the exact command: ${boot.result.command}` + (expected ? ' (contains the requested token OK)' : ' (does not contain the requested token OK)') +
      `; ${credentialProvenance(credential)}`
    : `no assistant text: exit ${boot.result.exitCode}${boot.result.timedOut ? ' (TIMED OUT)' : ''}, ` +
      `${(boot.result.stdout || '').length} stdout bytes, ${(boot.result.stderr || '').length} stderr bytes; ` +
      `verbatim stderr saved in ${boot.evidence}` + (boot.result.error ? `; spawn error: ${boot.result.error}` : '') +
      `; ${credentialProvenance(credential)}`;
  g('G5', { ran: true, ok, exitCode: boot.result.exitCode, durationMs: boot.result.durationMs, evidence: boot.evidence, detail });
}

/* ------------------------------------------------------------------ G8: the session-format one-way door (SPEC C8) */

/** `codecs: [releasedV0SessionFormatCodec, …]` with the line the reading came from. */
function catalogLines(scope, cat) {
  const rel = (p) => path.relative(scope, p).split(path.sep).join('/');
  const lines = [];
  lines.push(`package: ${rel(path.join(scope, 'dsh-session-format-catalog', 'lib', 'index.js'))}` +
    (cat.manifestVersion ? ` (@deepseek-ai/dsh-session-format-catalog@${cat.manifestVersion})` : ''));
  lines.push(`  currentVersion: ${cat.currentVersion ?? '(not declared)'}`);
  lines.push(`  codecs:        ${cat.codecs.length ? cat.codecs.map((v) => `releasedV${v}SessionFormatCodec`).join(', ') : '(none declared)'}`);
  lines.push(`  currentEncoder:${cat.currentEncoder === null ? ' (not declared)' : ` releasedV${cat.currentEncoder}SessionFormatCodec`}`);
  lines.push(`  migrations:    ${cat.migrations.length ? cat.migrations.map((m) => `v${m.from}->v${m.to}`).join(', ') : '(none declared)'}`);
  const others = cat.formatPackages.filter((p) => p.name !== '@deepseek-ai/dsh-session-format-catalog');
  lines.push(`  sibling @deepseek-ai/dsh-session-format-* packages (${others.length}): ` +
    (others.length ? others.map((p) => `${p.name}@${p.version ?? '?'}`).join(', ') : '(none)'));
  return lines.join('\n');
}

/** One human line naming an install, used in the gate detail. */
function nameInstall(cat, fallback) {
  return cat.ok
    ? `currentVersion ${cat.currentVersion ?? '(not declared)'} (${cat.scope})`
    : `${fallback}: NOT INSPECTED — ${cat.reason}`;
}

/**
 * Whether a codec version is backed by a sibling `@deepseek-ai/dsh-session-format-vN` package.
 *
 * This is deliberately reported as *is a package present for this generation*, not as *this is the
 * module the catalog imports it from*: the generated catalog imports the codec for gen N from the
 * `…-format-vN-1-to-vN` migration package, so attributing a codec to a module by name would be a
 * guess. What matters here is that the codec and its package are really installed.
 */
function codecProvenance(cat) {
  const backed = [];
  const catalogOnly = [];
  const installed = new Set((cat.formatPackages ?? []).map((p) => String(p.name).replace(/^@deepseek-ai\//, '')));
  for (const v of cat.codecs) {
    if (installed.has(`dsh-session-format-v${v}`) || [...installed].some((n) => n.startsWith(`dsh-session-format-v${v}-to-v`))) backed.push(v);
    else catalogOnly.push(v);
  }
  return { backed, catalogOnly };
}

function gateG8({ version, base, cand, snap, g }) {
  const candVersion = cand.ok ? Math.max(cand.currentVersion ?? cand.highestCodec ?? -1, cand.highestCodec ?? -1) : null;
  const candWrites = cand.ok ? cand.currentEncoder : null;
  const { backed, catalogOnly } = cand.ok ? codecProvenance(cand) : { backed: [], catalogOnly: [] };
  const codecAttribution =
    `codec(s) ${cand.ok && cand.codecs.length ? cand.codecs.map((v) => `v${v}`).join(', ') : '(none declared)'}` +
    `; generations with a sibling @deepseek-ai/dsh-session-format-* package installed: ${backed.length ? backed.map((v) => `v${v}`).join(', ') : 'none'}` +
    `; generations with no such package installed: ${catalogOnly.length ? catalogOnly.map((v) => `v${v}`).join(', ') : 'none'}`;
  const liveVersions = snap.ok ? Object.keys(snap.byVersion).map(Number).sort((a, b) => a - b) : [];
  const liveFormats = snap.ok ? (snap.total > 0 ? liveVersions : []) : null;

  /* An observed count and an unobserved count are different facts; never print 0 for a walk not made. */
  const observedAt = snap.newestMtime ?? null;
  const sessionsLine = snap.ok
    ? `${snap.total} session file(s) in ${snap.dir} by name: ${formatCounts(snap.byVersion, 'version') || '(none)'}` +
      `; file names: ${formatCounts(snap.byName, 'name') || '(none)'}` +
      `; mtime range ${snap.oldestMtime ?? '?'} .. ${snap.newestMtime ?? '?'}` + `; walked ${snap.walked ? 'fully' : 'NOT FULLY'}`
    : `NOT OBSERVED — ${snap.reason}`;

  const evidence = writeEvidence(`verify-${version}-G8.txt`, [
    `candidate version argument: ${version}`,
    `candidate engine root: ${cand.installRoot}`,
    '',
    '=== candidate session-format catalog (read from disk, verbatim values) ===',
    cand.ok ? catalogLines(cand.scope, cand) : `NOT INSPECTED — ${cand.reason}`,
    '',
    '=== baseline (pinned) engine session-format catalog ===',
    base.ok ? `root: ${base.installRoot}\n${catalogLines(base.scope, base)}` : `root: ${base.installRoot}\nNOT INSPECTED — ${base.reason}`,
    '',
    '=== live session files (names only; no session file was opened) ===',
    sessionsLine,
    snap.ok && snap.walkErrors.length > 0 ? `walk errors: ${snap.walkErrors.slice(0, 20).join(' | ')}` : null,
    '',
    'the physical artifacts were counted by NAME only (the engine\'s own canonical rule: `session.jsonl` is',
    'generation 0, `session.vN.jsonl` is generation N, plus an optional compression suffix).',
  ].filter((l) => l !== null).join('\n') + '\n');

  if (!cand.ok) {
    g('G8', {
      ran: false, ok: false, evidence,
      detail: `the candidate's session-format catalog could not be read (${cand.reason}), so this gate did not run; ` +
        `whether ${version} writes a newer session format than the live logs is UNKNOWN. ` +
        `live session files: ${snap.ok ? `${snap.total} (${formatCounts(snap.byVersion, 'version')})` : `NOT OBSERVED — ${snap.reason}`}`,
    });
    return { candVersion: null, candWrites: null, liveVersions, oneWayDoor: null };
  }
  if (!snap.ok) {
    g('G8', {
      ran: false, ok: false, evidence,
      detail: `the live session files could not be counted (${snap.reason}), so there is no observed live format to compare ` +
        `against — this gate did not run. The candidate declares currentVersion ${cand.currentVersion ?? '?'}` +
        `${cand.currentEncoder !== null ? ` and writes v${cand.currentEncoder}` : ''}; that reading is in the evidence file.`,
    });
    return { candVersion, candWrites, liveVersions: null, oneWayDoor: null };
  }

  const downForTarget = (target) => cand.downMigrations.filter((m) => m.to === target && cand.canRead(m.from));
  const newerOnDisk = liveFormats.filter((v) => v > candVersion);

  if (liveFormats.length === 0) {
    g('G8', {
      ran: true, ok: false, evidence,
      detail: `no session file was found under ${snap.dir} (${snap.total} name(s) matched the engine's own canonical ` +
        `session-log rule, walked ${snap.walked ? 'fully' : 'not fully'}), so there is no observed live format to compare ` +
        `against and this gate cannot pass: an empty result is a refusal, not health. ` +
        `The candidate declares currentVersion ${cand.currentVersion ?? '?'}` +
        `${cand.currentEncoder !== null ? `, writes v${cand.currentEncoder}` : ''}, codecs ${cand.codecs.map((v) => `v${v}`).join('/') || '(none)'}.`,
    });
    return { candVersion, candWrites, liveVersions, oneWayDoor: null };
  }

  const sameAsLive = liveFormats.every((v) => v === candVersion);
  const writesNewer = liveFormats.every((v) => candVersion > v);
  const canReadAll = liveFormats.every((v) => cand.canRead(v));
  const unreadable = liveFormats.filter((v) => !cand.canRead(v));

  const reasons = [];
  let oneWayDoor = false;
  if (unreadable.length > 0) {
    reasons.push(`the candidate ships NO codec for session format(s) ${unreadable.map((v) => `v${v}`).join(', ')}, which is ` +
      `what is on disk in the live home right now: this engine could not read ${snap.total} existing session file(s) at all`);
  }
  if (sameAsLive) {
    reasons.push(`the candidate writes v${candWrites}, the same format as every one of the ${snap.total} live session file(s) — ` +
      `a rollback finds logs the older engine reads`);
  } else if (writesNewer) {
    oneWayDoor = true;
    /* the codec that would make rolling back *safe* reads back from what the candidate WRITES */
    const covering = downForTarget(candWrites);
    const forward = cand.migrations.filter((m) => liveFormats.includes(m.from) && m.to >= candWrites);
    reasons.push(`the candidate declares currentVersion ${candVersion} and writes v${candWrites}, NEWER than the ` +
      `${liveFormats.map((v) => `v${v}`).join('/')} on disk: this is a ONE-WAY DOOR. Rolling back to the older engine after ` +
      `this engine has written logs leaves every session written in the meantime UNREADABLE by the older engine`);
    if (covering.length > 0) {
      reasons.push(`NOTE: the candidate also ships ${covering.map((m) => `@deepseek-ai/dsh-session-format-v${m.from}-to-v${m.to}`).join(', ')}, ` +
        `so a NEWER engine could read the older logs — but the direction that protects a rollback is the reverse one ` +
        `(v${candWrites} back to v${liveFormats.join('/')}), and that codec is not shipped`);
    } else if (forward.length > 0) {
      reasons.push(`the only new-format codec shipped is ${forward.map((m) => `v${m.from}->v${m.to}`).join(', ')}, which ` +
        `CONSUMES the older logs into the newer format: the same loss read from the other end, since after it runs the older ` +
        `engine cannot read the result either`);
    } else {
      reasons.push(`no new-format codec is shipped at all: the door is one-way in both directions`);
    }
  } else {
    reasons.push(`the candidate declares currentVersion ${candVersion}, which is neither strictly newer than every live ` +
      `format nor equal to it (live: ${liveFormats.map((v) => `v${v}`).join(', ')}) — this gate does not know this shape and will not guess`);
  }
  if (newerOnDisk.length > 0) {
    reasons.push(`NOTE: ${newerOnDisk.map((v) => `v${v}`).join(', ')} session log(s) already exist on disk and are NEWER than the ` +
      `candidate's own v${candVersion}: this candidate could not read the newest history`);
  }
  reasons.push(canReadAll
    ? `the candidate CAN read every format present on disk (codecs v${cand.codecs.join(', v')})`
    : `the candidate CANNOT read every format present on disk`);

  const downMigrationEvidence = cand.downMigrations.length === 0
    ? `no down-migration codec (vX->vY with Y < X) is shipped by this install, so nothing can convert the candidate's own output back for an older engine`
    : `down-migration codec(s) shipped: ${cand.downMigrations.map((m) => `v${m.from}->v${m.to}`).join(', ')}`;
  reasons.push(downMigrationEvidence);

  /* `ok` is exactly the SPEC test: the candidate writes the SAME format as the live logs. That is the only
   * shape in which a rollback is guaranteed to find readable history. A newer format is `ok:false` even when
   * a codec covers it, because nothing here proves the older engine would apply it — and the reverse codec
   * is what is missing. A gate that did not run is `ran:false, ok:false` above. */
  const ok = sameAsLive && unreadable.length === 0;
  const detail =
    `candidate declares currentVersion ${candVersion}` +
    `${cand.currentEncoder !== null ? `, writes v${candWrites}` : ', writes v?'} ` +
    `(${codecAttribution})` +
    `; baseline declares ${base.ok ? `currentVersion ${base.currentVersion ?? '?'}, codecs ${base.codecs.map((v) => `v${v}`).join(', ') || 'none'}` : `UNREADABLE — ${base.reason}`}` +
    `; live logs: ${snap.total} file(s), ${formatCounts(snap.byVersion, 'version')}` +
    `. ${reasons.join('; ')}.` +
    ` (catalog read from ${cand.catalogFile}${observedAt ? `; newest live session file mtime ${observedAt}` : ''})`;

  g('G8', {
    ran: true, ok, exitCode: null, durationMs: null, evidence, detail,
  });
  return { candVersion, candWrites, liveVersions, oneWayDoor };
}

/* ------------------------------------------------------------------ --full web boot */

function otherDshWebProcesses() {
  const ps = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const r = spawnSync(ps, ['-NoProfile', '-NonInteractive', '-Command',
    "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | ForEach-Object { $_.CommandLine } | Where-Object { $_ -match 'dsh' }"],
  { encoding: 'utf8', timeout: 60000, windowsHide: true });
  if (r.status !== 0 || typeof r.stdout !== 'string') {
    return { checked: false, reason: `could not enumerate node processes (exit ${r.status}, ${String(r.error ?? r.stderr ?? '').slice(0, 200)})`, lines: [] };
  }
  const lines = r.stdout.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    .filter((l) => /(?:^|[\s"'\\/])dsh(?:\.js)?["']?\s+web\b/.test(l) || /bin\.js"?\s+web\b/.test(l) || /--profile\s+web\b/.test(l));
  return { checked: true, lines };
}

function portFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

async function gateFull({ version, enginePath, home, cwd, g, extraEnv }) {
  const others = otherDshWebProcesses();
  let port = null;
  for (let p = 3400; p <= 3500; p++) {
    if (await portFree(p)) { port = p; break; }
  }
  const preflight = [
    `other dsh web processes: ${others.checked ? (others.lines.length === 0 ? '(none)' : `\n${others.lines.join('\n')}`) : `CHECK FAILED: ${others.reason}`}`,
    `port chosen: ${port ?? '(none free in 3400-3500)'}`,
    `isolated home: ${home}`,
  ].join('\n');
  if (port === null) {
    const evidence = writeEvidence(`verify-${version}-GFULL.txt`, `${preflight}\n\nno free port, nothing started\n`);
    g('GFULL', { ran: false, ok: false, evidence, detail: 'no free port in 3400-3500; nothing was started' });
    return;
  }
  const conflicts = others.lines.filter((l) => l.includes(String(port)) || l.toLowerCase().includes(home.toLowerCase()));
  if (!others.checked || conflicts.length > 0) {
    const evidence = writeEvidence(`verify-${version}-GFULL.txt`, `${preflight}\n\nREFUSED before starting anything\n`);
    g('GFULL', {
      ran: false, ok: false, evidence,
      detail: !others.checked
        ? `refused: could not prove no other dsh web is running (${others.reason})`
        : `refused: an existing dsh web process conflicts with this boot: ${conflicts.join(' | ')}`,
    });
    return;
  }

  const logFile = path.join(LOGS, `verify-${version}-GFULL.engine.log`);
  fs.mkdirSync(LOGS, { recursive: true });
  const out = fs.openSync(logFile, 'w');
  const startedAt = iso();
  const t0 = Date.now();
  const child = spawn(process.execPath, [enginePath, 'web', '--port', String(port), '--no-open'], {
    env: { ...process.env, DSH_HOME: home, ...(extraEnv ?? {}) }, cwd, windowsHide: true, stdio: ['ignore', out, out],
  });
  const pid = child.pid;
  let exit = null;
  child.on('exit', (code) => { exit = code; });
  let answered = false;
  let lastError = null;
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    if (exit !== null) break;
    try {
      const ok = await new Promise((resolve) => {
        const req = net.connect({ host: '127.0.0.1', port }, () => { req.destroy(); resolve(true); });
        req.on('error', (e) => { lastError = e.code; resolve(false); });
        req.setTimeout(3000, () => { req.destroy(); resolve(false); });
      });
      if (ok) { answered = true; break; }
    } catch (e) { lastError = String(e); }
    await new Promise((r) => setTimeout(r, 750));
  }
  const durationMs = Date.now() - t0;
  let killResult = 'not killed — the process had already exited';
  if (exit === null && pid) {
    const k = spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { encoding: 'utf8', windowsHide: true, timeout: 30000 });
    killResult = `taskkill /PID ${pid} /T /F -> exit ${k.status}: ${String(k.stdout ?? '').trim() || String(k.stderr ?? '').trim()}`;
    try { child.kill('SIGKILL'); } catch { /* already gone */ }
  }
  try { fs.closeSync(out); } catch { /* ignore */ }

  const engineLog = fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8') : '';
  const evidence = writeEvidence(`verify-${version}-GFULL.txt`, [
    preflight,
    `command: node ${enginePath} web --port ${port} --no-open`,
    `pid: ${pid}`, `startedAt: ${startedAt}`, `durationMs: ${durationMs}`,
    `answered on 127.0.0.1:${port}: ${answered ? 'yes' : 'no'}`, `process exited during the wait: ${exit === null ? 'no' : `yes (${exit})`}`,
    `last connect error: ${lastError ?? 'none'}`, killResult,
    '', '=== engine stdout+stderr (verbatim) ===', engineLog,
  ].join('\n') + '\n');
  const ok = answered && exit === null;
  g('GFULL', {
    ran: true, ok, exitCode: exit, durationMs, evidence,
    detail: ok
      ? `web profile booted on 127.0.0.1:${port} in ${durationMs} ms (pid ${pid}); ${killResult}; a web boot spawns the MCP bridges and costs real memory, which is why it is opt-in`
      : `web profile did NOT answer on 127.0.0.1:${port}${exit !== null ? ` (process exited ${exit})` : ' within 90000 ms'}${lastError ? `; last connect error ${lastError}` : ''}; ${killResult}`,
  });
}

/* ------------------------------------------------------------------ main */

async function main(argvInput = process.argv.slice(2)) {
  let parsed;
  try {
    parsed = parseArgs(argvInput);
  } catch (err) {
    process.stderr.write(`verify: ${err.message}\n\n${USAGE}\n`);
    return 2;
  }
  if (parsed.help) { process.stdout.write(`${USAGE}\n`); return 0; }
  const { flags } = parsed;
  const version = String(flags['--version']);
  const full = Boolean(flags['--full']);
  const noBoot = Boolean(flags['--no-boot']);
  const turnTimeout = flags['--turn-timeout'] ? Number(flags['--turn-timeout']) : 240000;
  if (!Number.isFinite(turnTimeout) || turnTimeout <= 0) {
    process.stderr.write('verify: --turn-timeout must be a positive number of milliseconds\n');
    return 2;
  }

  const { gate, finish } = makeGates();
  const notes = [];

  /* the dispatcher passes --dsh-home and --logs-dir; honour them for this run */
  if (flags['--dsh-home']) {
    const requested = path.resolve(flags['--dsh-home']);
    if (!fs.existsSync(requested)) {
      process.stderr.write(`verify: --dsh-home "${requested}" does not exist\n`);
      return 2;
    }
    LIVE_HOME = requested;
  }
  if (flags['--logs-dir']) LOGS = path.resolve(flags['--logs-dir']);

  let engine;
  try {
    engine = resolveEngine(version, flags['--prefix'], flags['--engine']);
  } catch (err) {
    process.stderr.write(`verify: ${err.message}\n`);
    return 2;
  }
  const contractPath = flags['--contract'] ? path.resolve(flags['--contract']) : path.join(STATE, 'candidates', version, 'contract.json');
  const contractSha256 = sha256File(contractPath);
  const treeArgPath = flags['--tree'] ? path.resolve(flags['--tree']) : null;

  if (!engine.enginePath) {
    notes.push(`no engine for ${version} could be resolved (looked for --engine, --prefix, vendor/prefix/${version}, state/pin.json, DSH_INSTALL, and the npx cache). Nothing was run.`);
    const gates = finish();
    const out = {
      schemaVersion: 1, generatedAt: generatedAt(flags), version, contractSha256,
      pass: false, complete: false, gates, notes,
    };
    emit(out, flags['--out']);
    return 0;
  }

  const manifest = dshManifest(engine.enginePath);
  notes.push(`engine for ${version}: ${engine.enginePath} (source: ${engine.source}); manifest @deepseek-ai/dsh@${manifest.version ?? '?'}${manifest.version && String(manifest.version) !== version ? ` — WARNING: the resolved engine reports ${manifest.version}, not ${version}` : ''}`);
  if (contractSha256 === null) notes.push(`the contract at ${contractPath} is absent, so contractSha256 is null and promote must refuse this verify`);
  else notes.push(`contractSha256 ${contractSha256} read from ${contractPath}`);
  if (flags['--diff']) notes.push(`the dispatcher also passed --diff ${path.resolve(flags['--diff'])}; the gates do not consume diff.json, it is recorded here so nothing passed in is silently dropped`);

  /* ---- the model credential (SPEC C14) ----------------------------------------------------------
   * Resolved from the LIVE home at gate time and passed into the child ENVIRONMENT. It is never
   * copied into the isolated home, never written to state/logs/ (plain text, live secret), never
   * printed, never serialised into verify.json: only its presence and its length are reportable.
   * --------------------------------------------------------------------------------------------- */
  const credential = resolveCredential(LIVE_HOME);
  const extraEnv = credential.ok ? { [credential.key]: credential.value } : null;
  if (credential.ok) {
    /* the value is dropped from the object as soon as the child environment has it: everything that
     * reports on it downstream can only see its length */
    credential.valueLength = credential.value.length;
    delete credential.value;
  }
  notes.push(credential.ok
    ? `model credential: ${credential.key} resolved from the LIVE ${credential.file} and passed to the boot children through the ENVIRONMENT only ` +
      `(present: yes; ${credential.valueLength} characters; sha256 of the credentials file ${credential.sha256}). It is NEVER written into the isolated home, ` +
      `NEVER written to state/logs/, NEVER printed and NEVER recorded in verify.json.`
    : `model credential: could NOT be resolved (${credential.reason}). G4/G5 were not passed a credential, so they are ran:false; nothing was written that contains a secret.`);

  /* ---- isolated home ---- */
  const candidateDir = path.join(STATE, 'candidates', version);
  const home = path.join(candidateDir, 'home');
  const cwd = path.join(candidateDir, 'cwd');
  /* .credentials.yaml is deliberately NOT in this list: it is a live secret and the credential reaches
   * the engine through the environment instead (SPEC C14). Copying it is what this change removes. */
  const srcs = ['settings.yaml', 'profiles', '.agent-presets'];
  const liveSize = {};
  for (const s of srcs) liveSize[s] = measure(path.join(LIVE_HOME, s));
  const copyStats = { files: 0, bytes: 0, links: 0, dirs: 0, copiedLinks: 0, replacedLinks: 0, linkTargetsLeftAsDirs: 0 };
  const copyStart = Date.now();
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(cwd, { recursive: true });
  for (const s of srcs) {
    const src = path.join(LIVE_HOME, s);
    if (!fs.existsSync(src)) { notes.push(`isolated home: ${src} does not exist and was not copied`); continue; }
    copyTree(src, path.join(home, s), copyStats);
  }
  const copyMs = Date.now() - copyStart;
  const homeSize = measure(home);
  const credInHome = path.join(home, CREDENTIAL_BASENAME);
  if (fs.existsSync(credInHome)) {
    /* written by an EARLIER run of this module, before the credential moved to the environment. This
     * module never deletes anything, so it is reported rather than removed — a human decides. */
    notes.push(`WARNING: ${credInHome} exists, written by an earlier run that copied it. This run did NOT write it and did not remove it ` +
      `(nothing in this pipeline deletes anything). Nothing under state/candidates/** is committed today; a human should decide whether to remove it.`);
  }
  notes.push(`isolated DSH_HOME: ${home}`);
  notes.push(`live source size: ${srcs.map((s) => `${s} ${liveSize[s].files} files/${liveSize[s].bytes} bytes/${liveSize[s].links} links`).join(', ')}`);
  notes.push(`isolated copy: ${copyStats.files} files/${copyStats.bytes} bytes, ${copyStats.links} links preserved (${copyStats.replacedLinks} re-pointed from an earlier run)${copyStats.copiedLinks > 0 ? `, ${copyStats.copiedLinks} file link(s) copied as bytes: no privilege to create file symlinks` : ''}${copyStats.linkTargetsLeftAsDirs > 0 ? `, ${copyStats.linkTargetsLeftAsDirs} destination(s) were already real directories and were left as they are` : ''}, ${copyMs} ms on disk (${homeSize.files} files/${homeSize.bytes} bytes/${homeSize.links} links re-measured)`);
  notes.push(`${CREDENTIAL_BASENAME} is NOT copied into the isolated home and is NOT written anywhere by this module: the model credential reaches the engine ` +
    `through the child process ENVIRONMENT only (SPEC C14). Nothing this run wrote contains a secret. state/candidates/** must never be committed (dsh-update/ is untracked in harness-config today).`);

  /* ---- G1 ---- */
  const g1 = gateG1({ version, enginePath: engine.enginePath, home, cwd, g: gate, extraEnv });

  /* ---- inputs and G2/G3 ---- */
  const patch = patchTargets(version, flags['--consumed']);
  const bundleInfo = profileBundles('web');
  const treeArtifactPath = treeArgPath ?? path.join(candidateDir, 'tree.json');
  const treeArtifact = readJsonIfPresent(treeArtifactPath);
  if (!treeArtifact) notes.push(`no tree artifact was supplied or found at ${treeArtifactPath}; G2/G3 read the dump G1 just produced`);
  const treeChoice = treeForGates({ g1, artifact: treeArtifact, artifactPath: treeArtifactPath });
  if (treeChoice.note) notes.push(treeChoice.note);
  if (treeChoice.crossCheck) {
    notes.push(`tree cross-check: the supplied artifact and the fresh dump ${treeChoice.crossCheck.agreeRows ? 'agree on the row count' : 'DISAGREE on the row count'} and ${treeChoice.crossCheck.agreePatched ? 'agree on patchedRowIds' : 'DISAGREE on patchedRowIds'}`);
  }
  gateG2({ version, tree: treeChoice.used, targets: patch.targets, patchSource: patch.source ?? patch.error, treeNote: treeChoice.note, g: gate });
  gateG3({ version, tree: treeChoice.used, bundles: bundleInfo.bundles, bundleSource: bundleInfo.source ?? bundleInfo.error, treeNote: treeChoice.note, g: gate });

  /* ---- G4/G5 ---- */
  if (noBoot) {
    gate('G4', { ran: false, ok: false, detail: '--no-boot: the settings document is only read by a real boot, so this gate did not run (--dump-config cannot decide it)' });
    gate('G5', { ran: false, ok: false, detail: '--no-boot: no engine turn was run' });
  } else if (!extraEnv) {
    const why = `the model credential could not be resolved from the LIVE ${credential.file} (${credential.reason}), and nothing was written to make it available: an engine booted without it fails with MISSING_CREDENTIAL, so this gate is ran:false rather than a fabricated pass (SPEC C14)`;
    gate('G4', { ran: false, ok: false, detail: why });
    gate('G5', { ran: false, ok: false, detail: why });
    notes.push(`G4/G5 did not run: ${why}`);
  } else {
    const headlessDump = runEngine({
      enginePath: engine.enginePath, args: ['--profile', 'headless', '--dump-config'], home, cwd, timeoutMs: 120000,
      label: `verify-${version}-G4-dump.txt`, extraEnv,
    });
    const boot = runEngine({
      enginePath: engine.enginePath, args: ['--profile', 'headless', 'Reply with the single word OK.'], home, cwd, timeoutMs: turnTimeout,
      label: `verify-${version}-G5.txt`, extraEnv,
    });
    const combined = [
      headlessDump.result.stderr, headlessDump.result.stdout,
      boot.result.stderr, boot.result.stdout,
    ].join('\n');
    gateG4({ version, headlessDump, boot, diagnostics: scanSettingsDiagnostics(combined), g: gate, credential });
    gateG5({ version, boot, g: gate, credential });
    notes.push(`G4 limitation: ${MEASURED_SETTINGS_LIMITATION}`);
    if (headlessDump.result.exitCode !== 0) {
      notes.push(`the headless --dump-config used by G4 exited ${headlessDump.result.exitCode}; its verbatim output is in ${headlessDump.evidence}`);
    }
  }

  /* ---- --full ---- */
  if (!full) {
    gate('GFULL', { ran: false, ok: false, detail: 'not requested (pass --full to boot the web profile on a free port in 3400-3500 and kill only the pid this module started)' });
  } else if (!extraEnv) {
    gate('GFULL', { ran: false, ok: false, detail: `refused before starting anything: the model credential could not be resolved from ${credential.file} (${credential.reason}), and a web boot without it fails with MISSING_CREDENTIAL` });
  } else {
    await gateFull({ version, enginePath: engine.enginePath, home, cwd, g: gate, extraEnv });
  }

  /* ---- G8: the session-format one-way door (SPEC C8) ----
   * Reads the real catalog files from BOTH installs and counts the live session files by name only.
   * It needs no engine run, so --no-boot does not skip it. */
  const baselineArg = flags['--baseline-engine']
    ? path.resolve(flags['--baseline-engine'])
    : (readJsonIfPresent(path.join(STATE, 'pin.json'))?.enginePath ?? null);
  const baselineCatalog = baselineArg
    ? readSessionFormatCatalog(baselineArg)
    : { ok: false, installRoot: null, reason: 'no pinned engine: state/pin.json carries no enginePath and --baseline-engine was not given' };
  const candidateCatalog = readSessionFormatCatalog(engine.enginePath);
  const sessionsDir = flags['--sessions-dir'] ? path.resolve(flags['--sessions-dir']) : path.join(LIVE_HOME, 'sessions');
  const snap = snapshotSessionFormats(sessionsDir);
  notes.push(`G8 baseline install: ${baselineArg ?? '(none)'} — ${nameInstall(baselineCatalog, 'baseline session-format catalog')}`);
  notes.push(`G8 candidate install: ${engine.enginePath} — ${nameInstall(candidateCatalog, 'candidate session-format catalog')}`);
  notes.push(`G8 live session files: ${snap.ok ? `${snap.total} file(s) under ${snap.dir}, by name ${formatCounts(snap.byVersion, 'version') || '(none)'}` : `NOT COUNTED — ${snap.reason}`}`);
  gateG8({ version, base: baselineCatalog, cand: candidateCatalog, snap, g: gate });

  const gates = finish();
  const ran = gates.filter((g) => g.ran);
  const bootGatesRan = ['G4', 'G5'].every((id) => gates.find((g) => g.id === id)?.ran === true);
  // SPEC: "pass is true only when every gate with ran:true has ok:true". That is a necessary
  // condition, and it is read here as such: a verification whose boot gates did not run is not a
  // passing verification, because SPEC §5 lets a promote ride on `pass`.
  const pass = ran.length > 0 && ran.every((g) => g.ok) && bootGatesRan;
  if (ran.length === 0) notes.push('no gate ran, so pass is false by construction: an empty verification is a refusal, not a pass');
  if (!bootGatesRan) notes.push('pass is false because G4/G5 did not run: a verification with no boot must never gate a promote (SPEC §5 keys a promote on pass)');
  const complete = ran.length > 0 && ran.every((g) => g.ok) && bootGatesRan;
  notes.push(`gates: ${gates.map((g) => `${g.id} ${g.ran ? (g.ok ? 'ok' : 'FAIL') : 'not-run'}`).join(', ')}`);
  const out = { schemaVersion: 1, generatedAt: generatedAt(flags), version, contractSha256, pass, complete, gates, notes };
  emit(out, flags['--out']);
  return 0;
}

function emit(out, outPath) {
  const text = JSON.stringify(out, null, 2) + '\n';
  if (outPath) {
    const target = path.resolve(outPath);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const tmp = `${target}.tmp-${process.pid}`;
    fs.writeFileSync(tmp, text);
    fs.renameSync(tmp, target);
  }
  process.stdout.write(text);
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (isMain) {
  main().then((code) => { process.exitCode = code; }).catch((err) => {
    process.stderr.write(`verify: unexpected failure: ${err?.stack ?? err}\n`);
    process.exitCode = 1;
  });
}

/**
 * Dispatcher-friendly entry point, for a caller that would rather import than spawn:
 *
 *   verifyVersion({ version, engine, prefix, out, consumed, contract, tree, diff, logsDir, dshHome,
 *                   full, noBoot, turnTimeoutMs, generatedAt })
 *
 * The standalone CLI stays primary (SPEC: every lib module runs standalone); this maps one options
 * object onto the same code path so `lib/cli.mjs` can use either style.
 */
async function verifyVersion(options = {}) {
  const flags = {};
  const map = {
    version: '--version', engine: '--engine', prefix: '--prefix', out: '--out', consumed: '--consumed',
    contract: '--contract', tree: '--tree', diff: '--diff', logsDir: '--logs-dir', dshHome: '--dsh-home',
    turnTimeoutMs: '--turn-timeout', generatedAt: '--generated-at',
  };
  for (const [key, flag] of Object.entries(map)) if (options[key] !== undefined && options[key] !== null) flags[flag] = String(options[key]);
  if (options.full) flags['--full'] = true;
  if (options.noBoot) flags['--no-boot'] = true;
  const argv = [];
  for (const [k, v] of Object.entries(flags)) { if (v === true) argv.push(k); else argv.push(k, v); }
  return main(argv);
}

export {
  parseDump, scanSettingsDiagnostics, resolveEngine, copyTree, measure, otherDshWebProcesses, verifyVersion,
  /* G8 + credential helpers, exported so a canary can exercise them without running a gate */
  readSessionFormatCatalog, snapshotSessionFormats, resolveCredential, findCredentialValue,
};

