#!/usr/bin/env node
/**
 * make-preset-rows.mjs — convert directory-shaped agent presets into 0.1.7 preset ROWS.
 *
 * THE MIGRATION THIS EXISTS FOR
 * -----------------------------
 * On the 0.1.5 line a preset is a DIRECTORY: `~/.dsh/.agent-presets/<id>/agent.cordis.yml`, found
 * by `readdir` in `@deepseek-ai/dsh-agent-presets` (`USER_PRESET_DIR = '.agent-presets'`).
 *
 * On the 0.1.7 line that package is gone. `@deepseek-ai/dsh-agent-preset-registry` has no `readdir`
 * and no `readFile`: it exposes `register(definition)`, and a preset is a *composition row* —
 * `id=preset-<name> name=@deepseek-ai/dsh-agent-preset config={"id","order","plugins"}` — whose
 * `plugins` array is exactly the row list our `agent.cordis.yml` files already contain
 * (`@deepseek-ai/dsh-agent-preset`'s own schema: `z.object({ id, name, description, order:
 * z.number(), plugins: z.array(z.any()).required() })`).
 *
 * So the conversion is mechanical: wrap each preset's row list in a `preset-<name>` row and insert
 * it. Upgrading WITHOUT this conversion leaves `settings.agent-presets.default: zabz` naming a
 * preset that does not exist; sessions fall back to a shipped preset and the persona is lost
 * silently, with no error. Hence a generated artefact plus `--check` in CI rather than a one-off.
 *
 * WHY `insert:` AND NOT AN ID-TARGETED PATCH
 * -----------------------------------------
 * `applyEntryPatches` in `@deepseek-ai/dsh-app-boot` is the patch algorithm (`--dump-config` and
 * boot share it). A patch with `insert` and no `id` does `data.push(...insert)` — it adds rows to an
 * empty patch root, so it needs no existing row to target. The shipped four presets keep their own
 * rows; ours are appended after them.
 *
 * WHY THE ORDER IS 10 + NAME INDEX
 * --------------------------------
 * The four shipped presets take `order` 1-4 (`standard`, `ptc`, `minimal`, `cordis`). Ours must sort
 * after them, so the base is 10. Within our own set the rule is *ascending name order*, because it
 * is stable without reading any other file, and it is deliberately a function of the WHOLE
 * discovered set — `--names zabz` filters what is emitted without renumbering, so a preset's order
 * never moves because another preset was filtered out.
 *
 * WHY THE OUTPUT IS GENERATED YET THE `plugins` ARRAY IS VERBATIM
 * --------------------------------------------------------------
 * `plugins` is the preset's own row list, re-serialised from the source file with the same keys in
 * the same order. Nothing is rewritten, reordered, defaulted or dropped. `!!js` scalars are the one
 * place where that needs care, and the care is measured rather than assumed:
 *
 *   `YAML.stringify(value, { customTags: CUSTOM_TAGS })` — the obvious call — writes
 *   `!!js undefined` for every expression, and re-parsing that yields the literal string
 *   "undefined". VERIFIED 2026-09-28 against yaml 2.9.0: `jsTag.stringify` is called once with the
 *   `{ __js }` wrapper and its return value is discarded. Silently, that would have destroyed every
 *   `disabled: !!js process.platform === 'win32'` gate. So the wrapper is replaced by a unique
 *   sentinel STRING before `stringify`, and the sentinel is substituted back to `!!js <source text>`
 *   textually afterwards — which is also why the expression text can be byte-identical to the
 *   source.
 *
 * Every emission is therefore re-parsed with the unmodified parser (`PARSE_OPTIONS`) and compared
 * against the input before anything is written; a mismatch is a hard error. This converter cannot
 * silently emit a lost expression.
 *
 * WHY THE ROWS ALSO GO INTO A MANAGED BLOCK IN `profiles/web/cordis.patch.yml`
 * ---------------------------------------------------------------------------
 * The standalone artefact above only does anything if something passes `--patch`, and NOTHING does:
 * a profile's patch layers are its bundles' own patches, then `$DSH_HOME/profiles/<name>/cordis.patch.yml`,
 * then `$DSH_HOME/cordis.patch.yml`, and neither `scripts/sync.py` nor `multi-window/dshw.ps1`
 * mentions `--patch` at all (both searched, no match). Left as a loose file, the migration would
 * never happen and nothing would say so. So the same three `insert:` entries are also written into
 * the layer the engine ALREADY loads, inside a MARKED MANAGED BLOCK — the convention this repo
 * already established for exactly this problem in that very file
 * (`scripts/mesh-provider-install.ps1` writes the `mesh-provider-install` one there).
 *
 * The block is spliced, never authored: `--install` replaces ONLY the lines between the two marker
 * lines, proves the rest of the file is byte-identical, and re-checks itself before writing; it is
 * idempotent, it creates the block before the final `]` when absent, and it refuses — changing
 * nothing — when the markers are unbalanced, duplicated, or the file does not parse.
 *
 * WHY THE BLOCK IS FLOW STYLE, AND WHAT "VERBATIM" CAN MEAN THERE
 * --------------------------------------------------------------
 * That file is ONE YAML FLOW collection (`[ { … }, { … } ]`), and a block collection inside a flow
 * collection is a parse error — "missed comma between flow collection entries", measured against
 * that file by `dsh --profile web --dump-config` and recorded in the file's own commentary above
 * `sshArgs`. So the block carries the SAME THREE PATCH ENTRIES re-emitted in flow style rather than
 * the block-style bytes of the standalone file. What stays verbatim is every scalar that carries
 * meaning: `id`, `name`, `config.id`, `config.order`, every plugin row, and every `!!js` source text
 * byte for byte. The two artefacts are proven to deep-equal one another (below, and in
 * `dsh-update/tests/preset-rows/`), which is the strongest claim a different serialisation allows.
 *
 * Usage:
 *   node scripts/make-preset-rows.mjs [--presets-dir <dir>] [--out <file>] [--check] [--names a,b,c]
 *                                    [--install] [--install-target <file>] [--print-block]
 *
 *   --presets-dir    directory of `<name>/agent.cordis.yml` presets (default: <repo>/presets)
 *   --out            file to write (default: <repo>/profiles/web/presets.generated.patch.yml)
 *   --check          compare the committed artefact(s) with what would be generated; write nothing.
 *                    Exit 1 on drift or a missing file. It covers BOTH artefacts: the standalone
 *                    `--out` file and the managed block in `--install-target`. With `--names` the
 *                    emitted set is narrowed, so the block check is skipped and said to be.
 *   --install        write the standalone file AND splice the three entries into the managed block
 *                    in `--install-target`. Refuses with `--names` (a filtered block would silently
 *                    drop presets from the boot layer).
 *   --install-target file carrying the managed block (default: <repo>/profiles/web/cordis.patch.yml)
 *   --print-block    print the managed block body (indented, exactly as it appears in the file) and
 *                    write nothing.
 *   --names          comma-separated subset to emit; orders still come from the full set.
 *
 * Exit codes: 0 ok, 1 failure (drift, unreadable/invalid preset, self-check mismatch, bad markers),
 * 2 usage.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import { JS_TAG_URI, PARSE_OPTIONS, YAML, yamlResolvedFrom } from '../dsh-update/lib/yaml.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, '..');

const DEFAULT_PRESETS_DIR = join(REPO_ROOT, 'presets');
const DEFAULT_OUT = join(REPO_ROOT, 'profiles', 'web', 'presets.generated.patch.yml');
const DEFAULT_INSTALL_TARGET = join(REPO_ROOT, 'profiles', 'web', 'cordis.patch.yml');
const PRESET_FILE_NAME = 'agent.cordis.yml';

/** `id` of the plugin row that registers a preset — the row `name` every emitted row carries. */
const PRESET_PLUGIN_NAME = '@deepseek-ai/dsh-agent-preset';

