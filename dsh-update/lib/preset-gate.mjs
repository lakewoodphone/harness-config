#!/usr/bin/env node
/**
 * preset-gate.mjs — gate G7: resolve every AGENT PRESET row against a candidate install.
 *
 * WHY THIS MODULE EXISTS (SPEC.md C3)
 * -----------------------------------
 * The pipeline's structural detector composes the plugin tree with `dsh --profile web
 * --dump-config` and diffs it. That dump describes the HOST/PROFILE composition only. **Agent
 * presets contribute ZERO rows to it.** Measured 2026-09-23 by set arithmetic: the `zabz` preset
 * has 26 row ids, the host dump has 163, and of the 14 preset-exclusive ids (`persona`, `planning`,
 * `compaction`, `delegation`, `tool-ask-user`, `tool-cordis`, `present`, `mcp-secretary`, …) not one
 * appears in the dump in any form.
 *
 * So a preset row naming a package the new version removed is invisible to the tree diff — and it
 * breaks NEW SESSION CREATION on that preset, with no host-level symptom at all. That is not
 * theoretical: `0.1.7-rc.1` removed `@deepseek-ai/dsh-workflow-worker-thread`, named by all three
 * presets, and removed `@deepseek-ai/dsh-agent-presets` (which OWNS the shipped preset roster).
 * Both were verified absent by direct directory check of the fetched install.
 *
 * This gate is cheap and needs no engine: it reads preset composition files and a contract.json.
 * It never starts, stops or restarts an engine, and it never writes outside `--out`.
 *
 * WHAT IS AUTHORITATIVE HERE
 * --------------------------
 * A preset file's own bytes are file contents, and a contract's `packages` map is manifest data
 * (SPEC §Evidence tiers): both AUTHORITATIVE. A row's `name:` therefore supports a `BREAKS` when
 * the candidate has no such package or no such export subpath. Anything this gate cannot decide
 * from those two artefacts goes to `unverified` — never to a silent pass. A `SAFE` verdict with a
 * populated `unverified` list is honest; a `SAFE` verdict with a silent gap is a lie.
 *
 * WHY THE ROWS ARE READ FROM THE PARSED DOCUMENT AND NOT FROM A LINE REGEX
 * ------------------------------------------------------------------------
 * Every finding must carry a real `file` and `line` and no synthesised line number, and a preset
 * file is mostly prose: the personas are thousands of words of block scalars, and an MCP row's
 * `config:` holds `{ id, name }` server entries that a naive "find every `name:`" scan would report
 * as rows. Measured on this machine: a scan for maps carrying `id` + `name` finds 32 mappings in
 * `cordis-bg` (19 rows + 13 MCP server entries) and 41 in `zabz` (26 rows + 15 server entries),
 * while the true row counts are 19 / 20 / 26. A regex would therefore have invented 13 "missing
 * packages" per file. So: rows are the elements of the document's ROOT SEQUENCE (plus anything
 * under an `insert:`), and each row's line comes from that node's own source range.
 *
 * `!!js` tagged scalars are preserved as source text by `lib/yaml.mjs`'s custom tag. A row whose
 * `name:` is such an expression is reported as undecidable — this module never evaluates engine
 * expressions, and it must not pretend a text scan is a resolution.
 *
 * Usage:
 *   node lib/preset-gate.mjs --candidate-contract <contract.json> [--baseline-contract <c.json>]
 *        [--root <harnessConfigRoot>] [--dsh-home <path>] [--out <preset-gate.json>]
 *        [--profile-name <settingsKey>] [--generated-at <ISO-8601>]
 *
 * With no `--out` the artifact is printed on stdout. Exit 0 on a written artifact; exit 1 when the
 * gate cannot run at all (an unreadable or empty candidate contract, no usable YAML implementation);
 * exit 2 on a usage error.
 */
import { createHash } from 'node:crypto';
import {
  existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync,
} from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCHEMA_VERSION = 1;
const CONFIG_ROOT_DEFAULT = resolve(HERE, '..', '..');

const USAGE = 'usage: node lib/preset-gate.mjs --candidate-contract <contract.json> '
  + '[--baseline-contract <contract.json>] [--root <harnessConfigRoot>] [--dsh-home <path>] '
  + '[--out <preset-gate.json>] [--profile-name <settingsKey>] [--generated-at <ISO-8601>]';

class UsageError extends Error {}

/** Finding classes. P1/P2 come straight from the six breakage classes (B1/B2); P3 and P4 are this
 *  gate's own, and P0 is the "it is ours, an upstream contract cannot judge it" bucket. */
const CLASS = {
  P0: 'P0', // our own package or a relative specifier — INFO, never BREAKS
  P1: 'P1', // package missing from the candidate (B1)
  P2: 'P2', // export subpath missing from the candidate package (B2)
  P3: 'P3', // the default preset name the settings document sets is in no roster
  P4: 'P4', // repo vs live preset drift
};

const SEVERITY_ORDER = { BREAKS: 0, RISKY: 1, CAPABILITY: 2, INFO: 3 };

/**
 * Preset files generated wholesale from another composition. A drift involving one of these is
 * expected between generator runs, so it is reported as INFO with the generator named — never as
 * an error. The mapping is data, read from the generator's own docstring (`scripts/
 * make_zabz_preset.py`: "GENERATED OUTPUT. `presets/zabz/agent.cordis.yml` is rewritten wholesale
 * from … SRC = REPO / "presets" / "cordis-bg" / "agent.cordis.yml"`).
 */
const GENERATED_PRESETS = [
  {
    preset: 'zabz',
    repoRelPath: 'presets/zabz/agent.cordis.yml',
    generatedBy: 'scripts/make_zabz_preset.py',
    from: 'presets/cordis-bg/agent.cordis.yml',
  },
];

// ── arguments ────────────────────────────────────────────────────────────────────────────────
function parseArgs(argv) {
  const args = {
    candidateContract: null,
    baselineContract: null,
    root: null,
    dshHome: null,
    out: null,
    profileKey: 'agent-presets',
    generatedAt: null,
    help: false,
  };
  const rest = [...argv];
  const take = (flag) => {
    const v = rest.shift();
    if (v === undefined) throw new UsageError(`${flag} needs a value`);
    return v;
  };
  while (rest.length > 0) {
    const a = rest.shift();
    const eq = a.startsWith('--') ? a.indexOf('=') : -1;
    const key = eq > 0 ? a.slice(0, eq) : a;
    const inline = eq > 0 ? a.slice(eq + 1) : null;
    const val = (flag) => (inline !== null ? inline : take(flag));
    if (key === '--candidate-contract' || key === '--candidate') args.candidateContract = val(key);
    else if (key === '--baseline-contract' || key === '--baseline') args.baselineContract = val(key);
    else if (key === '--root') args.root = val(key);
    else if (key === '--dsh-home' || key === '--dshHome') args.dshHome = val(key);
    else if (key === '--out') args.out = val(key);
    else if (key === '--profile-name' || key === '--profileName') args.profileKey = val(key);
    else if (key === '--generated-at' || key === '--generatedAt') args.generatedAt = val(key);
    else if (key === '--help' || key === '-h') args.help = true;
    else if (a.startsWith('-')) throw new UsageError(`unknown option ${a}`);
    else throw new UsageError(`unexpected extra argument ${a}`);
  }
  return args;
}

// ── small helpers ────────────────────────────────────────────────────────────────────────────
const toPosix = (p) => p.split(sep).join('/');
const orderByString = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

function sha256(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

/** Byte offsets of every line start, so a parser's character offset becomes a real 1-based line. */
function makeLineIndex(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i += 1) {
    if (text.charCodeAt(i) === 10) starts.push(i + 1);
  }
  return starts;
}

/** The 1-based line containing `offset`, by binary search over the line starts. */
function lineAt(starts, offset) {
  if (!Number.isFinite(offset)) return null;
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= offset) lo = mid; else hi = mid - 1;
  }
  return lo + 1;
}

function readText(abs) {
  return readFileSync(abs, 'utf8');
}

/** A scalar node's text, or null when it is not a plain scalar (an `!!js` wrapper, a map, …). */
function scalarText(value) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function isJsWrapper(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
    && typeof value.__js === 'string';
}

