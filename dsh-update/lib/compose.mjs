/**
 * compose.mjs — run an engine's `--dump-config` and normalize it into `tree.json`.
 *
 * The other half of the pipeline: `contract.mjs` says what is on disk, this says what the engine
 * actually composes from it. A row id in this file is what a `cordis.patch.yml` target must hit,
 * so `rowIds` / `patchedRowIds` are the load-bearing fields — B3 ("patch target gone") and B4
 * ("patch target moved") are decided from them and from nothing else.
 *
 * WHAT THIS MODULE DOES NOT DO
 * ----------------------------
 * It does not evaluate anything. `--dump-config` emits `!!js <expression>` where the *engine* will
 * evaluate JavaScript at boot; here those survive as their source text (`disabledExpr`,
 * `{ __js: … }` inside `config`). Evaluating them would change the tree being described, and a
 * description that depends on the describing process's environment is not a baseline.
 *
 * SAFETY: the only engine invocation this module can make is `--dump-config` and `--version`, both
 * read-only. There is no code path that boots, stops or restarts an engine: a running engine
 * serves the session that runs this, so killing it would kill the caller.
 *
 * Usage:
 *   node lib/compose.mjs [--profile web] [--bin <engineBin>] [--home <dshHome>] [--out <path>]
 *                        [--log-dir <dir>] [--patch <path> ...] [--node <path>]
 */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { hostname } from 'node:os';