/** The four shipped presets use `order` 1-4. Ours start here so they sort after every shipped one. */
const ORDER_BASE = 10;

/** Sentinel namespace for the `!!js` substitution. A source file containing it is rejected. */
const SENTINEL_PREFIX = '__DSH_JSEXPR_';

// ── the managed block in the profile patch layer ─────────────────────────────────────────────
/** Region id. One word, used in both marker lines, so `grep` finds the whole story. */
const BLOCK_ID = 'preset-rows';
/** The canonical marker lines. Written verbatim by `--install`; matched by prefix, trimmed. */
const MARKER_BEGIN = `# <<< ${BLOCK_ID}: BEGIN managed block — written by `
  + 'scripts/make-preset-rows.mjs, do not hand-edit <<<';
const MARKER_END = `# <<< ${BLOCK_ID}: END managed block <<<`;
const MARKER_BEGIN_RE = /^#\s*<<<\s*preset-rows:\s*BEGIN managed block\b/;
const MARKER_END_RE = /^#\s*<<<\s*preset-rows:\s*END managed block\b/;
/** Indentation of every line the block owns, matching the file's own two-space flow style. */
const BLOCK_INDENT = '  ';
/**
 * `lineWidth` for the flow rendering. Measured on the real three presets (2026-09-28) — NOT 0, and
 * not the emitter's default 80:
 *
 *   width    0 :    3 lines / ~120 KB, one ~40 KB line per entry — legal, unreadable, and a change
 *                 anywhere makes the whole line a diff.
 *   width   80 : 2248 lines /  123 KB, max line 147
 *   width  120 : 1573 lines /  102 KB, max line 154
 *   width  160 : 1338 lines /   95 KB, max line 213  <- this
 *
 * Beyond 160 the savings flatten out (the data itself is ~79 KB), so this is the knee: wrapped
 * enough that a preset change is a localised diff, long lines still bounded.
 */
const FLOW_LINE_WIDTH = 160;

const USAGE = 'usage: node scripts/make-preset-rows.mjs [--presets-dir <dir>] [--out <file>] '
  + '[--check] [--names a,b,c] [--install] [--install-target <file>] [--print-block]';

// ── plain-scalar safety ──────────────────────────────────────────────────────────────────────
// An emitted `!!js` value must survive as the SAME source text. A plain scalar is byte-identical to
// the source expression, so it is preferred; anything a plain scalar cannot carry is single-quoted,
// which still decodes to the same string (the re-parse check below is what actually guarantees it).
//
// THE RULE IS CONTEXT-DEPENDENT, and this was measured rather than reasoned about. In a BLOCK
// collection a plain scalar may contain `,` `[` `]` `{` `}`; inside a FLOW collection those are
// indicator characters and end the scalar. Rendering the flow block with the block rule truncated
// `process.getBuiltinModule('node:url').fileURLToPath(new URL('skills/', baseUrl))` at the comma,
// which the very next self-check caught on 2026-09-28 — the `!!js` value came back as
// `…new URL('skills/'` and the document structure no longer matched. So `plainSafe` takes the
// style, and the flow block quotes every expression that carries a flow indicator.
const PLAIN_UNSAFE_FIRST = /^[\s\-?:,[\]{}#&*!|>'"%@`]/;
const PLAIN_RESERVED = /^(?:true|false|null|yes|no|on|off|~|y|n|True|False|Null|TRUE|FALSE|NULL|Yes|No|On|Off|YES|NO|ON|OFF|Y|N)$/;
/** Characters that may not appear in a plain scalar inside a flow collection (YAML 1.2 §7.3.3). */
const FLOW_INDICATORS = /[,[\]{}]/;

/** `style` is `block` (default) or `flow`; the flow rules are strictly stricter. */
function plainSafe(text, style = 'block') {
  if (typeof text !== 'string' || text.length === 0) return false;
  if (/[\n\r\t]/.test(text)) return false;
  if (/^\s|\s$/.test(text)) return false;
  if (PLAIN_UNSAFE_FIRST.test(text)) return false;
  if (text.includes(': ') || text.endsWith(':') || text.includes(' #')) return false;
  if (style === 'flow' && FLOW_INDICATORS.test(text)) return false;
  if (PLAIN_RESERVED.test(text)) return false;
  return true;
}

const singleQuote = (text) => `'${text.replace(/'/g, "''")}'`;
const jsValueText = (expr, style = 'block') => (plainSafe(expr, style) ? expr : singleQuote(expr));

// ── `!!js` handling ──────────────────────────────────────────────────────────────────────────
const isJs = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v) && typeof v.__js === 'string';