/** A `file` for a location: repo-relative (posix) when inside the config root, else absolute. */
function fileFor(abs, configRoot) {
  const p = resolve(configRoot).toLowerCase();
  const c = resolve(abs).toLowerCase();
  if (c === p || c.startsWith(p + sep.toLowerCase())) return toPosix(relative(configRoot, abs));
  return toPosix(abs);
}

function listDirDirs(dir) {
  const out = [];
  let entries;
  try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return null; }
  for (const e of entries.sort((a, b) => orderByString(a.name, b.name))) {
    if (e.isDirectory()) { out.push(e.name); continue; }
    if (!e.isSymbolicLink()) continue;
    try { if (statSync(join(dir, e.name)).isDirectory()) out.push(e.name); } catch { /* dangling link */ }
  }
  return out;
}

// ── YAML ─────────────────────────────────────────────────────────────────────────────────────
/**
 * `lib/yaml.mjs` resolves a real `yaml` implementation and registers the `!!js` tag. It throws at
 * import time when no implementation can be found, and that is fatal on purpose: without a parser
 * this gate could only pattern-match, and a pattern-matched row is exactly the plausible-but-wrong
 * reading this pipeline exists to prevent. A gate that cannot make the observation says so and
 * exits non-zero; it does not emit a verdict.
 */
let YAML_MOD = null;
let YAML_MOD_ERROR = null;
try {
  YAML_MOD = await import(new URL('./yaml.mjs', import.meta.url).href);
} catch (e) {
  YAML_MOD = null;
  YAML_MOD_ERROR = `lib/yaml.mjs is not importable: ${e.message}`;
}
const PARSE_OPTIONS = YAML_MOD?.PARSE_OPTIONS ?? {};

/** Parse one YAML document, collecting errors and warnings instead of throwing. */
function parseYamlDoc(text) {
  const warnings = [];
  try {
    const doc = YAML_MOD.YAML.parseDocument(text, {
      ...PARSE_OPTIONS,
      onWarning: (w) => warnings.push(String(w?.message ?? w)),
    });
    const errors = (doc?.errors ?? []).map((e) => String(e?.message ?? e));
    return { doc, errors, warnings };
  } catch (e) {
    return { doc: null, errors: [e.message], warnings };
  }
}

// ── contracts ────────────────────────────────────────────────────────────────────────────────
/**
 * Read a contract, and refuse to treat an empty one as an input. SPEC §Safety invariants 8: an
 * empty or failed read is a failure, never an empty success — a contract with no `packages` map
 * would silently declare every preset name "missing", which is a fabricated BREAKS storm.
 */
function readContract(pathArg, label) {
  const abs = resolve(pathArg);
  if (!existsSync(abs)) throw new Error(`${label} contract does not exist: ${abs}`);
  const text = readText(abs);
  let doc;
  try {
    doc = JSON.parse(text);
  } catch (e) {
    throw new Error(`${label} contract ${abs} is not valid JSON: ${e.message}`);
  }
  const packages = doc?.packages;
  if (!packages || typeof packages !== 'object' || Object.keys(packages).length === 0) {
    throw new Error(`${label} contract ${abs} carries no packages map (or an empty one) — an empty `
      + 'contract is a refusal, not an input, and every preset name would be reported missing');
  }
  return {
    path: abs,
    sha256: sha256(text),
    generatedAt: doc.generatedAt ?? null,
    installRoot: doc.installRoot ?? null,
    schemaVersion: doc.schemaVersion ?? null,
    version: doc?.dsh?.version ?? null,
    packageCount: Object.keys(packages).length,
    packages,
  };
}

// ── settings: the default preset name ────────────────────────────────────────────────────────
/**
 * Read `<settingsKey>.default` out of the live settings document, with the REAL line of the
 * `default:` key. The value is read from the parsed document (manifest data) and the line from that
 * key node's own source range, so neither is synthesised; if the document does not parse, the
 * observation could not be made and it is reported as such rather than skipped.
 */
function readDefaultPreset(settingsPath, settingsKey, configRoot) {
  const result = {
    file: fileFor(settingsPath, configRoot),
    path: settingsPath,
    key: settingsKey,
    present: existsSync(settingsPath),
    value: null,
    valueLine: null,
    parseError: null,
    note: null,
  };
  if (!result.present) {
    result.note = `the settings document ${result.file} does not exist, so which preset is the `
      + 'default could not be read';
    return result;
  }
  const text = readText(settingsPath);
  const starts = makeLineIndex(text);
  const { doc, errors } = parseYamlDoc(text);
  if (!doc || errors.length > 0) {
    result.parseError = errors.join(' | ') || 'no document';
    result.note = `${result.file} did not parse as YAML (${result.parseError}), so the default `
      + 'preset name could not be read';
    return result;
  }
  const root = doc.contents;
  if (!root || root.constructor.name !== 'YAMLMap') {
    result.note = `${result.file} root is ${root ? root.constructor.name : 'empty'}, not a mapping, `
      + 'so the default preset name could not be read';
    return result;
  }
  const keyMember = root.items.find((m) => String(m?.key?.value) === settingsKey);
  if (!keyMember) {
    result.note = `${result.file} has no top-level "${settingsKey}" key, so no default preset is set `
      + 'by this document';
    return result;
  }
  if (!keyMember.value || keyMember.value.constructor.name !== 'YAMLMap') {
    result.note = `${result.file}: "${settingsKey}" is not a mapping, so it names no default preset`;
    return result;
  }
  const defMember = keyMember.value.items.find((m) => String(m?.key?.value) === 'default');
  if (!defMember) {
    result.note = `${result.file}: "${settingsKey}" has no "default" key`;
    return result;
  }
  result.value = scalarText(defMember.value?.value);
  result.valueLine = Array.isArray(defMember.key?.range) ? lineAt(starts, defMember.key.range[0]) : null;
  if (result.value === null && isJsWrapper(defMember.value?.value)) {
    result.note = `${result.file}: "${settingsKey}.default" is a !!js expression, which this gate `
      + 'does not evaluate';
  } else if (result.value === null) {
    result.note = `${result.file}: "${settingsKey}.default" is not a plain scalar`;
  }
  return result;
}

// ── preset discovery ─────────────────────────────────────────────────────────────────────────
/**
 * Every preset composition this gate can find, and every place it expected one and found none. A
 * directory that does not exist is recorded with a reason, never silently skipped.
 */
function discoverPresets(configRoot, dshHome) {
  const sources = [
    { role: 'repo', dir: join(configRoot, 'presets'), label: '<root>/presets' },
    { role: 'live', dir: join(dshHome, '.agent-presets'), label: '<dsh-home>/.agent-presets' },
  ];
  const files = [];
  const absent = [];
  const rosterByRole = { repo: [], live: [] };

  for (const src of sources) {
    if (!existsSync(src.dir)) {
      absent.push({
        role: src.role,
        dir: src.dir,
        reason: `${src.label} (${src.dir}) does not exist, so the preset compositions there are NOT `
          + 'checked (input-data gap)',
      });
      continue;
    }
    const dirs = listDirDirs(src.dir);
    if (dirs === null) {
      absent.push({ role: src.role, dir: src.dir, reason: `${src.label} (${src.dir}) could not be listed (input-data gap)` });
      continue;
    }
    rosterByRole[src.role] = dirs;
    for (const name of dirs) {
      const abs = join(src.dir, name, 'agent.cordis.yml');
      if (!existsSync(abs) || !statSync(abs).isFile()) {
        absent.push({
          role: src.role,
          dir: join(src.dir, name),
          preset: name,
          reason: `${src.role} preset directory "${name}" exists but holds no agent.cordis.yml, so `
            + 'its rows are NOT checked',
        });
        continue;
      }
      files.push({ role: src.role, preset: name, path: abs });
    }
  }
  return { files, absent, rosterByRole };
}

/**
 * The roster the SHIPPED presets provide, which lives inside the `@deepseek-ai/dsh-agent-presets`
 * package of an install. Measured contents on this machine (baseline install): `cordis`, `minimal`,
 * `ptc`, `standard`.
 */