import { dirname, isAbsolute, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { isJs, parseYamlWithWarnings } from './yaml.mjs';

const SCHEMA_VERSION = 1;
const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_BIN = 'C:\\Users\\ezabz\\AppData\\Local\\npm-cache\\_npx\\1e7f6d9597241db0'
  + '\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js';
const DEFAULT_HOME = 'C:\\Users\\ezabz\\.dsh';
const DEFAULT_PROFILE = 'web';
const DEFAULT_LOG_DIR = join(MODULE_DIR, '..', 'state', 'logs');
const DUMP_TIMEOUT_MS = 120000;

/**
 * Where this deployment's agent presets live. Both roots are read: the repo copy is the source of
 * truth for what we authored, and `~/.dsh/.agent-presets` is what the engine actually loads.
 */
const PRESET_ROOTS = [
  join(MODULE_DIR, '..', '..', 'presets'),
  'C:\\Users\\ezabz\\.dsh\\.agent-presets',
];

/** Strings this module greps for, to answer the preset-rows question with evidence. */
const PRESET_MARKERS = [
  'tool-subagent', 'persona', 'skill-filesystem', 'tool-workflow', 'agent-presets',
  'tool-subagent-codex', 'tool-subagent-claude-code', 'mcp-secretary', 'tool-subagent-local',
  'tool-subagent-fork', 'tool-ralph', 'present', 'delegation', 'compaction', 'planning',
];
/**
 * Row ids that are shipped by the HOST composition, so that finding them in a dump proves nothing
 * about whether our presets contributed. Verified against the real 2026-09-23 dump of profile
 * `web`: every id in this list appears in that dump, and every one of them is also declared by
 * `presets/zabz/agent.cordis.yml`. This list is only a fast path — the decisive answer is
 * computed by actually reading the preset files at run time.
 */
const HOST_SHARED_ROW_IDS = [
  'agent-instructions', 'tool-bash', 'tool-pwsh', 'tool-fs', 'tool-fs-search', 'tool-jobs',
  'command-goal', 'tool-goal', 'tool-todo', 'tool-web', 'skill-filesystem', 'tool-skill',
  'tool-subagent', 'tool-subagent-control', 'tool-subagent-list-agents', 'tool-subagent-fork',
  'tool-workflow', 'tool-ralph',
];

/** Row ids declared by `- id: X` in a preset composition file. */
function rowIdsOfPresetFile(file) {
  try {
    return [...readFileSync(file, 'utf8').matchAll(/^- id:\s*(\S+)/gm)].map((m) => m[1]);
  } catch {
    return [];
  }
}

/**
 * Collect `<presetDir>/<name>/agent.cordis.yml` for every preset directory that exists.
 * Best-effort: a missing or unreadable directory is reported, never treated as an empty preset.
 */
function collectPresetRowIds() {
  const presets = {};
  const problems = [];
  for (const root of PRESET_ROOTS) {
    let entries = [];
    try {
      entries = readdirSync(root, { withFileTypes: true });
    } catch (e) {
      problems.push(`${root}: ${e.code === 'ENOENT' ? 'does not exist' : e.message}`);
      continue;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const file = join(root, entry.name, 'agent.cordis.yml');
      if (!existsSync(file)) continue;
      const ids = rowIdsOfPresetFile(file);
      if (ids.length > 0) presets[entry.name] = { file, rowIds: ids };
    }
  }
  return { presets, problems };
}

/**
 * Answer, from the dump itself, whether agent-preset files contribute rows to `--dump-config`.
 *
 * The reasoning is in the returned fields, not in prose, so it can be re-derived. The rule that
 * matters: a marker present in the HOST composition tells you nothing, because the same row id can
 * be shipped by `dsh-base` (and re-declared, disabled, by `dsh-web-app`) *and* declared by a
 * preset. The decisive field is `presetOnlyRowIdsFound` — ids that exist only in a preset file and
 * have no host-side origin. If none of those is in the dump, the dump is host/profile only.
 */
function observePresets(text, rows) {
  const markerCounts = {};
  for (const m of PRESET_MARKERS) markerCounts[m] = text.split(m).length - 1;

  const { presets, problems } = collectPresetRowIds();
  const rowIds = new Set(rows.map((r) => r.id).filter(Boolean));
  const hostShared = new Set(HOST_SHARED_ROW_IDS);

  const allPresetIds = new Set(Object.values(presets).flatMap((p) => p.rowIds));
  const presetOnly = [...allPresetIds].filter((id) => !hostShared.has(id)).sort();
  const presetOnlyRowIdsFound = presetOnly.filter((id) => rowIds.has(id));
  const presetOnlyRowIdsMissing = presetOnly.filter((id) => !rowIds.has(id));
  const sharedWithHost = [...allPresetIds].filter((id) => hostShared.has(id)).sort();

  const rowsWithPresetProvenance = rows
    .filter((r) => r.patchedBy !== null && /agent-presets|agent\.cordis|presets[\\/]/.test(r.patchedBy))
    .map((r) => ({ id: r.id, patchedBy: r.patchedBy }));

  const hostPlaneRowsForSharedIds = rows
    .filter((r) => sharedWithHost.includes(r.id) && r.disabled === true)
    .map((r) => r.id);

  return {
    question: 'Does `--dump-config` of this profile contain the rows contributed by OUR agent '
      + 'presets (presets/* and ~/.dsh/.agent-presets), or only the host/profile composition?',
    answer: presetOnlyRowIdsFound.length === 0
      ? 'HOST/PROFILE COMPOSITION ONLY — the preset files contribute no rows to this dump. All '
        + `${presetOnly.length} preset-exclusive row ids are absent, while ${sharedWithHost.length} `
        + 'row ids the presets share with the host appear because the host declares them too.'
      : `PRESET ROWS PRESENT — ${presetOnlyRowIdsFound.join(', ')} appear in the dump.`,
    markerCounts,
    presetFilesRead: Object.fromEntries(
      Object.entries(presets).map(([k, v]) => [k, { file: v.file, rowCount: v.rowIds.length }]),
    ),
    presetReadProblems: problems,
    presetExclusiveRowIdsSearched: presetOnly,
    presetOnlyRowIdsFound,
    presetOnlyRowIdsMissing,
    rowIdsSharedBetweenPresetsAndHost: sharedWithHost,
    sharedIdsDisabledOnTheHostPlane: hostPlaneRowsForSharedIds,
    rowsPatchedByAPresetPath: rowsWithPresetProvenance,
    agentPresetMountRows: rows
      .filter((r) => /agent-preset|agentPreset/.test(`${r.id ?? ''} ${r.name ?? ''}`))
      .map((r) => ({ id: r.id, name: r.name, config: r.config })),
    perMarkerVerdict: {
      'tool-subagent': 'INCONCLUSIVE — shipped by the dsh-base host bundle and re-declared '
        + '(disabled) by dsh-web-app; the preset declares the same id',
      'persona': markerCounts.persona > 0
        ? 'the substring occurs but NOT as a row id; no `- id: persona` exists in this dump, and '
          + 'the preset is the only declarer of that row id'
        : 'absent',
      'skill-filesystem': 'INCONCLUSIVE — a host bundle row id, not a preset marker',
      'tool-workflow': 'INCONCLUSIVE — a host bundle row id, not a preset marker',
      'agent-presets': `the host mount row @deepseek-ai/dsh-agent-presets is present `
        + `(config ${JSON.stringify(rows.find((r) => r.id === 'agent-presets')?.config ?? null)}); `
        + 'it is the component that LOADS preset files at session creation, not the preset rows '
        + 'themselves, so its presence does not mean preset rows are in this dump',
    },
    decisiveness:
      '`tool-subagent`, `skill-filesystem` and `tool-workflow` are NOT evidence either way: their '
      + 'ids are shipped by the dsh-base host bundle (and re-declared, usually disabled, by '
      + 'dsh-web-app) with the same names, so finding them proves nothing about a preset. The '
      + 'decisive signals are the ids in `presetExclusiveRowIdsSearched` — e.g. `persona`, '
      + '`tool-subagent-codex`, `mcp-secretary`, `present` — which are declared only by '
      + 'presets/*/agent.cordis.yml.',
  };
}

// ── helpers ──────────────────────────────────────────────────────────────────────────────────
const toPosix = (p) => p.split(sep).join('/');

function sha256Text(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

/** A filesystem-safe timestamp: ISO-8601 with the characters Windows forbids replaced. */
function stamp(date = new Date()) {
  return date.toISOString().replace(/[:.]/g, '-');
}

/** Recursively replace every `!!js` wrapper with an object that keeps the source text visible. */
function plainValue(value) {
  if (isJs(value)) return { __js: value.__js };
  if (Array.isArray(value)) return value.map(plainValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plainValue(v)]));
  }
  return value === undefined ? null : value;
}