/**
 * Replace every `{ __js }` wrapper with a sentinel string, collecting the source texts in order.
 * Returns `{ value, exprs }`, where `exprs[i]` is the source text of `SENTINEL_PREFIX + i`.
 */
function replaceJsWithSentinels(node, exprs) {
  if (isJs(node)) {
    const index = exprs.push(node.__js) - 1;
    return `${SENTINEL_PREFIX}${String(index).padStart(4, '0')}__`;
  }
  if (Array.isArray(node)) return node.map((child) => replaceJsWithSentinels(child, exprs));
  if (node && typeof node === 'object') {
    return Object.fromEntries(
      Object.entries(node).map(([key, child]) => [key, replaceJsWithSentinels(child, exprs)]),
    );
  }
  return node;
}

/** Substitute the emitted sentinels back to `!!js <source text>`, longest index first. */
function restoreJsText(yamlText, exprs, style = 'block') {
  let text = yamlText;
  for (let i = exprs.length - 1; i >= 0; i -= 1) {
    const sentinel = `${SENTINEL_PREFIX}${String(i).padStart(4, '0')}__`;
    // `stringify` may quote the sentinel in some future release; accept every form it could take.
    const pattern = new RegExp(`!!str ${sentinel}|'${sentinel}'|"${sentinel}"|${sentinel}`, 'g');
    text = text.replace(pattern, `!!js ${jsValueText(exprs[i], style)}`);
  }
  return text;
}

/** Every `!!js` source text in a parsed value, in document order. */
function collectJsTexts(node, acc = []) {
  if (isJs(node)) acc.push(node.__js);
  else if (Array.isArray(node)) node.forEach((child) => collectJsTexts(child, acc));
  else if (node && typeof node === 'object') Object.values(node).forEach((child) => collectJsTexts(child, acc));
  return acc;
}

// ── discovery and reading ────────────────────────────────────────────────────────────────────
/**
 * Preset names, ascending by name. `Array.prototype.sort` on strings is code-unit order, so the
 * result does not depend on locale, filesystem enumeration order or the platform.
 */
function discoverPresetNames(presetsDir) {
  let entries;
  try {
    entries = readdirSync(presetsDir, { withFileTypes: true });
  } catch (e) {
    throw new Error(`cannot read --presets-dir ${presetsDir}: ${e.message}`);
  }
  const names = entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => existsSync(join(presetsDir, name, PRESET_FILE_NAME)))
    .sort();
  if (names.length === 0) {
    throw new Error(`no preset found under ${presetsDir}: expected at least one `
      + `<name>/${PRESET_FILE_NAME}. An empty result is a failure, not an empty success.`);
  }
  return names;
}

/**
 * Parse one preset's `agent.cordis.yml` into its row list.
 *
 * The file is a top-level YAML sequence of `{id, name, config, disabled, group, isolate}` maps. A
 * file that parses to anything else is rejected rather than coerced: a converter that silently
 * dropped the rows it did not understand would lose capability without saying so.
 */
function readPresetRows(presetsDir, name) {
  const file = join(presetsDir, name, PRESET_FILE_NAME);
  let text;
  try {
    text = readFileSync(file, 'utf8');
  } catch (e) {
    throw new Error(`cannot read preset ${file}: ${e.message}`);
  }
  if (text.includes(SENTINEL_PREFIX)) {
    throw new Error(`preset ${file} already contains the marker ${SENTINEL_PREFIX}, which this `
      + 'converter uses internally to carry `!!js` source text; refusing to guess.');
  }
  let rows;
  try {
    rows = YAML.parse(text, PARSE_OPTIONS);
  } catch (e) {
    throw new Error(`cannot parse preset ${file}: ${e.message}`);
  }
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(`preset ${file} did not parse to a non-empty top-level sequence `
      + `(got ${rows === null ? 'null' : Array.isArray(rows) ? 'empty sequence' : typeof rows})`);
  }
  rows.forEach((row, index) => {
    if (!row || typeof row !== 'object' || Array.isArray(row)) {
      throw new Error(`preset ${file}: entry ${index + 1} is not a mapping`);
    }
    if (typeof row.id !== 'string' || row.id.length === 0) {
      throw new Error(`preset ${file}: entry ${index + 1} has no string id`);
    }
    if (typeof row.name !== 'string' || row.name.length === 0) {
      throw new Error(`preset ${file}: entry ${index + 1} (id ${row.id}) has no string name`);
    }
  });
  return { file, text, rows, sha256: createHash('sha256').update(text, 'utf8').digest('hex') };
}