function discoverShippedRoster(installRoot) {
  const out = {
    installRoot: installRoot ?? null,
    dir: installRoot ? join(installRoot, 'node_modules', '@deepseek-ai', 'dsh-agent-presets', 'presets') : null,
    present: false,
    presets: [],
    reason: null,
  };
  if (!installRoot) {
    out.reason = 'the candidate contract records no installRoot, so the shipped preset roster '
      + 'could not be located (input-data gap)';
    return out;
  }
  if (!existsSync(out.dir)) {
    out.reason = `${out.dir} does not exist, so the roster the SHIPPED presets provide is not `
      + 'available from this candidate install (input-data gap)';
    return out;
  }
  const dirs = listDirDirs(out.dir);
  if (dirs === null) {
    out.reason = `${out.dir} could not be listed (input-data gap)`;
    return out;
  }
  out.present = true;
  out.presets = dirs;
  return out;
}

// ── parsing one preset file ──────────────────────────────────────────────────────────────────
/**
 * Extract the rows of a preset composition.
 *
 * A row is an element of the document's ROOT SEQUENCE. Rows are added to that sequence; an
 * `insert:` member inside a row contributes further rows and is walked as well. Nothing else is a
 * row — measured, the `{ id, name }` maps under an MCP row's `config:` would otherwise be counted
 * as 13 phantom rows per file.
 */
function collectRows(doc, starts) {
  const rows = [];
  const problems = [];
  const root = doc?.contents;
  if (!root) return { rows, problems: ['the document is empty, so it contributes no rows'] };
  if (root.constructor.name !== 'YAMLSeq') {
    return {
      rows,
      problems: [`the document root is ${root.constructor.name}, not a sequence of rows; no rows `
        + 'were extracted from it (input-data gap: this is not the shape an agent preset has)'],
    };
  }
  const lineOfNode = (node) => (node && Array.isArray(node.range) ? lineAt(starts, node.range[0]) : null);
  // A YAMLPair carries no `range` of its own: its position is its KEY's position. Reporting the
  // pair's own (absent) range is how every line number in this gate came back null once, which
  // is the "confident empty value" this codebase refuses to ship — so keys are addressed directly.
  const keyLine = (member) => (member && Array.isArray(member.key?.range) ? lineAt(starts, member.key.range[0]) : null);
  const scalarValue = (member) => (member ? scalarText(member.value?.value) : null);
  const scalarRaw = (member) => (member ? member.value?.value : undefined);

  const addRow = (item, index, viaInsertOf) => {
    if (!item || item.constructor.name !== 'YAMLMap') {
      problems.push(`root item ${index} is ${item ? item.constructor.name : 'null'}, not a row `
        + 'mapping, and was skipped');
      return;
    }
    const members = new Map(item.items.map((m) => [String(m?.key?.value), m]));
    const idMember = members.get('id');
    const nameMember = members.get('name');
    const rawName = scalarRaw(nameMember);
    const row = {
      index,
      id: scalarValue(idMember),
      idLine: keyLine(idMember),
      line: keyLine(idMember) ?? keyLine(nameMember) ?? lineOfNode(item),
      name: scalarText(rawName),
      nameLine: keyLine(nameMember),
      dynamic: isJsWrapper(rawName),
      group: members.has('group'),
      disabled: scalarValue(members.get('disabled')) === 'true',
      viaInsertOf: viaInsertOf ?? null,
    };
    rows.push(row);
    if (!idMember) {
      problems.push(`row at line ${row.line} carries no "id"`);
    }
    if (!idMember || !nameMember) {
      problems.push(`row ${row.id ? `"${row.id}"` : `#${index}`} at line ${row.line} carries no `
        + '"name", so which package it mounts is unnamed here');
    }
    if (row.dynamic) {
      problems.push(`row "${row.id ?? `#${index}`}" at line ${row.nameLine} names its package with a `
        + '!!js expression, which this gate does not evaluate');
    }
    // Rows can be nested. Two shapes exist, and both are read structurally rather than guessed:
    //   * a GROUP row (`group: true`, `name: cordis:group`) carries its member rows as the
    //     elements of its `config:` SEQUENCE — measured, this is how `planning`, `compaction` and
    //     `delegation` hold plan-mode, the compaction stack, the subagent rows and
    //     `workflow-worker-thread`. Missing this walk is how the gate failed to see the one
    //     breakage it exists for;
    //   * an `insert:` member holds added rows directly.
    // A non-group row's `config:` is NOT walked: an MCP row's config is a map of `{ id, name }`
    // server entries, which are configuration, not rows.
    const insertMember = members.get('insert');
    if (insertMember?.value && insertMember.value.constructor.name === 'YAMLSeq') {
      insertMember.value.items.forEach((it, i) => addRow(it, `${index}.insert[${i}]`, row.id));
    } else if (insertMember?.value && insertMember.value.constructor.name === 'YAMLMap') {
      addRow(insertMember.value, `${index}.insert`, row.id);
    }
    const configMember = members.get('config');
    if (row.group && configMember?.value && configMember.value.constructor.name === 'YAMLSeq') {
      configMember.value.items.forEach((it, i) => addRow(it, `${index}.config[${i}]`, row.id));
    }
  };

  root.items.forEach((item, i) => addRow(item, i, null));
  return { rows, problems };
}

/** Parse one preset file into `{ ok, rows, problems, parseError, sha256, bytes, lineCount }`. */
function analysePresetFile(file, configRoot) {
  const entry = {
    preset: file.preset,
    role: file.role,
    path: toPosix(file.path),
    file: fileFor(file.path, configRoot),
    present: true,
    sha256: null,
    bytes: 0,
    lineCount: 0,
    mtime: null,
    rows: 0,
    rowIds: [],
    parseError: null,
    problems: [],
    names: [],
    _doc: null,
    _starts: null,
  };
  let text;
  try {
    text = readText(file.path);
  } catch (e) {
    entry.present = false;
    entry.parseError = `unreadable: ${e.message}`;
    entry.problems.push(`could not read ${entry.file}: ${e.message}`);
    return entry;
  }
  entry.sha256 = sha256(text);
  entry.bytes = Buffer.byteLength(text, 'utf8');
  const starts = makeLineIndex(text);
  entry.lineCount = starts.length;
  try {
    entry.mtime = new Date(statSync(file.path).mtimeMs).toISOString();
  } catch { entry.mtime = null; }

  const { doc, errors, warnings } = parseYamlDoc(text);
  if (!doc || errors.length > 0) {
    entry.parseError = errors.join(' | ') || 'no document';
    entry.problems.push(`${entry.file} failed to parse as YAML: ${entry.parseError} — it contributes `
      + 'NO rows to this gate, and the names it declares are therefore not checked (input-data gap: '
      + 'this is a gap in the analysis, not a clean file)');
    return entry;
  }
  if (warnings.length > 0) {
    entry.problems.push(`${entry.file} parsed with ${warnings.length} non-fatal YAML warning(s), `
      + `first: ${warnings[0]}`);
  }
  const { rows, problems } = collectRows(doc, starts);
  entry._doc = doc;
  entry._starts = starts;
  entry.rows = rows.length;
  entry.rowIds = rows.map((r) => r.id).filter((x) => x !== null);
  entry.problems.push(...problems);
  entry._rows = rows;
  return entry;
}

// ── name classification / resolution ────────────────────────────────────────────────────────
/** Node's rule, as SPEC C11 states it for `exports`: a subpath is `"."` or begins with `"./"`. */
function splitSpecifier(name) {
  const scoped = /^(@[^/]+\/[^/]+)(\/.*)?$/.exec(name);
  if (scoped) return { pkg: scoped[1], rest: scoped[2] ?? null };
  const bare = /^([^/]+)(\/.*)?$/.exec(name);
  if (bare) return { pkg: bare[1], rest: bare[2] ?? null };
  return { pkg: name, rest: null };
}

function subpathOf(rest) {
  if (!rest) return '.';
  return `.${rest}`; // `/list-agents` -> `./list-agents`
}

/** Does an `exports` pattern entry (`./src/*`) cover this subpath? Node's own wildcard rule. */
function patternCovers(entry, subpath) {
  if (!entry.includes('*')) return false;
  const re = new RegExp(`^${entry.split('*').map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^]*')}$`);
  return re.test(subpath);
}