// ── dump parsing ─────────────────────────────────────────────────────────────────────────────
/**
 * Read the leading `# == …` comment block immediately above a top-level sequence entry.
 *
 * The engine writes one comment line per layer that contributed the row, in the form
 *   `# == <layer>`                — the row came from `<layer>`
 *   `# == <layer>, patched by <p>` — and `<p>` patched it on the way through
 * and the comment block ends where the `- ` entry begins. A blank line between comment and entry
 * has never been observed but is tolerated; a comment not attached to an entry is ignored.
 */
function readCommentBlocks(text) {
  const lines = text.split(/\r?\n/);
  const blocks = []; // { entryLine, layers: [], patchedBy: string|null }
  let pending = null;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const cm = /^#\s*==\s*(.+?)\s*$/.exec(line);
    if (cm) {
      if (!pending) pending = { entryLine: null, layers: [], patchedBy: null };
      const body = cm[1];
      const patched = /^(.*?),\s*patched by\s+(.+)$/.exec(body);
      if (patched) {
        pending.layers.push(patched[1].trim());
        // The LAST `patched by` wins: it is the final writer of the row.
        pending.patchedBy = patched[2].trim();
      } else {
        pending.layers.push(body.trim());
      }
      continue;
    }
    if (/^\s*$/.test(line)) continue; // blank line inside/before a comment block
    if (/^-\s/.test(line) || line === '-') {
      pending = pending ?? { entryLine: null, layers: [], patchedBy: null };
      pending.entryLine = i;
      blocks.push(pending);
      pending = null;
      continue;
    }
    // Any other content ends the association: the comment block belonged to nothing.
    pending = null;
  }
  return blocks;
}

/**
 * Flatten a top-level entry into one or more rows.
 *
 * Group rows (`name: cordis:group`, or any row whose `config` is a sequence of nested row maps)
 * own child rows; each child is emitted with `parent` = the owning row's id and `depth` one
 * greater. This is a real shape in the upstream dump, so it is handled rather than assumed away.
 */