// ── the generated document ───────────────────────────────────────────────────────────────────
function header(rowsByPreset, exprs) {
  const yamlInfo = yamlResolvedFrom();
  const lines = [
    '# GENERATED FILE — DO NOT EDIT BY HAND.',
    '#',
    '# Written by `scripts/make-preset-rows.mjs`. Edit that converter, not this file; `--check`',
    '# fails whenever this file and the converter disagree.',
    '#',
    '# WHAT THIS IS',
    '#   In 0.1.7 a preset is a composition ROW, not a directory: local preset-directory discovery is',
    '#   gone (`@deepseek-ai/dsh-agent-presets` is removed, and `@deepseek-ai/dsh-agent-preset-registry`',
    '#   has no readdir/readFile — it takes definitions programmatically). Each entry below inserts one',
    '#   `preset-<name>` row whose `config.plugins` is that preset\'s own row list, verbatim in shape.',
    '#   Without it, `settings.agent-presets.default: <name>` names a preset that does not exist and the',
    '#   session falls back to a shipped preset — silently, with no error.',
    '#',
    '# HOW TO APPLY IT',
    '#   Add this file to the profile\'s patch layers, e.g.',
    '#     node dsh-update/lib/compose.mjs --profile web --patch profiles/web/presets.generated.patch.yml \\',
    '#          --bin <0.1.7 engine bin.js> --out %TEMP%/verify.json --log-dir %TEMP%/logs',
    '#   Regenerate with:',
    '#     node scripts/make-preset-rows.mjs',
    '#',
    `# ORDER RULE  ${ORDER_BASE} + index in ascending name order over the whole discovered set. The four`,
    '#   shipped presets take order 1-4 (`standard`, `ptc`, `minimal`, `cordis`), so ours sort after',
    '#   them. The numbering is a function of the full set, not of --names, so filtering never',
    '#   renumbers a preset.',
    '#',
    '# SOURCES (sha256 of the exact bytes each row list was read from)',
  ];
  for (const item of rowsByPreset) {
    lines.push(`#   presets/${item.name}/${PRESET_FILE_NAME}  rows=${item.rows.length}  `
      + `sha256=${item.sha256}`);
  }
  lines.push(
    '#',
    `# \`!!js\` expressions carried: ${exprs.length} (source text preserved; see the converter for why`,
    '#   `YAML.stringify` + `customTags` cannot be used for this).',
    `# yaml ${yamlInfo?.version ?? 'unknown'} from ${yamlInfo?.root ?? 'unknown'}`,
    `# tag: ${JS_TAG_URI}`,
    '# No timestamp is recorded deliberately: the output must be byte-stable for `--check`.',
    '#',
  );
  return `${lines.join('\n')}\n`;
}

/**
 * Build the patch document text for the selected presets.
 *
 * One top-level patch entry per preset: `- insert:` with a one-row list. `insert` without an `id`
 * appends to the root entry list (`dsh-app-boot` `applyEntryPatches`), which is what makes this work
 * against a base tree that has no row of ours to target.
 */
function patchEntries(items) {
  return items.map((item) => ({
    insert: [{
      id: `preset-${item.name}`,
      name: PRESET_PLUGIN_NAME,
      config: {
        id: item.name,
        order: item.order,
        plugins: item.rows,
      },
    }],
  }));
}

function buildDocument(items, exprs) {
  const wrapped = replaceJsWithSentinels(patchEntries(items), exprs);
  const body = restoreJsText(YAML.stringify(wrapped, {
    // Deterministic, and hostile to nothing: no anchors/aliases from repeated values, and no line
    // folding that could re-wrap a long expression or a persona string.
    aliasDuplicateObjects: false,
    lineWidth: 0,
  }), exprs);
  return header(items, exprs) + body;
}

// ── the managed block: generation, splicing, checking ────────────────────────────────────────
/** The `#` commentary written inside the block, above the entries. Regenerated on every run. */
function blockCommentLines(items) {
  return [
    '# ── the local agent presets, as 0.1.7 composition ROWS ─────────────────────',
    '# On the 0.1.7 line a preset is a ROW, not a directory: local preset-directory',
    '# discovery was removed, so `presets/<name>/agent.cordis.yml` is no longer read',
    '# from disk at all. Each `insert:` below appends one `preset-<name>` row whose',
    "# `config.plugins` is that preset's own row list, taken from the file named.",
    '# Written by `node scripts/make-preset-rows.mjs --install`; `--check` fails when',
    '# this block and presets/*/agent.cordis.yml disagree. The standalone artifact for',
    '# composing with `--patch` is profiles/web/presets.generated.patch.yml.',
    ...items.map((item) => `#   presets/${item.name}/${PRESET_FILE_NAME}  rows=${item.rows.length}`
      + `  order=${item.order}  sha256=${item.sha256}`),
  ];
}

/**
 * The block's body: the same patch entries as the standalone file, in FLOW style, indented, one
 * trailing comma each (a flow sequence accepts the trailing comma before the file's own `]`).
 *
 * Each entry is stringified on its own rather than the whole array, so no bracket-stripping
 * heuristic stands between the emitter and the file: what lands between the markers is exactly
 * what `YAML.stringify` produced for the entries, plus indentation. The caller runs `selfCheck`
 * on the result (re-parsed inside `[ … ]`) before it is allowed anywhere near disk.
 */
function buildBlockBodyLines(items) {
  const exprs = [];
  const wrapped = replaceJsWithSentinels(patchEntries(items), exprs);
  const entryTexts = wrapped.map((entry) => restoreJsText(YAML.stringify(entry, {
    flow: true,
    aliasDuplicateObjects: false,
    lineWidth: FLOW_LINE_WIDTH,
  }), exprs, 'flow').replace(/\n$/, ''));
  const rowLines = entryTexts.flatMap((text) => `${text},`.split('\n'));
  const lines = [...blockCommentLines(items), ...rowLines];
  return {
    exprs,
    /** How many patch entries the body carries — the comment lines are not entries. */
    entries: wrapped.length,
    /**
     * The body lines, WITHOUT the file's indentation: indenting is applied in exactly one place
     * (`indentBlockLines`), by the splice, the `--check` and `--print-block` alike. Applying it
     * here as well produced a block whose markers sat at two spaces and everything else at four,
     * which `--check` then (correctly) reported as drift — measured 2026-09-28.
     */
    lines,
    /** The same body, wrapped as its own flow sequence, for `selfCheck` and for parsing. */
    document: `[${['', ...lines].join('\n')}\n]\n`,
  };
}