/** A single, extensionless segment is the only shape an `exports` key can have. */
function looksLikeExportSubpath(rest) {
  const seg = rest.replace(/^\//, '');
  if (seg.length === 0) return false;
  if (seg.includes('/')) return false;
  if (/\.[A-Za-z0-9]+$/.test(seg)) return false;
  return true;
}

const isOwnName = (name) => /^dsh-plugin-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)
  || name.startsWith('./') || name.startsWith('../') || name.startsWith('/')
  || /^[A-Za-z]:[\\/]/.test(name) || name.startsWith('file:');

/**
 * Resolve one distinct `name:` against the candidate contract. Returns the resolution, and — only
 * where the evidence supports one — a finding. `own` and `unjudged` names NEVER produce a BREAKS:
 * an upstream contract cannot judge our own packages, and a third-party name is not in its map.
 */
function analyseName(name, ctx) {
  const { candidate, baseline } = ctx;
  const out = {
    name,
    package: null,
    subpath: null,
    resolution: 'unknown',
    findings: [],
    gap: null,
  };

  // 1. Ours. `dsh-plugin-*` and bare relative/absolute specifiers never break on an upstream
  //    contract: they resolve from a profile's own node_modules or from the tree itself.
  if (isOwnName(name)) {
    out.resolution = name.startsWith('dsh-plugin-') ? 'own-package' : 'relative-specifier';
    out.findings.push({
      class: CLASS.P0,
      severity: 'INFO',
      subject: name,
      evidence: `the candidate contract describes ${candidate.packageCount} @deepseek-ai/* packages `
        + `only (${candidate.path}); "${name}" is one of this deployment's own packages and is not in `
        + 'that map by construction, so its absence there means nothing',
      evidenceTier: 'AUTHORITATIVE',
      why: 'a packaging mistake in our own plugin would break the preset, but an upstream contract '
        + 'cannot see it either way — this is reported so it is not mistaken for a checked name',
      suggested: 'keep verifying our own bundles with verify.mjs gates G3 (the bundles resolve) and '
        + 'a real boot; this gate deliberately does not judge them',
    });
    out.gap = {
      kind: 'own-package',
      reason: 'our own package (or a relative specifier) — an upstream contract cannot judge it',
    };
    return out;
  }

  // 2. A cordis built-in pseudo-name. `cordis:group` is a structural marker, not a package.
  if (name.startsWith('cordis:')) {
    out.resolution = 'builtin';
    out.gap = {
      kind: 'builtin-row-name',
      reason: `"${name}" is a built-in cordis row name (a group marker), not a package specifier; a `
        + 'contract of installed packages cannot judge it and there is nothing to resolve',
    };
    return out;
  }

  // 3. Upstream. Only this branch can produce a BREAKS.
  const { pkg, rest } = splitSpecifier(name);
  out.package = pkg;
  out.subpath = rest ? subpathOf(rest) : '.';

  if (!pkg.startsWith('@deepseek-ai/')) {
    out.resolution = 'unknown-third-party';
    out.gap = {
      kind: 'not-in-contract-scope',
      reason: `"${name}" is neither a @deepseek-ai/* package nor one of this deployment's own, and `
        + 'the contract describes @deepseek-ai/* only — so this name is NOT checked here',
    };
    return out;
  }

  const hit = Object.prototype.hasOwnProperty.call(candidate.packages, pkg)
    ? candidate.packages[pkg]
    : null;

  // 3a. The package itself is gone. This is B1 and it is AUTHORITATIVE: the contract is a manifest
  //     census, and a name that is not in it cannot resolve at mount.
  if (hit === null || hit === undefined || hit.present === false || hit.version === null) {
    const absent = hit === null || hit === undefined || hit.present === false;
    const bits = [];
    if (absent) {
      bits.push(`"${pkg}" is not a key in the candidate contract's packages map `
        + `(${candidate.packageCount} @deepseek-ai/* packages, read from ${candidate.path}, `
        + `sha256 ${candidate.sha256.slice(0, 16)}…, generatedAt ${candidate.generatedAt ?? 'unknown'})`);
    } else {
      bits.push(`"${pkg}" is present in the candidate contract but its version is null with `
        + `manifestReadable=${String(hit.manifestReadable)} — SPEC treats a null version as missing `
        + `(contract ${candidate.path}, generatedAt ${candidate.generatedAt ?? 'unknown'})`);
    }
    if (baseline) {
      const b = Object.prototype.hasOwnProperty.call(baseline.packages, pkg) ? baseline.packages[pkg] : null;
      if (b && b.version !== null) {
        bits.push(`the baseline contract ${baseline.path} DOES carry it at version ${b.version}, so `
          + 'the candidate version REMOVED a package this deployment names');
      } else if (b) {
        bits.push(`the baseline contract ${baseline.path} carries it too but with version null, so `
          + 'the name is not resolvable in either install');
      } else {
        bits.push(`the baseline contract ${baseline.path} does not carry it either, so this name is `
          + 'not resolvable from what is running today either');
      }
    }
    out.resolution = absent ? 'missing-package' : 'missing-version';
    out.findings.push({
      class: CLASS.P1,
      severity: 'BREAKS',
      subject: pkg,
      evidence: `${bits.join('; ')}`,
      evidenceTier: 'AUTHORITATIVE',
      why: `a preset row names "${pkg}" and the candidate install has no such package, so that row `
        + 'cannot resolve at mount and creating a session on this preset fails — with no host-level '
        + 'symptom at all, because presets contribute no rows to --dump-config',
      suggested: `remove or disable the naming row in every preset file listed under consumers, or `
        + `keep it only if the candidate replaces "${pkg}" with a package we then name instead`,
    });
    return out;
  }

  // 3b. The package is there. Now the subpath.
  const subs = Array.isArray(hit.exportSubpaths) ? hit.exportSubpaths : null;
  if (out.subpath === '.') {
    out.resolution = 'resolved-package';
    return out;
  }
  if (subs === null) {
    out.resolution = 'unjudged-no-export-map';
    out.gap = {
      kind: 'no-export-subpaths-recorded',
      reason: `the candidate contract records no exportSubpaths array for ${pkg}, so the subpath `
        + `"${out.subpath}" could not be checked either way`,
    };
    return out;
  }
  if (subs.includes(out.subpath)) {
    out.resolution = 'resolved-subpath';
    return out;
  }
  const pattern = subs.find((s) => typeof s === 'string' && patternCovers(s, out.subpath));
  if (pattern) {
    out.resolution = 'resolved-subpath-pattern';
    out.gap = {
      kind: 'subpath-matched-by-pattern',
      reason: `"${out.subpath}" is not enumerated literally in ${pkg}'s exportSubpaths, but the `
        + `pattern entry "${pattern}" covers it; it was therefore treated as resolvable and NOT as `
        + 'a breakage (a false BREAKS is worse than an honest gap)',
    };
    return out;
  }
  if (!looksLikeExportSubpath(rest)) {
    // A multi-segment or extension-bearing specifier is a FILE path, not an exports key. Calling it
    // missing would be the same class of error as the false BREAKS the first pipeline run produced.
    out.resolution = 'unjudged-subpath-shape';
    out.gap = {
      kind: 'subpath-not-an-exports-key',
      reason: `"${out.subpath}" is not the shape of an exports key (a single extensionless segment) `
        + `— it names a path, and exportSubpaths only enumerates package exports, so it was NOT `
        + `judged. ${pkg} exports: ${JSON.stringify(subs)}`,
    };
    return out;
  }
  out.resolution = 'missing-subpath';
  out.findings.push({
    class: CLASS.P2,
    severity: 'BREAKS',
    subject: name,
    evidence: `the candidate ${pkg} (version ${hit.version}) exposes exportSubpaths `
      + `${JSON.stringify(subs)}; "${out.subpath}" is not among them `
      + `(contract ${candidate.path}, generatedAt ${candidate.generatedAt ?? 'unknown'})`,
    evidenceTier: 'AUTHORITATIVE',
    why: 'a preset row names this subpath, so the row cannot resolve at mount and creating a session '
      + 'on this preset fails — the host composition is unaffected and reports nothing',
    suggested: `use a subpath the candidate does export (${JSON.stringify(subs)}), or keep the row `
      + 'disabled until upstream restores it',
  });
  return out;
}