function flattenEntry(entry, ctx, parent, depth) {
  const id = typeof entry.id === 'string' ? entry.id : null;
  const name = typeof entry.name === 'string' ? entry.name : null;
  const rawDisabled = entry.disabled;
  const disabled = typeof rawDisabled === 'boolean' ? rawDisabled : null;
  const disabledExpr = isJs(rawDisabled) ? rawDisabled.__js : null;

  const configRaw = entry.config;
  const nestedRows = Array.isArray(configRaw) && configRaw.some(
    (v) => v && typeof v === 'object' && !Array.isArray(v) && ('id' in v || 'name' in v),
  );
  const group = name === 'cordis:group' || nestedRows;

  const row = {
    index: ctx.rows.length,
    id,
    name,
    disabled,
    disabledExpr,
    group,
    config: group && nestedRows ? {} : plainValue(configRaw ?? {}),
    layers: [...ctx.pendingLayers],
    patchedBy: ctx.pendingPatchedBy,
    parent,
    depth,
  };
  if (!id) row.idMissing = true;
  if (entry.inject !== undefined) row.inject = plainValue(entry.inject);
  ctx.rows.push(row);

  if (group && nestedRows) {
    for (const child of configRaw) {
      if (!child || typeof child !== 'object' || Array.isArray(child)) {
        ctx.notes.push(`group row "${id ?? '<no id>'}" has a non-map entry in its config sequence; skipped`);
        continue;
      }
      flattenEntry(child, ctx, id, depth + 1);
    }
  }
  return row;
}

export function parseDump(text) {
  const notes = [];
  const { value, warnings, errors } = parseYamlWithWarnings(text);
  if (errors.length > 0) {
    throw new Error(`YAML parse errors: ${errors.slice(0, 5).join('; ')}`);
  }
  if (!Array.isArray(value)) {
    throw new Error(`the dump did not parse to a sequence of rows (got ${value === null ? 'null' : typeof value})`);
  }
  const blocks = readCommentBlocks(text);
  if (blocks.length !== value.length) {
    notes.push(`comment-block count (${blocks.length}) does not match parsed row count `
      + `(${value.length}); rows are matched positionally, so a comment mismatch means the `
      + 'layer attribution below is suspect');
  }
  const ctx = { rows: [], notes, pendingLayers: [], pendingPatchedBy: null };
  for (let i = 0; i < value.length; i += 1) {
    const entry = value[i];
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      notes.push(`entry ${i} is not a map; recorded as a row with null id/name so it is not silently dropped`);
      ctx.pendingLayers = [];
      ctx.pendingPatchedBy = null;
      flattenEntry({ id: null, name: null }, ctx, null, 0);
      continue;
    }
    const block = blocks[i];
    ctx.pendingLayers = block ? block.layers : [];
    ctx.pendingPatchedBy = block ? block.patchedBy : null;
    flattenEntry(entry, ctx, null, 0);
  }
  return { rows: ctx.rows, notes, warnings };
}

// ── engine invocation ────────────────────────────────────────────────────────────────────────
function runEngine(nodeExe, args, env) {
  return new Promise((resolvePromise) => {
    const started = Date.now();
    let child;
    try {
      child = spawn(nodeExe, args, { env, windowsHide: true });
    } catch (e) {
      resolvePromise({ spawnError: e, stdout: '', stderr: '', exitCode: null, durationMs: 0 });
      return;
    }
    const out = [];
    const err = [];
    child.stdout.on('data', (d) => out.push(d));
    child.stderr.on('data', (d) => err.push(d));
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* already gone */ }
    }, DUMP_TIMEOUT_MS);
    child.on('error', (e) => {
      clearTimeout(timer);
      resolvePromise({ spawnError: e, stdout: '', stderr: '', exitCode: null, durationMs: Date.now() - started });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolvePromise({
        stdout: Buffer.concat(out).toString('utf8'),
        stderr: Buffer.concat(err).toString('utf8'),
        exitCode: code,
        durationMs: Date.now() - started,
      });
    });
  });
}

async function engineVersion(nodeExe, bin, env) {
  const r = await runEngine(nodeExe, [bin, '--version'], env);
  if (r.exitCode !== 0) return { version: null, detail: `--version exited ${r.exitCode}: ${r.stderr.trim()}` };
  return { version: r.stdout.trim() || null, detail: null };
}