/** Indent every non-empty line of a block by the file's own two-space style. */
const indentBlockLines = (lines) => lines.map((line) => (line.length > 0 ? BLOCK_INDENT + line : line));

/** Normalise a path for the drift report, relative to the repo when it is inside it. */
function relToRepo(file) {
  return file.startsWith(`${REPO_ROOT}\\`) || file.startsWith(`${REPO_ROOT}/`)
    ? file.slice(REPO_ROOT.length + 1)
    : file;
}

const indexOfMarkers = (lines) => {
  const begins = [];
  const ends = [];
  lines.forEach((line, i) => {
    const trimmed = line.trim();
    if (MARKER_BEGIN_RE.test(trimmed)) begins.push(i);
    if (MARKER_END_RE.test(trimmed)) ends.push(i);
  });
  return { begins, ends };
};

/** The file's own line ending. A file with no newline at all is treated as LF. */
const eolOf = (text) => (text.includes('\r\n') ? '\r\n' : '\n');

/**
 * Parse the patch entries a block body carries, by wrapping the body in `[ … ]`. The body is a flow
 * sequence's interior — comment lines and one entry per preset — so this is exactly how the engine's
 * own parser will read it once the block sits inside the file's outer sequence. Throws on anything
 * that does not parse; callers decide whether that is a refusal or a failure.
 */
function parseBlockEntries(bodyLines) {
  const parsed = YAML.parse(`[\n${bodyLines.join('\n')}\n]\n`, PARSE_OPTIONS);
  if (!Array.isArray(parsed)) throw new Error('the block body did not parse to a sequence');
  return parsed;
}

/**
 * Splice the managed block into `text`, returning the new text and the evidence for it.
 *
 * The contract, in the order the checks are made: refuse unless the file parses as a non-empty
 * top-level flow sequence; refuse on unbalanced or duplicated markers; refuse on a committed block
 * that does not itself parse; then build the candidate text, and refuse to return it unless the
 * text outside the block region is byte-identical to what it was, the result still parses, it has
 * exactly the expected number of patch entries, and all three generated entries are in it.
 *
 * `mode` is `append` (no markers: the block goes before the final `]`), `replace`, or `noop`
 * (the block is already byte-identical, so nothing is written and the file is untouched).
 */
export function spliceManagedBlock(text, bodyLines, entryCount = null) {
  const problems = [];
  const eol = eolOf(text);
  const lines = text.split(eol);
  // How many patch entries the body carries. The body is comment lines + one entry each, so the
  // caller passes the count; deriving it from the body length would count comment and wrapped lines.
  const generated = entryCount ?? parseBlockEntries(bodyLines).length;
  const blockLines = indentBlockLines([MARKER_BEGIN, ...bodyLines, MARKER_END]);
  const { begins, ends } = indexOfMarkers(lines);
  const sha = (s) => createHash('sha256').update(s, 'utf8').digest('hex');

  let current;
  try {
    current = YAML.parse(text, PARSE_OPTIONS);
  } catch (e) {
    return { problems: [`${'the target file does not parse'}: ${e.message}`] };
  }
  if (!Array.isArray(current) || current.length === 0) {
    return {
      problems: [`the target file is not a non-empty top-level YAML sequence `
        + `(got ${current === null ? 'null' : Array.isArray(current) ? 'empty sequence' : typeof current})`
        + '; a profile patch file is a flow sequence of patch entries'],
    };
  }

  let mode;
  let oldBegin = null;
  let oldEnd = null;
  if (begins.length === 0 && ends.length === 0) {
    mode = 'append';
    const closing = lines.reduce((acc, line, i) => (line.trim() === ']' ? i : acc), -1);
    if (closing < 0) {
      return {
        problems: ['no final `]` line found, so the block has nowhere to be appended: a profile '
          + 'patch file is one flow sequence and must end with `]`'],
      };
    }
    oldEnd = closing - 1; // nothing is owned yet; the region before the block is the whole file
  } else if (begins.length === 1 && ends.length === 1 && begins[0] < ends[0]) {
    mode = 'replace';
    [oldBegin, oldEnd] = [begins[0], ends[0]];
  } else {
    const detail = `BEGIN marker lines: ${begins.length} (at ${begins.join(', ') || '-'}), `
      + `END marker lines: ${ends.length} (at ${ends.join(', ') || '-'})`;
    return {
      problems: [`the \`${BLOCK_ID}\` markers are unbalanced or duplicated — ${detail}. Refusing to `
        + 'guess which region is ours; fix the markers by hand (or remove both) and run again.'],
    };
  }

  // Entry count committed in the block, so the result's own entry count can be predicted.
  const oldBody = oldBegin === null ? [] : lines.slice(oldBegin + 1, oldEnd);
  let oldCount = 0;
  if (oldBegin !== null) {
    try {
      oldCount = parseBlockEntries(oldBody).length;
    } catch {
      oldCount = null;
    }
  }
  if (oldBegin !== null && oldCount === null) {
    return {
      problems: ['the lines between the markers do not parse as a flow sequence of patch entries. '
        + 'Repair the block by hand, or delete both marker lines and run --install to write it fresh.'],
    };
  }

  const nextLines = mode === 'append'
    ? [...lines.slice(0, oldEnd + 1), '', ...blockLines, ...lines.slice(oldEnd + 1)]
    : [...lines.slice(0, oldBegin), ...blockLines, ...lines.slice(oldEnd + 1)];
  const next = nextLines.join(eol);

  if (next === text) {
    return {
      mode: 'noop',
      text,
      eol,
      currentEntries: current.length,
      blockEntries: bodyLines.length,
      outsideSha: sha(next),
    };
  }

  // The outside-the-block text must be untouched. It is proved, not asserted: remove the block
  // region from both texts and compare the sha256 of what is left. The region is the marker lines
  // plus the body, and in `append` mode also the blank separator line the splice inserts, so that
  // every byte the splice adds is inside the region and the rest of the file provably is not.
  const outsideOf = (all, begin, end) => (begin === null ? all.join(eol) : [...all.slice(0, begin), ...all.slice(end + 1)].join(eol));
  const regionStart = mode === 'append' ? oldEnd + 1 : oldBegin;
  const regionLength = blockLines.length + (mode === 'append' ? 1 : 0);
  const nextEnd = regionStart + regionLength - 1;
  const before = outsideOf(lines, oldBegin, oldEnd);
  const after = outsideOf(nextLines, regionStart, nextEnd);
  if (sha(before) !== sha(after)) {
    return { problems: ['internal check failed: the text outside the block would change; nothing was written'] };
  }

  let composed;
  try {
    composed = YAML.parse(next, PARSE_OPTIONS);
  } catch (e) {
    return { problems: [`the result would not parse, so it was not written: ${e.message}`] };
  }
  if (!Array.isArray(composed)) {
    return { problems: ['internal check failed: the result did not parse to a sequence; nothing was written'] };
  }
  const expectedCount = current.length - oldCount + generated;
  if (composed.length !== expectedCount) {
    return {
      problems: [`internal check failed: the result holds ${composed.length} patch entries, expected `
        + `${expectedCount} (${current.length} present${oldCount ? ` less ${oldCount} replaced` : ''} `
        + `plus ${generated} generated); nothing was written`],
    };
  }
  return {
    mode,
    text: next,
    eol,
    currentEntries: current.length,
    blockEntries: generated,
    expectedEntries: expectedCount,
    outsideShaBefore: sha(before),
    outsideShaAfter: sha(after),
    outsideSha: sha(after),
  };
}