// ── repo vs live drift ───────────────────────────────────────────────────────────────────────
/** The first 1-based line at which two texts differ, comparing raw lines (CRLF included). */
function firstDifferingLine(aText, bText) {
  if (aText === bText) return null;
  const a = aText.split('\n');
  const b = bText.split('\n');
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    if (a[i] !== b[i]) return i + 1;
  }
  return n + 1 <= Math.max(a.length, b.length) ? n + 1 : null;
}

/**
 * How a drift finding describes a side's row count. A file that failed to parse has an UNKNOWN row
 * count, and printing "0 rows" for it would be a fabricated reading — the same class of error as
 * synthesising a line number.
 */
function rowsLabel(entry) {
  return entry.parseError !== null ? 'rows unknown (the file failed to parse)' : `${entry.rows} rows`;
}

/**
 * Compare the repo copy of each preset against its live copy under `<dsh-home>/.agent-presets/`.
 * A row that vanished from the live copy is RISKY; a content difference is INFO. For a preset that
 * is GENERATED wholesale from another composition, the difference is INFO with the generator named,
 * because between generator runs the repo and the home legitimately disagree.
 */
function compareDrift(repoEntries, liveEntries, ctx) {
  const findings = [];
  const gaps = [];
  const byPreset = (list) => new Map(list.map((e) => [e.preset, e]));
  const repo = byPreset(repoEntries);
  const live = byPreset(liveEntries);
  const names = [...new Set([...repo.keys(), ...live.keys()])].sort(orderByString);

  for (const preset of names) {
    const r = repo.get(preset) ?? null;
    const l = live.get(preset) ?? null;
    const gen = GENERATED_PRESETS.find((g) => g.preset === preset
      && (r === null || toPosix(relative(ctx.configRoot, r.path)) === g.repoRelPath)) ?? null;
    const genNote = gen
      ? ` NOTE: ${gen.repoRelPath} is GENERATED WHOLESALE from ${gen.from} by ${gen.generatedBy}, so a `
        + 'difference here means the generator and/or the sync have not been re-run since the last '
        + 'edit; that is expected between generator runs and is reported as INFO, never as an error.'
      : '';

    if (r && !l) {
      findings.push({
        class: CLASS.P4,
        severity: 'INFO',
        subject: `${preset} (repo-only)`,
        evidence: `the repo copy ${r.file} exists (sha256 ${r.sha256}, ${rowsLabel(r)}, mtime `
          + `${r.mtime ?? 'unknown'}) and there is no ${ctx.dshHomeForDisplay}/.agent-presets/${preset}/`
          + `agent.cordis.yml — the preset is NOT installed, so a session asking for it by this name `
          + 'cannot find it here.'
          + genNote,
        evidenceTier: 'AUTHORITATIVE',
        consumers: [
          { file: r.file, line: null },
          { file: toPosix(join(ctx.dshHome, '.agent-presets', preset, 'agent.cordis.yml')), line: null },
        ],
        why: 'a preset that exists only in the repo is not what the running engine mounts; the '
          + 'deployment is running something older or something else',
        suggested: `install it into ${ctx.dshHome}/.agent-presets/${preset}/agent.cordis.yml (or `
          + 're-run whatever syncs the repo presets into the home) and re-run this gate',
      });
      continue;
    }
    if (!r && l) {
      findings.push({
        class: CLASS.P4,
        severity: 'INFO',
        subject: `${preset} (live-only)`,
        evidence: `the live copy ${l.file} is installed (sha256 ${l.sha256}, ${rowsLabel(l)}, mtime `
          + `${l.mtime ?? 'unknown'}) and no repo copy exists at <root>/presets/${preset}/`
          + 'agent.cordis.yml — this preset exists only on this machine and would be lost with it.',
        evidenceTier: 'AUTHORITATIVE',
        consumers: [{ file: l.file, line: null }],
        why: 'a preset edited in place inside the live home is not versioned anywhere, so it is not '
          + 'reviewed and does not exist on the other machines',
        suggested: `copy it into <root>/presets/${preset}/ so it is versioned, then re-run this gate`,
      });
      continue;
    }
    if (!r || !l) continue;

    if (r.sha256 === l.sha256) continue; // byte-identical: nothing to report

    const vanished = r.rowIds.filter((id) => !l.rowIds.includes(id));
    const added = l.rowIds.filter((id) => !r.rowIds.includes(id));
    const diffLine = firstDifferingLine(readText(r.path), readText(l.path));
    const consumers = [];
    if (vanished.length > 0) {
      for (const id of vanished.slice().sort(orderByString)) {
        const line = (r._rows ?? []).find((row) => row.id === id)?.line ?? null;
        consumers.push({ file: r.file, line });
      }
    } else {
      consumers.push({ file: r.file, line: diffLine });
      consumers.push({ file: l.file, line: diffLine });
    }
    // A vanished row is the drift that matters; for a generated preset the generator is the
    // documented explanation, so it is INFO with that fact named rather than an error.
    const severity = vanished.length > 0 && !gen ? 'RISKY' : 'INFO';
    findings.push({
      class: CLASS.P4,
      severity,
      subject: `${preset} (repo vs live differ)`,
      evidence: `repo ${r.file} sha256 ${r.sha256} (${rowsLabel(r)}, mtime ${r.mtime ?? 'unknown'}) `
        + `vs live ${l.file} sha256 ${l.sha256} (${rowsLabel(l)}, mtime ${l.mtime ?? 'unknown'}); `
        + 'row ids present in the repo copy and absent from the live '
        + `copy: ${vanished.length > 0 ? vanished.join(', ') : '(none)'}; present live and absent `
        + `from the repo copy: ${added.length > 0 ? added.join(', ') : '(none)'}; first differing `
        + `line: ${diffLine ?? '(none: the two texts are equal here, so the difference is in bytes '
        + 'this comparison does not normalize)'}`
        + genNote,
      evidenceTier: 'AUTHORITATIVE',
      consumers,
      why: l.rows === 0
        ? 'the LIVE copy carries no rows at all while the repo copy does — the installed preset is '
          + 'empty or failed to parse where the repo copy did not'
        : (vanished.length > 0
          ? 'the running engine mounts the live copy, so a row that exists in the repo but not live '
            + 'is a capability the repo believes it has and the machine does not'
          : 'the running engine mounts the live copy, so the two disagree about configuration that '
            + 'has not been re-synced'),
      suggested: `diff ${r.file} against ${l.file} and re-sync deliberately (for a generated preset: `
        + `re-run ${gen ? gen.generatedBy : 'the generator'}, then re-run this gate)`,
    });
  }
  return { findings, gaps };
}

