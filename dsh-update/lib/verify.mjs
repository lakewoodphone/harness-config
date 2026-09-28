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
];

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
                          [--full] [--no-boot] [--turn-timeout <ms>] [--generated-at <ISO-8601>]

Runs the five dsh-update gates against an isolated copy of DSH_HOME (state/candidates/<ver>/home),
saving the verbatim output of every engine invocation under --logs-dir (default state/logs/).
--no-boot skips G4/G5. --full adds a real web-profile boot on a free port in 3400-3500, killed by
pid immediately after. Exit 0 when the gates completed (pass tells you whether they were ok);
non-zero on a usage or infrastructure failure, with the diagnostic on stderr.

The dispatcher (lib/cli.mjs) calls this module with --engine/--contract/--tree/--diff/--logs-dir/
--dsh-home, so those flags are part of the interface: --engine is the candidate bin.js, --contract is
the artifact its sha256 is recorded from, and --tree is the candidate tree used for G2/G3 (the dump
G1 just produced is always parsed too and any disagreement is reported).`;

class UsageError extends Error {}

/* ------------------------------------------------------------------ arguments */

const VALUED_FLAGS = new Set([
  '--version', '--prefix', '--engine', '--out', '--consumed', '--contract', '--tree', '--diff',
  '--logs-dir', '--dsh-home', '--turn-timeout', '--generated-at',
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

function runEngine({ enginePath, args, home, cwd, timeoutMs, label }) {
  const env = { ...process.env, DSH_HOME: home };
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

function gateG1({ version, enginePath, home, cwd, g }) {
  const { result, evidence } = runEngine({
    enginePath, args: ['--profile', 'web', '--dump-config'], home, cwd, timeoutMs: 120000,
    label: `verify-${version}-G1.txt`,
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

function gateG4({ version, headlessDump, boot, diagnostics, g }) {
  const scannedBytes = (headlessDump.result.stdout || '').length + (headlessDump.result.stderr || '').length +
    (boot.result.stdout || '').length + (boot.result.stderr || '').length;
  const evidence = writeEvidence(`verify-${version}-G4.txt`, [
    `settings document scanned: ${path.join(LIVE_HOME, 'settings.yaml')} (copied into the isolated home)`,
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
  ].join('\n') + '\n');
  const dumpOk = headlessDump.result.exitCode === 0;
  const bootOk = boot.result.exitCode === 0;
  const ok = dumpOk && bootOk && diagnostics.length === 0;
  const parts = [];
  parts.push(`headless --dump-config exit ${headlessDump.result.exitCode}`);
  parts.push(`boot exit ${boot.result.exitCode}`);
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

function gateG5({ version, boot, g }) {
  const reply = extractAssistantText(boot.result.stdout);
  const ok = boot.result.exitCode === 0 && reply !== null && reply !== '';
  const expected = reply !== null && /\bok\b/i.test(reply);
  const detail = ok
    ? `exit 0, assistant text ${JSON.stringify(reply.slice(0, 200))}, ${boot.result.durationMs} ms` +
      `; the exact command: ${boot.result.command}` + (expected ? ' (contains the requested token OK)' : ' (does not contain the requested token OK)')
    : `no assistant text: exit ${boot.result.exitCode}${boot.result.timedOut ? ' (TIMED OUT)' : ''}, ` +
      `${(boot.result.stdout || '').length} stdout bytes, ${(boot.result.stderr || '').length} stderr bytes; ` +
      `verbatim stderr saved in ${boot.evidence}` + (boot.result.error ? `; spawn error: ${boot.result.error}` : '');
  g('G5', { ran: true, ok, exitCode: boot.result.exitCode, durationMs: boot.result.durationMs, evidence: boot.evidence, detail });
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

async function gateFull({ version, enginePath, home, cwd, g }) {
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
    env: { ...process.env, DSH_HOME: home }, cwd, windowsHide: true, stdio: ['ignore', out, out],
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

  /* ---- isolated home ---- */
  const candidateDir = path.join(STATE, 'candidates', version);
  const home = path.join(candidateDir, 'home');
  const cwd = path.join(candidateDir, 'cwd');
  const srcs = ['settings.yaml', 'profiles', '.agent-presets', '.credentials.yaml'];
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
  notes.push(`isolated DSH_HOME: ${home}`);
  notes.push(`live source size: ${srcs.map((s) => `${s} ${liveSize[s].files} files/${liveSize[s].bytes} bytes/${liveSize[s].links} links`).join(', ')}`);
  notes.push(`isolated copy: ${copyStats.files} files/${copyStats.bytes} bytes, ${copyStats.links} links preserved (${copyStats.replacedLinks} re-pointed from an earlier run)${copyStats.copiedLinks > 0 ? `, ${copyStats.copiedLinks} file link(s) copied as bytes: no privilege to create file symlinks` : ''}${copyStats.linkTargetsLeftAsDirs > 0 ? `, ${copyStats.linkTargetsLeftAsDirs} destination(s) were already real directories and were left as they are` : ''}, ${copyMs} ms on disk (${homeSize.files} files/${homeSize.bytes} bytes/${homeSize.links} links re-measured)`);
  notes.push('.credentials.yaml is copied into the isolated home only because a headless turn cannot reach a model without it; state/candidates/** must never be committed (dsh-update/ is untracked in harness-config today).');

  /* ---- G1 ---- */
  const g1 = gateG1({ version, enginePath: engine.enginePath, home, cwd, g: gate });

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
  } else {
    const headlessDump = runEngine({
      enginePath: engine.enginePath, args: ['--profile', 'headless', '--dump-config'], home, cwd, timeoutMs: 120000,
      label: `verify-${version}-G4-dump.txt`,
    });
    const boot = runEngine({
      enginePath: engine.enginePath, args: ['--profile', 'headless', 'Reply with the single word OK.'], home, cwd, timeoutMs: turnTimeout,
      label: `verify-${version}-G5.txt`,
    });
    const combined = [
      headlessDump.result.stderr, headlessDump.result.stdout,
      boot.result.stderr, boot.result.stdout,
    ].join('\n');
    gateG4({ version, headlessDump, boot, diagnostics: scanSettingsDiagnostics(combined), g: gate });
    gateG5({ version, boot, g: gate });
    notes.push(`G4 limitation: ${MEASURED_SETTINGS_LIMITATION}`);
    if (headlessDump.result.exitCode !== 0) {
      notes.push(`the headless --dump-config used by G4 exited ${headlessDump.result.exitCode}; its verbatim output is in ${headlessDump.evidence}`);
    }
  }

  /* ---- --full ---- */
  if (!full) {
    gate('GFULL', { ran: false, ok: false, detail: 'not requested (pass --full to boot the web profile on a free port in 3400-3500 and kill only the pid this module started)' });
  } else {
    await gateFull({ version, enginePath: engine.enginePath, home, cwd, g: gate });
  }

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

export { parseDump, scanSettingsDiagnostics, resolveEngine, copyTree, measure, otherDshWebProcesses, verifyVersion };