/**
 * `--check` for the managed block: does the committed block match what would be generated?
 * Returns an exit code. A missing block is drift (the wiring is not there), not a pass.
 */
function checkManagedBlock(targetFile, bodyLines, log, logErr) {
  if (!existsSync(targetFile)) {
    logErr(`--check: DRIFT — ${targetFile} does not exist, so the managed block cannot be there`);
    return 1;
  }
  const text = readFileSync(targetFile, 'utf8');
  const eol = eolOf(text);
  const lines = text.split(eol);
  const { begins, ends } = indexOfMarkers(lines);
  if (begins.length === 0 && ends.length === 0) {
    logErr(`--check: DRIFT — the \`${BLOCK_ID}\` managed block is absent from ${relToRepo(targetFile)}; `
      + 'the generated rows are not in any layer the engine loads. Run with --install.');
    return 1;
  }
  if (begins.length !== 1 || ends.length !== 1 || begins[0] >= ends[0]) {
    logErr(`--check: DRIFT — the \`${BLOCK_ID}\` markers in ${relToRepo(targetFile)} are unbalanced or `
      + `duplicated (BEGIN ${begins.length}, END ${ends.length})`);
    return 1;
  }
  const committed = lines.slice(begins[0] + 1, ends[0]).join(eol);
  const generated = indentBlockLines(bodyLines).join(eol);
  if (committed === generated) {
    log(`--check: managed block UP TO DATE — ${relToRepo(targetFile)} `
      + `(lines ${begins[0] + 2}-${ends[0]}, ${bodyLines.length} lines inside the markers)`);
    return 0;
  }
  const diff = firstDifference(committed, generated);
  logErr(`--check: DRIFT — the \`${BLOCK_ID}\` block in ${relToRepo(targetFile)} does not match what `
    + 'the converter would write');
  if (diff) {
    logErr(`  first difference at block line ${diff.line}`);
    logErr(`  committed: ${diff.committed.slice(0, 400)}`);
    logErr(`  generated: ${diff.generated.slice(0, 400)}`);
  }
  logErr(`  committed ${Buffer.byteLength(committed, 'utf8')} bytes vs generated `
    + `${Buffer.byteLength(generated, 'utf8')} bytes (block body only)`);
  return 1;
}

/**
 * Prove the emitted text is what the input was, using the UNMODIFIED parser.
 *
 * This is the guard that makes the broken-`stringify` hazard harmless: it compares the `!!js` source
 * texts in order, requires each one to appear byte-for-byte in the emitted bytes, and rejects the
 * `!!js undefined` shape outright.
 *
 * `style` must be the style the text was emitted in: an expression that is plain-safe in a block is
 * NOT plain-safe in a flow collection, and there it is legitimately single-quoted (which escapes the
 * `'` inside it, so the raw text is absent by construction rather than by loss). The `!!js` value
 * comparison above is style-independent and is the check that cannot be relaxed.
 */