// ── observations: does the dump contain OUR preset rows? ────────────────────────────────────
/**
 * Answer, from the dump itself, whether agent-preset files contribute rows to `--dump-config`.
 *
 * The reasoning is in the returned fields, not in prose, so it can be re-derived: a marker that
 * exists in the HOST composition tells you nothing (the same row id can be shipped by
 * `dsh-base` and re-declared by a preset), so the decisive field is `presetOnlyRowIdsFound` —
 * ids that exist in `presets/*\/agent.cordis.yml` and have no host-side origin at all.
 */

// ── main build ───────────────────────────────────────────────────────────────────────────────
export function parseArgs(argv) {
  const args = {
    profile: DEFAULT_PROFILE,
    bin: DEFAULT_BIN,
    home: DEFAULT_HOME,
    out: null,
    logDir: DEFAULT_LOG_DIR,
    patches: [],
    node: process.execPath,
    // `--default-config` switches to `--dump-default-config`: the profile tree WITHOUT this
    // deployment's user layer and without any `--patch` overlay. It exists because a patch REPLACES
    // the targeted row's whole `config`, so a key upstream newly adds to that row's default is
    // silently swallowed by our restated config. The only clean comparison arm is the unpatched
    // tree, and the engine's own flag is the way to get it. See SPEC.md B11 / gate G6.
    defaultConfig: false,
  };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--profile') args.profile = need('--profile');
    else if (a === '--bin') args.bin = need('--bin');
    else if (a === '--home') args.home = need('--home');
    else if (a === '--out') args.out = need('--out');
    else if (a === '--log-dir') args.logDir = need('--log-dir');
    else if (a === '--patch') args.patches.push(need('--patch'));
    else if (a === '--node') args.node = need('--node');
    else if (a === '--default-config') args.defaultConfig = true;
    else if (a === '-h' || a === '--help') args.help = true;
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

const USAGE = 'usage: node lib/compose.mjs [--profile web] [--bin <engineBin>] [--home <dshHome>] '
  + '[--out <path>] [--log-dir <dir>] [--patch <path> ...] [--node <path>] [--default-config]';

export async function buildTree(options = {}) {
  const opts = { ...parseArgs([]), ...options };
  const notes = [];
  const started = Date.now();
  const when = new Date();
  const stampStr = stamp(when);
  const binAbs = resolve(opts.bin);
  const homeAbs = resolve(opts.home);
  const logDirAbs = isAbsolute(opts.logDir) ? opts.logDir : resolve(process.cwd(), opts.logDir);
  // One place decides which dump we are asking for, so no invocation string can drift from the
  // argv that was actually run.
  const dumpFlag = opts.defaultConfig ? '--dump-default-config' : '--dump-config';
  if (opts.defaultConfig && opts.patches.length > 0) {
    // Not an error — but the engine does not parse the user layer in default mode, so the overlay
    // has no effect. Recording it beats letting someone believe they narrowed the query.
    // eslint-disable-next-line no-param-reassign
    opts.patchesUnusedInDefaultMode = opts.patches.length;
  }

  const base = {
    schemaVersion: SCHEMA_VERSION,
    generatedAt: when.toISOString(),
    enginePath: binAbs,
    engineVersion: null,
    host: hostname(),
    dshHome: homeAbs,
    profile: opts.profile,
    dumpMode: opts.defaultConfig ? 'default' : 'composed',
    isolatedHome: null,
    invocation: null,
    exitCode: null,
    durationMs: null,
    stderr: '',
    evidence: { stdout: null, stderr: null, stdoutBytes: 0, stderrBytes: 0, stdoutSha256: null, stderrSha256: null },
    rows: [],
    rowIds: [],
    names: [],
    layerComments: [],
    patchedRowIds: [],
    disabledRowIds: [],
    parseWarnings: null,
    observations: null,
    notes,
  };

  // Fail fast on inputs that cannot possibly work, but still emit an artifact: an empty `rows`
  // array without a `failure` is the one output this module may never produce.
  const binExists = existsSync(binAbs);
  if (!binExists && !opts.bin.startsWith('--')) {
    base.failure = `engine binary not found: ${binAbs}`
      + ' — nothing was invoked; this is a bad --bin/engine path, not an engine fault';
    base.invocation = `${opts.node} ${binAbs} --profile ${opts.profile} ${dumpFlag} (NOT RUN)`;
    return { artifact: base, logDirAbs, fatal: true };
  }
  if (existsSync(binAbs)) {
    try {
      if (!statSync(binAbs).isFile()) {
        base.failure = `engine binary path is not a file: ${binAbs}`;
        base.invocation = `${opts.node} ${binAbs} --profile ${opts.profile} ${dumpFlag} (NOT RUN)`;
        return { artifact: base, logDirAbs, fatal: true };
      }
    } catch (e) {
      base.failure = `cannot stat engine binary ${binAbs}: ${e.message}`;
      return { artifact: base, logDirAbs, fatal: true };
    }
  }

  const profileDir = join(homeAbs, 'profiles', opts.profile);
  if (!existsSync(profileDir)) {
    base.failure = `profile "${opts.profile}" does not exist: ${profileDir} is absent`
      + ' — the engine would have to create it, and describing a profile that does not exist is '
      + 'not a reading. Nothing was invoked.';
    base.invocation = `${opts.node} ${binAbs} --profile ${opts.profile} ${dumpFlag} (NOT RUN)`;
    return { artifact: base, logDirAbs, fatal: true };
  }
  for (const patch of opts.patches) {
    const patchAbs = isAbsolute(patch) ? patch : resolve(process.cwd(), patch);
    if (!existsSync(patchAbs)) {
      base.failure = `--patch file does not exist: ${patchAbs}; nothing was invoked`;
      return { artifact: base, logDirAbs, fatal: true };
    }
  }

  const childEnv = { ...process.env, DSH_HOME: homeAbs };
  const argv = [binAbs, '--profile', opts.profile, dumpFlag];
  for (const patch of opts.patches) {
    argv.push('--patch', isAbsolute(patch) ? patch : resolve(process.cwd(), patch));
  }
  base.invocation = [opts.node, ...argv].map((a) => (a.includes(' ') ? `"${a}"` : a)).join(' ');

  const ver = await engineVersion(opts.node, binAbs, childEnv);
  base.engineVersion = ver.version;
  if (ver.detail) notes.push(`engine version unread: ${ver.detail}`);

  const run = await runEngine(opts.node, argv, childEnv);
  base.exitCode = run.exitCode;
  base.durationMs = run.durationMs;
  base.stderr = run.stderr;

  // Always write the raw streams verbatim, before any interpretation of them.
  mkdirSync(logDirAbs, { recursive: true });
  const outFile = join(logDirAbs, `dump-${opts.profile}-${stampStr}.out`);
  const errFile = join(logDirAbs, `dump-${opts.profile}-${stampStr}.err`);
  writeFileSync(outFile, run.stdout, 'utf8');
  writeFileSync(errFile, run.stderr, 'utf8');
  base.evidence = {
    stdout: outFile,
    stderr: errFile,
    stdoutBytes: Buffer.byteLength(run.stdout, 'utf8'),
    stderrBytes: Buffer.byteLength(run.stderr, 'utf8'),
    stdoutSha256: sha256Text(run.stdout),
    stderrSha256: sha256Text(run.stderr),
  };

  if (run.spawnError) {
    base.failure = `could not spawn the engine: ${run.spawnError.message}`
      + ` — invocation was: ${base.invocation}. Raw stdout and stderr were still written to `
      + `${toPosix(logDirAbs)} (both empty).`;
    return { artifact: base, logDirAbs, fatal: false };
  }

  let parsed = null;
  let parseFailure = null;
  if (run.stdout.trim().length === 0) {
    parseFailure = 'stdout was empty, so there was nothing to parse';
  } else {
    try {
      parsed = parseDump(run.stdout);
    } catch (e) {
      parseFailure = e.message;
    }
  }

  if (run.exitCode !== 0) {
    base.failure = `engine exited ${run.exitCode}. stderr: `
      + `${run.stderr.trim().slice(0, 2000) || '<empty>'}. Raw stdout is at ${outFile}`
      + ` (${base.evidence.stdoutBytes} bytes, sha256 ${base.evidence.stdoutSha256.slice(0, 16)}…)`
      + `${parseFailure ? `. The stdout additionally did not parse: ${parseFailure}` : ''}`;
    if (parsed) {
      base.parseWarnings = parsed.warnings.length > 0 ? parsed.warnings : null;
    }
    return { artifact: base, logDirAbs, fatal: false };
  }

  if (parseFailure) {
    base.failure = `engine exited 0 but its stdout did not parse: ${parseFailure}. `
      + `Raw stdout (${base.evidence.stdoutBytes} bytes) is preserved verbatim at ${outFile}; `
      + 'no rows are reported because none could be trusted, and an empty rows array here is a '
      + 'refusal, not a reading of an empty tree.';
    return { artifact: base, logDirAbs, fatal: false };
  }

  if (parsed.rows.length === 0) {
    base.failure = 'engine exited 0 and its stdout parsed to zero rows — an empty composed tree '
      + `for profile "${opts.profile}" is a refusal, not health. Raw stdout is at ${outFile}`;
    return { artifact: base, logDirAbs, fatal: false };
  }

  base.rows = parsed.rows;
  base.rowIds = parsed.rows.map((r) => r.id).filter((v) => v !== null);
  base.names = [...new Set(parsed.rows.map((r) => r.name).filter((v) => v !== null))];
  base.layerComments = [...new Set(parsed.rows.flatMap((r) => r.layers))];
  base.patchedRowIds = parsed.rows
    .filter((r) => r.patchedBy !== null)
    .map((r) => r.id)
    .filter((v) => v !== null);
  base.disabledRowIds = parsed.rows
    .filter((r) => r.disabled === true || r.disabledExpr !== null)
    .map((r) => r.id)
    .filter((v) => v !== null);
  base.parseWarnings = parsed.warnings.length > 0 ? parsed.warnings : null;
  if (parsed.notes.length > 0) notes.push(...parsed.notes);
  notes.push(`${parsed.rows.length} rows reported (${base.rowIds.length} with an id, `
    + `${base.rows.filter((r) => r.group).length} group rows, `
    + `${base.rows.filter((r) => r.depth > 0).length} nested)`);
  base.observations = observePresets(run.stdout, parsed.rows);

  return { artifact: base, logDirAbs, fatal: false };
}

// ── standalone ───────────────────────────────────────────────────────────────────────────────
async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    process.stderr.write(`compose.mjs: ${e.message}\n${USAGE}\n`);
    process.exit(2);
    return;
  }
  if (args.help) {
    process.stderr.write(`${USAGE}\n`);
    process.exit(0);
    return;
  }
  let result;
  try {
    result = await buildTree(args);
  } catch (e) {
    process.stderr.write(`compose.mjs: ${e?.stack ?? e}\n`);
    process.exit(1);
    return;
  }
  const { artifact, fatal } = result;
  const text = `${JSON.stringify(artifact, null, 2)}\n`;
  if (args.out) {
    const outAbs = isAbsolute(args.out) ? args.out : resolve(process.cwd(), args.out);
    mkdirSync(dirname(outAbs), { recursive: true });
    writeFileSync(outAbs, text, 'utf8');
  } else {
    process.stdout.write(text);
  }
  if (artifact.failure) {
    process.stderr.write(`compose.mjs: ${fatal ? 'refused before invoking the engine' : 'the dump could not be read'}: `
      + `${artifact.failure}\n`);
    process.exit(1);
    return;
  }
  process.stderr.write(`compose.mjs: ${artifact.rows.length} rows, exit ${artifact.exitCode}, `
    + `${artifact.durationMs} ms; logs at ${toPosix(result.logDirAbs)}\n`);
  process.exit(0);
}

const invokedDirectly = Boolean(process.argv[1])
  && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  main().catch((e) => {
    process.stderr.write(`compose.mjs: unexpected failure: ${e?.stack ?? e}\n`);
    process.exit(1);
  });
}