// ── assembly ─────────────────────────────────────────────────────────────────────────────────
function buildArtifact(args) {
  const configRoot = resolve(args.root ?? process.env.DSH_CONFIG_ROOT ?? CONFIG_ROOT_DEFAULT);
  const dshHome = resolve(
    args.dshHome ?? process.env.DSH_HOME ?? join(process.env.USERPROFILE ?? process.env.HOME ?? '', '.dsh'),
  );
  const notes = [];
  const unverifiedRaw = [];
  const gap = (entry) => unverifiedRaw.push(entry);

  const candidate = readContract(args.candidateContract, 'candidate');
  let baseline = null;
  if (args.baselineContract) {
    try {
      baseline = readContract(args.baselineContract, 'baseline');
    } catch (e) {
      notes.push(`the baseline contract could not be read (${e.message}), so findings carry no `
        + '"removed vs never present" comparison; every absence is reported on the candidate alone');
    }
  }
  notes.push(`candidate contract: ${candidate.path} (${candidate.packageCount} packages, dsh `
    + `${candidate.version ?? 'unknown'}, installRoot ${candidate.installRoot ?? 'unknown'}, `
    + `generatedAt ${candidate.generatedAt ?? 'unknown'}, sha256 ${candidate.sha256.slice(0, 16)}…)`);
  if (baseline) {
    notes.push(`baseline contract: ${baseline.path} (${baseline.packageCount} packages, dsh `
      + `${baseline.version ?? 'unknown'}, sha256 ${baseline.sha256.slice(0, 16)}…)`);
  }
  notes.push(`config root: ${configRoot}; dsh home: ${dshHome}`);

  const discovery = discoverPresets(configRoot, dshHome);
  for (const a of discovery.absent) notes.push(`absent: ${a.reason}`);
  const shipped = discoverShippedRoster(candidate.installRoot);
  notes.push(shipped.present
    ? `shipped preset roster: ${shipped.presets.join(', ')} (from ${shipped.dir})`
    : `shipped preset roster UNAVAILABLE: ${shipped.reason}`);

  // ── parse every file ──
  const entries = discovery.files
    .slice()
    .sort((a, b) => orderByString(`${a.role}|${toPosix(a.path)}`, `${b.role}|${toPosix(b.path)}`))
    .map((f) => analysePresetFile(f, configRoot));
  const failed = entries.filter((e) => e.parseError !== null);
  if (entries.length === 0) {
    notes.push('NO preset composition file was found at all — this is a gap in the analysis, not a '
      + 'clean result: the verdict below says nothing about preset resolution');
  }
  if (failed.length > 0) {
    notes.push(`${failed.length}/${entries.length} preset file(s) failed to parse and contribute no `
      + `rows: ${failed.map((f) => f.file).join(', ')}`);
  }

  // ── resolve every distinct name ──
  const ctx = { candidate, baseline };
  const byName = new Map();
  for (const entry of entries) {
    if (entry.parseError !== null) continue;
    for (const row of entry._rows ?? []) {
      if (row.name === null) continue;
      if (!byName.has(row.name)) byName.set(row.name, []);
      byName.get(row.name).push({
        preset: entry.preset,
        role: entry.role,
        file: entry.file,
        line: row.nameLine ?? null,
        rowId: row.id ?? null,
        index: row.index,
      });
    }
  }

  const findingsRaw = [];
  const stats = {
    presetFiles: entries.length,
    presetFilesParsed: entries.length - failed.length,
    presetFilesFailed: failed.length,
    rows: entries.reduce((n, e) => n + (e.parseError === null ? e.rows : 0), 0),
    distinctNames: byName.size,
    namesResolved: 0,
    namesUnverified: 0,
    upstreamNamesChecked: 0,
    ownNames: 0,
    builtinNames: 0,
    thirdPartyNames: 0,
    repoPresets: discovery.rosterByRole.repo.length,
    livePresets: discovery.rosterByRole.live.length,
    shippedRosterPresets: shipped.present ? shipped.presets.length : 0,
  };

  const resolutions = new Map();
  for (const name of [...byName.keys()].sort(orderByString)) {
    const res = analyseName(name, ctx);
    resolutions.set(name, res);
    const consumers = byName.get(name)
      .slice()
      .sort((a, b) => orderByString(`${a.file}|${String(a.line).padStart(6, '0')}`, `${b.file}|${String(b.line).padStart(6, '0')}`));
    // One factual cross-reference, computed from the files themselves: when ONLY the installed
    // copies still name a package the candidate removed, and the repo copy of that same preset
    // exists and no longer names it, say so — that is the difference between "we must find a
    // replacement" and "the replacement is already written down and just has to be synced".
    const repoPresets = new Set(entries.filter((e) => e.role === 'repo').map((e) => e.preset));
    const liveOnly = consumers.some((c) => c.role === 'live')
      && !consumers.some((c) => c.role === 'repo')
      && consumers.every((c) => c.role !== 'live' || repoPresets.has(c.preset));
    for (const f of res.findings) {
      const enriched = liveOnly && f.class === CLASS.P1
        ? {
          ...f,
          evidence: `${f.evidence}; note: only the INSTALLED copies name it — the repo copy of the `
            + 'same preset exists and no longer names it, so a replacement has been written down and '
            + 'has not been synced into the live home',
        }
        : f;
      findingsRaw.push({ ...enriched, consumers });
    }
    if (res.resolution.startsWith('resolved')) stats.namesResolved += 1;
    if (res.resolution === 'own-package' || res.resolution === 'relative-specifier') stats.ownNames += 1;
    else if (res.resolution === 'builtin') stats.builtinNames += 1;
    else if (res.resolution === 'unknown-third-party') stats.thirdPartyNames += 1;
    else stats.upstreamNamesChecked += 1;

    if (res.gap) {
      stats.namesUnverified += 1;
      for (const c of consumers) {
        gap({
          ref: name,
          kind: res.gap.kind,
          reason: res.gap.reason,
          file: c.file,
          line: c.line,
          where: consumers.map((x) => (x.line === null ? x.file : `${x.file}:${x.line}`)),
          locations: consumers.length,
          preset: c.preset,
        });
      }
    }
    // A preset file whose parse failed contributes no names; say so per name-level check.
  }

  // ── the shipped roster package itself ──
  // The roster this gate uses for P3 lives INSIDE `@deepseek-ai/dsh-agent-presets`. When the
  // candidate has removed that package the shipped roster goes with it. That is only a BREAKAGE if
  // something we own still NAMES the package: a comment that merely mentions it (which is what the
  // mesh patch layer was left with once the row was updated) breaks nothing, and calling it BREAKS
  // would be the same false-positive class the pipeline's first real run produced. A comment-only
  // mention is therefore recorded as a gap, with the comment lines quoted, never as a finding.
  const rosterPkg = '@deepseek-ai/dsh-agent-presets';
  const rosterPkgInCandidate = Object.prototype.hasOwnProperty.call(candidate.packages, rosterPkg)
    && candidate.packages[rosterPkg]?.version !== null;
  if (!rosterPkgInCandidate && !shipped.present) {
    const mentions = [];
    const commentMentions = [];
    const profilesDir = join(configRoot, 'profiles');
    if (existsSync(profilesDir)) {
      for (const profile of listDirDirs(profilesDir) ?? []) {
        const patch = join(profilesDir, profile, 'cordis.patch.yml');
        if (!existsSync(patch) || !statSync(patch).isFile()) continue;
        readText(patch).split('\n').forEach((ln, i) => {
          if (!ln.includes(rosterPkg)) return;
          const at = { file: fileFor(patch, configRoot), line: i + 1 };
          if (ln.trim().startsWith('#')) commentMentions.push(at); else mentions.push(at);
        });
      }
    }
    const gone = `"${rosterPkg}" is not in the candidate contract's packages map (`
      + `${candidate.packageCount} packages, ${candidate.path}) and `
      + `${shipped.dir ?? 'its roster directory'} does not exist, so the candidate ships NO shipped `
      + 'preset roster — the four presets this machine measures as shipped (cordis, minimal, ptc, '
      + 'standard) are not available from that install'
      + (baseline && Object.prototype.hasOwnProperty.call(baseline.packages, rosterPkg)
        ? `; the baseline contract carries it at version ${baseline.packages[rosterPkg].version}`
        : '');
    if (mentions.length > 0) {
      findingsRaw.push({
        class: CLASS.P1,
        severity: 'BREAKS',
        subject: rosterPkg,
        evidence: `${gone}; non-comment consumers naming it: `
          + `${mentions.map((c) => `${c.file}:${c.line}`).join(', ')}`,
        evidenceTier: 'AUTHORITATIVE',
        consumers: mentions,
        why: 'a row in a profile patch layer names this package and the candidate install does not '
          + 'have it, so that row cannot resolve',
        suggested: 'name the package upstream ships in its place (or delete the row deliberately), '
          + 'then re-run this gate',
      });
    } else {
      notes.push(`shipped roster: ${gone}`);
      gap({
        ref: rosterPkg,
        kind: 'shipped-roster-unavailable',
        reason: `${gone}. No file under ${toPosix(join(configRoot, 'profiles'))}/*/cordis.patch.yml `
          + 'names it on a non-comment line any more'
          + (commentMentions.length > 0
            ? ` (only comments do: ${commentMentions.map((c) => `${c.file}:${c.line}`).join(', ')})`
            : '')
          + ', so no consumer is left broken by the removal — but the shipped roster is NOT '
          + 'available to this gate, so the P3 union below is the local preset directories only, and '
          + 'a session naming a shipped preset (cordis, minimal, ptc, standard) has nothing to mount '
          + 'on that install',
        file: commentMentions[0]?.file ?? candidate.path,
        line: commentMentions[0]?.line ?? null,
        where: (commentMentions.length > 0 ? commentMentions : [{ file: candidate.path, line: null }])
          .map((c) => (c.line === null ? c.file : `${c.file}:${c.line}`)),
        locations: Math.max(commentMentions.length, 1),
      });
    }
  } else if (!rosterPkgInCandidate && shipped.present) {
    gap({
      ref: rosterPkg,
      kind: 'roster-present-without-package',
      reason: `"${rosterPkg}" is absent from the candidate contract yet ${shipped.dir} exists on `
        + 'disk — the package was resolved from somewhere other than this contract\'s install root, '
        + 'so the roster was read but the package census does not corroborate it',
      file: candidate.path,
      line: null,
      where: [shipped.dir],
      locations: 1,
    });
  }

  // ── P3: the default preset name ──
  const settingsPath = join(dshHome, 'settings.yaml');
  const def = readDefaultPreset(settingsPath, args.profileKey, configRoot);
  const localRoster = [
    ...discovery.rosterByRole.live.map((n) => ({ name: n, source: 'live' })),
  ];
  const shippedRoster = shipped.present ? shipped.presets.map((n) => ({ name: n, source: 'shipped' })) : [];
  const union = [...new Set([...localRoster, ...shippedRoster].map((x) => x.name))].sort(orderByString);

  const p3 = {
    settingsFile: def.file,
    settingsKey: args.profileKey,
    value: def.value,
    valueLine: def.valueLine,
    localPresets: localRoster.map((x) => x.name),
    shippedPresets: shippedRoster.map((x) => x.name),
    union,
    shippedRosterAvailable: shipped.present,
    passed: null,
    reason: null,
  };
  if (def.value === null) {
    p3.reason = def.note ?? `no value could be read for ${args.profileKey}.default`;
    gap({
      ref: `${args.profileKey}.default`,
      kind: 'settings-default-not-readable',
      reason: `the default preset name could not be READ (${p3.reason}), so whether it exists in any `
        + 'roster was not checked — this is an unobserved check, not a pass',
      file: def.file,
      line: def.valueLine,
      where: [def.file],
      locations: 1,
    });
  } else if (union.includes(def.value)) {
    p3.passed = true;
    const sources = [
      localRoster.some((x) => x.name === def.value) ? `${dshHome}/.agent-presets/` : null,
      shippedRoster.some((x) => x.name === def.value) ? `${shipped.dir}` : null,
    ].filter(Boolean);
    p3.reason = `"${def.value}" is in the union of the local roster ${JSON.stringify(p3.localPresets)} `
      + `and the shipped roster ${shipped.present ? JSON.stringify(p3.shippedPresets) : '(unavailable)'}`
      + ` — found in ${sources.join(' and ')}`;
  } else {
    p3.passed = false;
    p3.reason = `"${def.value}" is in NEITHER the local roster ${JSON.stringify(p3.localPresets)} nor `
      + `the shipped roster ${shipped.present ? JSON.stringify(p3.shippedPresets) : '(unavailable)'}`;
    findingsRaw.push({
      class: CLASS.P3,
      severity: 'BREAKS',
      subject: `${args.profileKey}.default = ${def.value}`,
      evidence: `${def.file}:${def.valueLine ?? '?'} sets ${args.profileKey}.default: ${def.value}; `
        + `the union of the shipped roster (${shipped.present ? JSON.stringify(shipped.presets) : 'unavailable'}) `
        + `and the local preset directories (${JSON.stringify(p3.localPresets)}) does not contain it`,
      evidenceTier: 'AUTHORITATIVE',
      consumers: [{ file: def.file, line: def.valueLine }],
      why: 'a default preset name no roster provides means the engine cannot mount the default '
        + 'preset, so new sessions fail to start until the setting or the preset directory is fixed',
      suggested: `either restore <dsh-home>/.agent-presets/${def.value}/agent.cordis.yml or point `
        + `${args.profileKey}.default at a preset that exists`,
    });
  }

  // ── drift ──
  const drift = compareDrift(
    entries.filter((e) => e.role === 'repo'),
    entries.filter((e) => e.role === 'live'),
    { configRoot, dshHome, dshHomeForDisplay: dshHome },
  );
  findingsRaw.push(...drift.findings);
  for (const g of drift.gaps) gap(g);
  notes.push('the repo-vs-live drift comparison covers agent.cordis.yml only; preset.yml and the '
    + 'skills/ trees beside it are NOT compared by this gate');
  notes.push('a row marked `disabled: true` whose package is absent from the candidate is still '
    + 'reported BREAKS and is NOT exempted — the SPEC\'s own B2 example does exactly that ("keep the '
    + 'disabled row; do not delete it"), and this gate must not boot a session to observe whether a '
    + 'disabled row\'s name is resolved at mount. Which rows are disabled is recorded per name in '
    + 'presets[].names[].disabled, so a reader can judge for themselves.');
  notes.push('this gate judges only that a NAME can resolve against the candidate install. It does '
    + 'not evaluate !!js expressions, does not compose the preset, and cannot see whether a row that '
    + 'resolves still accepts the config in the file — a boot is the only evidence for that.');

  // ── sort findings, assign ids, cap severity by evidence tier ──
  const deduped = new Map();
  for (const f of findingsRaw) {
    if (f.severity === 'BREAKS' && f.evidenceTier !== 'AUTHORITATIVE') {
      f.downgradedFrom = 'BREAKS';
      f.severity = 'RISKY';
      f.evidence = `${f.evidence} | DOWNGRADED BREAKS->RISKY: this rests on ${f.evidenceTier} `
        + 'evidence and only AUTHORITATIVE evidence may declare BREAKS (SPEC §Evidence tiers).';
    }
    const key = `${f.class}|${f.subject}|${f.severity}`;
    const prev = deduped.get(key);
    if (prev) {
      for (const c of f.consumers ?? []) {
        if (!prev.consumers.some((x) => x.file === c.file && x.line === c.line)) prev.consumers.push(c);
      }
      if (prev.evidence !== f.evidence) prev.evidence = `${prev.evidence} || also: ${f.evidence}`;
      continue;
    }
    deduped.set(key, { ...f, consumers: [...(f.consumers ?? [])] });
  }
  const ordered = [...deduped.values()].sort((a, b) => {
    const s = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
    if (s !== 0) return s;
    if (a.subject !== b.subject) return orderByString(a.subject, b.subject);
    if (a.class !== b.class) return orderByString(a.class, b.class);
    return orderByString(a.evidence ?? '', b.evidence ?? '');
  });
  const findings = ordered.map((f, i) => {
    const o = {
      id: `F${String(i + 1).padStart(3, '0')}`,
      class: f.class,
      severity: f.severity,
      subject: f.subject,
      evidence: f.evidence,
      evidenceTier: f.evidenceTier,
    };
    if (f.downgradedFrom) o.downgradedFrom = f.downgradedFrom;
    o.consumers = (f.consumers ?? []).slice().sort((a, b) => {
      const af = String(a.file ?? '');
      const bf = String(b.file ?? '');
      if (af !== bf) return orderByString(af, bf);
      return (a.line ?? -1) - (b.line ?? -1);
    });
    o.why = f.why;
    o.suggested = f.suggested;
    return o;
  });

  const counts = { BREAKS: 0, RISKY: 0, CAPABILITY: 0, INFO: 0 };
  for (const f of findings) counts[f.severity] = (counts[f.severity] ?? 0) + 1;
  const verdict = counts.BREAKS > 0 ? 'BREAKS' : (counts.RISKY > 0 ? 'RISKY' : 'SAFE');
  // The verdict above is over EVERY finding, as specified. Because P4 (repo vs live drift) is not
  // a statement about the CANDIDATE at all, it is also summarised separately: a reader checking
  // "does this upgrade break us" must be able to see a name-resolution verdict unpolluted by
  // housekeeping drift, and equally must not be able to miss the drift.
  const verdictOf = (list) => (
    list.some((f) => f.severity === 'BREAKS') ? 'BREAKS'
      : (list.some((f) => f.severity === 'RISKY') ? 'RISKY' : 'SAFE')
  );
  const verdicts = {
    overall: verdict,
    candidateNameResolution: verdictOf(findings.filter((f) => f.class !== CLASS.P4)),
    repoLiveDrift: verdictOf(findings.filter((f) => f.class === CLASS.P4)),
  };

  // ── unverified: group by (ref, kind, reason) so the list is readable at a glance ──
  const gmap = new Map();
  for (const u of unverifiedRaw) {
    const key = `${u.kind}\u0000${u.ref}\u0000${u.reason}`;
    if (!gmap.has(key)) {
      gmap.set(key, { ref: u.ref, kind: u.kind, reason: u.reason, file: u.file ?? null, line: u.line ?? null, where: [], locations: 0, presets: [] });
    }
    const g = gmap.get(key);
    for (const w of u.where ?? []) if (!g.where.includes(w)) g.where.push(w);
    if (u.preset && !g.presets.includes(u.preset)) g.presets.push(u.preset);
    g.locations = g.where.length;
  }
  const unverified = [...gmap.values()]
    .map((g) => ({
      ref: g.ref,
      kind: g.kind,
      reason: g.reason,
      file: g.file,
      line: g.line,
      where: g.where.slice().sort(orderByString),
      locations: g.locations,
      presets: g.presets.slice().sort(orderByString),
    }))
    .sort((a, b) => {
      if (a.ref !== b.ref) return orderByString(a.ref, b.ref);
      if (a.kind !== b.kind) return orderByString(a.kind, b.kind);
      return orderByString(a.reason, b.reason);
    });
  stats.unverifiedEntries = unverified.length;
  stats.unverifiedLocations = unverified.reduce((n, g) => n + g.locations, 0);

  // ── presets[]: one entry per file, with its own per-name resolution ──
  const presets = entries.map((e) => {
    const names = [...new Set((e._rows ?? []).map((r) => r.name).filter((n) => n !== null))]
      .sort(orderByString)
      .map((name) => {
        const res = resolutions.get(name);
        const locs = (e._rows ?? []).filter((r) => r.name === name);
        return {
          name,
          package: res?.package ?? null,
          subpath: res?.subpath ?? null,
          resolution: res?.resolution ?? 'not-analysed',
          line: locs[0]?.nameLine ?? null,
          rowId: locs[0]?.id ?? null,
          disabled: locs[0]?.disabled ?? null,
        };
      });
    return {
      preset: e.preset,
      role: e.role,
      file: e.file,
      path: e.path,
      present: e.present,
      sha256: e.sha256,
      bytes: e.bytes,
      lineCount: e.lineCount,
      mtime: e.mtime,
      rows: e.parseError === null ? e.rows : null,
      rowIds: e.parseError === null ? e.rowIds : null,
      parseError: e.parseError,
      problems: e.problems,
      names,
    };
  });

  // ── rosters and per-file pairing for the record ──
  const rosters = {
    shipped: {
      source: rosterPkg,
      installRoot: shipped.installRoot,
      dir: shipped.dir,
      present: shipped.present,
      presets: shipped.presets,
      inCandidateContract: rosterPkgInCandidate,
      reason: shipped.reason,
    },
    repo: { dir: join(configRoot, 'presets'), presets: discovery.rosterByRole.repo },
    live: { dir: join(dshHome, '.agent-presets'), presets: discovery.rosterByRole.live },
  };

  const artifact = {
    schemaVersion: SCHEMA_VERSION,
    generatedAt: ctx.generatedAt,
    verdict,
    verdicts,
    counts,
    candidate: {
      path: candidate.path,
      sha256: candidate.sha256,
      installRoot: candidate.installRoot,
      version: candidate.version,
      packages: candidate.packageCount,
      generatedAt: candidate.generatedAt,
    },
    baseline: baseline
      ? {
        path: baseline.path,
        sha256: baseline.sha256,
        installRoot: baseline.installRoot,
        version: baseline.version,
        packages: baseline.packageCount,
        generatedAt: baseline.generatedAt,
      }
      : null,
    findings,
    unverified,
    presets,
    defaultPreset: p3,
    rosters,
    stats,
    notes,
  };
  return artifact;
}