function selfCheck(text, exprs, inputValue, style = 'block') {
  const problems = [];
  if (/!!js +undefined\b/.test(text)) {
    problems.push('the emitted file contains `!!js undefined` — an expression was lost in emission');
  }
  let reparsed;
  try {
    reparsed = YAML.parse(text, PARSE_OPTIONS);
  } catch (e) {
    problems.push(`the emitted file does not re-parse: ${e.message}`);
    return problems;
  }
  const emitted = collectJsTexts(reparsed);
  if (emitted.length !== exprs.length) {
    problems.push(`${exprs.length} \`!!js\` expressions were emitted but ${emitted.length} were `
      + 'read back');
  }
  const count = Math.min(emitted.length, exprs.length);
  for (let i = 0; i < count; i += 1) {
    if (emitted[i] !== exprs[i]) {
      problems.push(`expression ${i + 1} changed: ${JSON.stringify(exprs[i])} -> ${JSON.stringify(emitted[i])}`);
    }
  }
  const notByteIdentical = exprs.filter((expr) => plainSafe(expr, style) && !text.includes(expr));
  if (notByteIdentical.length > 0) {
    problems.push(`${notByteIdentical.length} plain-safe expression(s) are not byte-identical in the `
      + `emitted text: ${notByteIdentical.slice(0, 3).map(JSON.stringify).join(', ')}`);
  }
  // The document structure must survive too, wrappers aside.
  const shape = (v) => {
    if (isJs(v)) return '<js>';
    if (Array.isArray(v)) return v.map(shape);
    if (v && typeof v === 'object') {
      return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shape(x)]));
    }
    return v;
  };
  if (JSON.stringify(shape(reparsed)) !== JSON.stringify(shape(inputValue))) {
    problems.push('the emitted document structure differs from the input (ids, order or key sets)');
  }
  return problems;
}