// ── CLI ──────────────────────────────────────────────────────────────────────────────────────
function resolveGeneratedAt(explicit) {
  if (explicit) {
    const t = Date.parse(explicit);
    if (Number.isNaN(t)) throw new UsageError(`--generated-at is not a parseable date: ${explicit}`);
    return new Date(t).toISOString();
  }
  const epoch = process.env.SOURCE_DATE_EPOCH;
  if (epoch !== undefined && epoch !== '') {
    const n = Number(epoch);
    if (!Number.isFinite(n)) throw new UsageError(`SOURCE_DATE_EPOCH is not a number: ${epoch}`);
    return new Date(n * 1000).toISOString();
  }
  return new Date().toISOString();
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    process.stderr.write(`preset-gate.mjs: ${e.message}\n${USAGE}\n`);
    return 2;
  }
  if (args.help) {
    process.stdout.write(`${USAGE}\n\n`
      + 'Resolves every agent-preset row name against a candidate contract.json.\n'
      + '  --candidate-contract  contract.json of the candidate install (required)\n'
      + '  --baseline-contract   contract.json of what runs today (optional; strengthens "removed")\n'
      + '  --root                harness-config checkout holding presets/ (default: the checkout\n'
      + '                        that owns this file)\n'
      + '  --dsh-home            DSH home holding .agent-presets/ and settings.yaml\n'
      + '  --profile-name        settings key whose `default` names the default preset\n'
      + '                        (default: agent-presets)\n'
      + '  --generated-at        pin the artifact timestamp; else SOURCE_DATE_EPOCH, else now\n');
    return 0;
  }
  if (!args.candidateContract) {
    process.stderr.write(`preset-gate.mjs: --candidate-contract is required\n${USAGE}\n`);
    return 2;
  }
  if (!YAML_MOD || typeof YAML_MOD.YAML?.parseDocument !== 'function') {
    process.stderr.write(`preset-gate.mjs: no usable YAML implementation — ${
      YAML_MOD_ERROR ?? 'lib/yaml.mjs exports no YAML with parseDocument'}\n`
      + 'A preset file parsed by pattern-matching would put plausible-but-wrong row names in this '
      + 'gate\'s verdict, so no artifact is written. Make lib/yaml.mjs resolvable and re-run.\n');
    return 1;
  }

  let generatedAt;
  try {
    generatedAt = resolveGeneratedAt(args.generatedAt);
  } catch (e) {
    process.stderr.write(`preset-gate.mjs: ${e.message}\n${USAGE}\n`);
    return 2;
  }

  let artifact;
  try {
    artifact = buildArtifact({ ...args, generatedAt });
  } catch (e) {
    process.stderr.write(`preset-gate.mjs: ${e.message}\n`);
    return 1;
  }
  artifact.generatedAt = generatedAt;

  const text = `${JSON.stringify(artifact, null, 2)}\n`;
  if (args.out) {
    const outAbs = isAbsolute(args.out) ? args.out : resolve(process.cwd(), args.out);
    mkdirSync(dirname(outAbs), { recursive: true });
    writeFileSync(outAbs, text, 'utf8');
    process.stderr.write(`preset-gate.mjs: wrote ${outAbs} (verdict ${artifact.verdict}, `
      + `findings ${artifact.counts.BREAKS} BREAKS / ${artifact.counts.RISKY} RISKY / `
      + `${artifact.counts.INFO} INFO, ${artifact.presets.length} preset file(s), `
      + `${artifact.unverified.length} unverified group(s))\n`);
  } else {
    process.stdout.write(text);
  }
  return 0;
}

const invokedDirectly = Boolean(process.argv[1])
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  main().then((code) => process.exit(code)).catch((e) => {
    process.stderr.write(`preset-gate.mjs: unexpected failure: ${e?.stack ?? e}\n`);
    process.exit(1);
  });
}

export { buildArtifact, analyseName, discoverPresets, collectRows, splitSpecifier };