// ── CLI ──────────────────────────────────────────────────────────────────────────────────────
export function parseArgs(argv) {
  const args = {
    presetsDir: DEFAULT_PRESETS_DIR,
    out: DEFAULT_OUT,
    check: false,
    names: null,
    help: false,
    install: false,
    installTarget: DEFAULT_INSTALL_TARGET,
    printBlock: false,
  };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--presets-dir') args.presetsDir = need('--presets-dir');
    else if (a === '--out') args.out = need('--out');
    else if (a === '--check') args.check = true;
    else if (a === '--install') args.install = true;
    else if (a === '--install-target') args.installTarget = need('--install-target');
    else if (a === '--print-block') args.printBlock = true;
    else if (a === '--names') {
      args.names = need('--names').split(',').map((s) => s.trim()).filter((s) => s.length > 0);
      if (args.names.length === 0) throw new Error('--names was given with no names in it');
    } else if (a === '-h' || a === '--help') args.help = true;
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

/** First line on which two texts differ, 1-based, for a drift report that is actionable. */
function firstDifference(a, b) {
  const la = a.split('\n');
  const lb = b.split('\n');
  for (let i = 0; i < Math.max(la.length, lb.length); i += 1) {
    if (la[i] !== lb[i]) {
      return {
        line: i + 1,
        committed: la[i] === undefined ? '<end of file>' : la[i],
        generated: lb[i] === undefined ? '<end of file>' : lb[i],
      };
    }
  }
  return null;
}

export async function main(argv = process.argv.slice(2), log = console.log, logErr = console.error) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (e) {
    logErr(`make-preset-rows.mjs: ${e.message}\n${USAGE}`);
    return 2;
  }
  if (args.help) {
    logErr(USAGE);
    return 0;
  }

  const presetsDir = isAbsolute(args.presetsDir) ? args.presetsDir : resolve(process.cwd(), args.presetsDir);
  const outFile = isAbsolute(args.out) ? args.out : resolve(process.cwd(), args.out);

  let allNames;
  try {
    allNames = discoverPresetNames(presetsDir);
  } catch (e) {
    logErr(`make-preset-rows.mjs: ${e.message}`);
    return 1;
  }

  // Order comes from the FULL set, so `--names` filters without renumbering.
  const orderByName = new Map(allNames.map((name, index) => [name, ORDER_BASE + index]));
  const selected = args.names ?? allNames;
  const unknown = selected.filter((name) => !orderByName.has(name));
  if (unknown.length > 0) {
    logErr(`make-preset-rows.mjs: --names named preset(s) that do not exist: ${unknown.join(', ')}. `
      + `Found: ${allNames.join(', ')}`);
    return 1;
  }

  let items;
  try {
    items = selected
      .map((name) => ({ name, order: orderByName.get(name), ...readPresetRows(presetsDir, name) }))
      .sort((a, b) => a.order - b.order);
    if (items.length === 0) throw new Error('no preset selected, so there is nothing to emit');
  } catch (e) {
    logErr(`make-preset-rows.mjs: ${e.message}`);
    return 1;
  }

  // Build the document, then check it against the input before it is allowed anywhere near disk.
  const exprs = [];
  let text;
  try {
    text = buildDocument(items, exprs);
  } catch (e) {
    logErr(`make-preset-rows.mjs: could not build the document: ${e.message}`);
    return 1;
  }
  const expected = patchEntries(items);
  const problems = selfCheck(text, exprs, expected);
  if (problems.length > 0) {
    logErr('make-preset-rows.mjs: REFUSING TO WRITE — the emitted document failed its own check:');
    for (const problem of problems) logErr(`  - ${problem}`);
    return 1;
  }

  // The managed block is built from the same entries and checked the same way before it is allowed
  // anywhere near a file the engine boots from.
  let block;
  try {
    block = buildBlockBodyLines(items);
  } catch (e) {
    logErr(`make-preset-rows.mjs: could not build the managed block: ${e.message}`);
    return 1;
  }
  const blockProblems = selfCheck(block.document, block.exprs, expected, 'flow');
  if (blockProblems.length > 0) {
    logErr('make-preset-rows.mjs: REFUSING TO WRITE — the managed block failed its own check:');
    for (const problem of blockProblems) logErr(`  - ${problem}`);
    return 1;
  }
  // The block and the standalone artefact must be the SAME patch entries. That is what "verbatim"
  // reduces to across two YAML styles, and it is checked by parsing both with the same parser.
  if (!isDeepStrictEqual(YAML.parse(block.document, PARSE_OPTIONS), YAML.parse(text, PARSE_OPTIONS))) {
    logErr('make-preset-rows.mjs: REFUSING TO WRITE — the managed block and the standalone artefact '
      + 'are not the same patch entries');
    return 1;
  }

  // `--print-block` writes the block on stdout, so the summary goes to stderr in that mode: the
  // printed block is then pipeable and diffable on its own.
  const say = args.printBlock ? logErr : log;
  say(`make-preset-rows.mjs — ${items.length} preset(s) from ${presetsDir}`);
  say(`  order rule: ${ORDER_BASE} + index in ascending name order over all ${allNames.length} discovered preset(s)`);
  for (const item of items) {
    say(`  preset-${item.name}  id=${item.name}  order=${item.order}  plugins=${item.rows.length}`
      + `  !!js=${collectJsTexts(item.rows).length}  <- presets/${item.name}/${PRESET_FILE_NAME}`);
  }
  say(`  !!js expressions carried: ${exprs.length}; self-check: ${problems.length === 0 ? 'PASS' : 'FAIL'}`);

  const installTarget = isAbsolute(args.installTarget)
    ? args.installTarget
    : resolve(process.cwd(), args.installTarget);
  say(`  managed block: ${items.length} entries, ${block.lines.length} lines, ${block.exprs.length} `
    + `!!js; self-check: PASS; deep-equal to the standalone artefact: yes`);

  if (args.printBlock) {
    const eol = existsSync(installTarget) ? eolOf(readFileSync(installTarget, 'utf8')) : '\n';
    process.stdout.write(`${indentBlockLines(block.lines).join(eol)}\n`);
    return 0;
  }

  if (args.install && args.names) {
    logErr('make-preset-rows.mjs: --install refuses --names — the installed block is always the full '
      + 'discovered set, because a filtered block would silently drop presets from the layer the '
      + 'engine boots. Emit the subset with --out, or install the full set.');
    return 2;
  }

  if (args.check) {
    let code = 0;
    if (!existsSync(outFile)) {
      logErr(`--check: DRIFT — ${relToRepo(outFile)} does not exist; run the converter without --check `
        + 'to create it');
      return 1;
    }
    const committed = readFileSync(outFile, 'utf8');
    if (committed === text) {
      log(`--check: UP TO DATE — ${relToRepo(outFile)}`);
    } else {
      const diff = firstDifference(committed, text);
      logErr(`--check: DRIFT — ${relToRepo(outFile)} does not match what the converter would write`);
      if (diff) {
        logErr(`  first difference at line ${diff.line}`);
        logErr(`  committed: ${diff.committed.slice(0, 400)}`);
        logErr(`  generated: ${diff.generated.slice(0, 400)}`);
      }
      logErr(`  committed ${Buffer.byteLength(committed, 'utf8')} bytes vs generated `
        + `${Buffer.byteLength(text, 'utf8')} bytes`);
      code = 1;
    }
    if (args.names) {
      log(`--check: managed block NOT CHECKED — --names narrows the emitted set (`
        + `${selected.join(', ')}), and the installed block is always the full discovered set`);
    } else if (checkManagedBlock(installTarget, block.lines, log, logErr) !== 0) {
      code = 1;
    }
    return code;
  }

  try {
    mkdirSync(dirname(outFile), { recursive: true });
    writeFileSync(outFile, text, 'utf8');
  } catch (e) {
    logErr(`make-preset-rows.mjs: cannot write ${outFile}: ${e.message}`);
    return 1;
  }
  if (statSync(outFile).size !== Buffer.byteLength(text, 'utf8')) {
    logErr(`make-preset-rows.mjs: wrote ${outFile} but its size does not match what was generated`);
    return 1;
  }
  log(`  wrote ${outFile} (${Buffer.byteLength(text, 'utf8')} bytes, ${
    text.split('\n').length - 1} lines)`);

  if (!args.install) {
    log(`  (the managed block in ${relToRepo(installTarget)} was NOT touched: --install does that)`);
    return 0;
  }

  if (!existsSync(installTarget)) {
    logErr(`make-preset-rows.mjs: --install-target ${installTarget} does not exist; nothing written there`);
    return 1;
  }
  const target = readFileSync(installTarget, 'utf8');
  const spliced = spliceManagedBlock(target, block.lines, block.entries);
  if (spliced.problems) {
    logErr(`make-preset-rows.mjs: REFUSING TO WRITE — ${relToRepo(installTarget)} was NOT changed:`);
    for (const problem of spliced.problems) logErr(`  - ${problem}`);
    return 1;
  }
  if (spliced.mode === 'noop') {
    log(`  managed block in ${relToRepo(installTarget)} is already up to date (${block.lines.length} `
      + 'lines): nothing written, file untouched');
    return 0;
  }
  try {
    writeFileSync(installTarget, spliced.text, 'utf8');
  } catch (e) {
    logErr(`make-preset-rows.mjs: cannot write ${installTarget}: ${e.message}`);
    return 1;
  }
  if (statSync(installTarget).size !== Buffer.byteLength(spliced.text, 'utf8')) {
    logErr(`make-preset-rows.mjs: wrote ${installTarget} but its size does not match what was generated`);
    return 1;
  }
  log(`  ${spliced.mode === 'append' ? 'created' : 'updated'} the managed block in `
    + `${relToRepo(installTarget)} (patch entries ${spliced.currentEntries} -> `
    + `${spliced.expectedEntries}, ${block.lines.length} lines between the markers)`);
  log(`  outside the block: byte-identical, sha256 ${spliced.outsideSha.slice(0, 16)}… `
    + '(proved by removing the block region from both texts and comparing)');
  return 0;
}

const invokedDirectly = Boolean(process.argv[1])
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => {
      process.stderr.write(`make-preset-rows.mjs: unexpected failure: ${e?.stack ?? e}\n`);
      process.exit(1);
    });
}
