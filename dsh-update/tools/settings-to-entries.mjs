/**
 * settings-to-entries.mjs — turn a `settings.yaml` document into PROFILE-PATCH ENTRIES.
 *
 * WHY THIS IS NEEDED AT ALL (measured 2026-10-05, and it is the whole of this upgrade's settings story).
 * On the 0.1.5 line `@deepseek-ai/dsh-settings-file` read `<harness home>/settings.yaml` — our file. That
 * package is GONE on 0.1.7+. Its replacement keeps its document at `configEditor.documentPath`, and that
 * getter is `profileContext.patchPath` (`dsh-config-editor/lib/index.js:24-26`) — i.e. **the profile's own
 * `cordis.patch.yml`**. The only other path, `importLegacyDocument()`
 * (`dsh-settings/lib/index.js:346-363`), is a ONE-SHOT migration: it reads
 * `join(profile.home, 'settings.yaml')`, RENAMES it to `.imported`, then calls `update(section, values)`
 * per section — the same write this tool performs, but implicitly, asynchronously, after the loader
 * settles, with failures logged and left behind in a renamed file.
 *
 * So a `settings.yaml` is not read on 0.1.7+. Its sections become `config:` blocks on the rows whose
 * namespaces they address, in the profile patch. Doing that here rather than letting the one-shot import
 * do it means the change is reviewable, idempotent, `--check`-able, and survives a re-stage.
 *
 * THREE MEASURED CONSTRAINTS, EACH FROM FAILING AT IT FIRST.
 *
 * 1. **A PROFILE PATCH IS NOT ALWAYS THE SAME YAML SHAPE.** Measured 2026-10-05:
 *      profiles/web/cordis.patch.yml  is a FLOW collection — `[` first, `]` last, entries are flow
 *                                     mappings with TRAILING COMMAS.
 *      profiles/mesh/cordis.patch.yml is a BLOCK sequence — no brackets at all, entries are `- id: x`
 *                                     with an indented `config:`.
 *    Emitting block entries into the flow file is invalid, and the engine rejects the WHOLE overlay:
 *        dsh: failed to parse overlay .../profiles/web/cordis.patch.yml
 *             YAMLException: missed comma between flow collection entries (1622:3)
 *    So the style is DETECTED from the target file (or given with `--style`), and each style is emitted
 *    in its own form. Nested content (`llm-deepseek.retryPolicy.backoff`,
 *    `llm-pi-ai.providers.deepinfra.models[]`) cannot be block style inside a flow mapping at all, which
 *    is why the `config` body is always produced by the real `yaml` stringifier in flow mode.
 *
 * 2. **`!!js` cannot survive `YAML.stringify`.** Verified 2026-09-28 against yaml 2.9.0 elsewhere in this
 *    repo: the tag's `stringify` is called once, its return value is discarded, and the output is
 *    `!!js undefined`, which re-parses as the STRING "undefined". A settings document containing `!!js`
 *    is REFUSED here rather than silently corrupted. (The mesh PATCH file legitimately contains `!!js`;
 *    this check is about the settings document, which is the thing being converted.)
 *
 * 3. **A section whose row cannot be resolved is REFUSED by name**, never emitted against a
 *    plausible-looking id — a patch entry naming a row that does not exist fails at mount.
 *
 * It does not invent values and does not validate them against the candidate schema: `settings-effective`
 * does that, and it is the gate that says whether the entries landed.
 *
 * Usage:
 *   node dsh-update/tools/settings-to-entries.mjs --settings <settings.yaml> [--print | --out <file>]
 *        [--install <profilePatch>] [--style flow|block] [--rows <json>] [--check] [--json]
 */

import fs from 'node:fs';
import path from 'node:path';
import { PARSE_OPTIONS, loadYaml } from '../lib/yaml.mjs';

const ARGS = process.argv.slice(2);
const JSON_MODE = ARGS.includes('--json');
const val = (n) => { const i = ARGS.indexOf(n); return i >= 0 ? ARGS[i + 1] : null; };

/**
 * Sections whose owning row id is NOT the section name.
 * `ui-onboarding`/`ui-developer-tools` are the two the engine's own migration remaps
 * (`dsh-settings/lib/index.js:302-308`, `LEGACY_SECTION_ENTRIES`) — stated by upstream, not guessed.
 * `agent-presets` is not a row at all on 0.2.0-rc.2: the namespace moved onto the
 * `agent-preset-registry` row, whose `config.default` carries the same value.
 */
const ROW_FOR_SECTION = new Map([
  ['ui-onboarding', 'ui-settings-general'],
  ['ui-developer-tools', 'ui-settings'],
  ['agent-presets', 'agent-preset-registry'],
]);

const BLOCK_ID = 'settings-from-yaml';

function refuse(lines) {
  for (const l of lines) process.stdout.write(`${l}\n`);
  process.exit(7);
}

/** Flow: the file closes with a bare `]`. Block: it does not. */
function detectStyle(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '');
  if (lines.length === 0) return { style: null, why: 'the file is empty' };
  const last = lines[lines.length - 1].trim();
  if (last === ']') return { style: 'flow', why: 'the last non-empty line is `]`, so it is a flow collection' };
  const first = lines[0].trim();
  if (first.startsWith('[')) return { style: null, why: 'the first line opens `[` but no line closes it with `]`' };
  if (lines.some((l) => l.startsWith('- ') || l.startsWith('- id:'))) {
    return { style: 'block', why: 'no closing `]`, and top-level `- ` entries, so it is a block sequence' };
  }
  return { style: null, why: 'neither a flow collection nor a block sequence could be identified' };
}

const settingsPath = val('--settings');
if (!settingsPath) {
  refuse(['usage: node dsh-update/tools/settings-to-entries.mjs --settings <settings.yaml> '
    + '[--print | --out <file> | --install <profilePatch>] [--style flow|block] [--rows <json>] '
    + '[--check] [--json]']);
}

let text;
try { text = fs.readFileSync(settingsPath, 'utf8'); } catch (e) {
  refuse([`settings-to-entries: cannot read ${settingsPath}: ${e.message}`]);
}
if (/!!js/.test(text)) {
  refuse(['settings-to-entries: REFUSED — this document contains `!!js`, and `YAML.stringify` cannot write '
    + 'that tag (it emits `!!js undefined`, which re-parses as the STRING "undefined"). Nothing was '
    + 'written. See the note at the top of this file.']);
}
if (val('--rows')) for (const [k, v] of Object.entries(JSON.parse(fs.readFileSync(val('--rows'), 'utf8')))) ROW_FOR_SECTION.set(k, v);

let YAML;
try { YAML = loadYaml(); } catch (e) {
  refuse([`settings-to-entries: REFUSED — ${e.message}`]);
}

// ── the target and its collection style must be settled BEFORE anything is emitted ───────────────
const installPath = val('--install');
const outPath = val('--out');
const target = installPath ?? outPath;
let existing = null;
let style = val('--style') ?? 'flow';
let styleWhy = `--style ${style} (or the default)`;
if (installPath) {
  const abs = path.resolve(installPath);
  try { existing = fs.readFileSync(abs, 'utf8'); } catch (e) {
    refuse([`settings-to-entries: REFUSED — cannot read ${abs}: ${e.message}`]);
  }
  const det = detectStyle(existing);
  if (!det.style) {
    refuse([`settings-to-entries: REFUSED — cannot tell which YAML shape ${abs} is: ${det.why}. `
      + 'Nothing was written; pass --style flow|block if you have read the file and know.']);
  }
  style = det.style;
  styleWhy = det.why;
}

// ── parse the document properly, with the pipeline's own options ───────────────────────────────────
let doc;
try {
  doc = YAML.parse(text, PARSE_OPTIONS);
} catch (e) {
  refuse([`settings-to-entries: the settings document does not parse: ${e.message}`]);
}
if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
  refuse(['settings-to-entries: the document did not parse to a mapping of sections; an empty or '
    + 'malformed document is a refusal, not an empty set of entries.']);
}

const sections = Object.keys(doc);
const problems = [];
const entries = [];
for (const name of sections) {
  const row = ROW_FOR_SECTION.get(name) ?? name;
  const config = doc[name];
  if (!config || typeof config !== 'object' || Array.isArray(config) || Object.keys(config).length === 0) {
    problems.push(`section "${name}" is not a mapping with any keys, so there is nothing to emit`);
    continue;
  }
  entries.push({ section: name, row, renamed: row !== name, config });
}

// ── emit in the target's own style, with the config body always stringified FLOW ──────────────────
let body = '';
if (entries.length > 0) {
  const emitted = entries.map((e) => {
    const configFlow = YAML.stringify(e.config, { flow: true, lineWidth: 0, indent: 2 }).trimEnd();
    if (configFlow.split('\n').length !== 1) {
      problems.push(`the config for "${e.section}" did not stringify to a single flow line; refusing `
        + 'rather than emitting a multi-line flow mapping whose indentation has not been checked');
    }
    // Flow style: one flow mapping per line, comma-terminated, inside the enclosing `[ ... ]`.
    // Block style: `- id: x` then an indented `config: { ... }` — a flow mapping is valid as a block
    // value, and it keeps every nested map and sequence on one line where the indentation cannot drift.
    return style === 'flow'
      ? `  { id: ${quoteIfNeeded(YAML, e.row)}, config: ${configFlow} },`
      : `- id: ${quoteIfNeeded(YAML, e.row)}\n  config: ${configFlow}`;
  });
  if (problems.length === 0) {
    const ind = style === 'flow' ? '  ' : '';
    body = [
      `${ind}# >>> ${BLOCK_ID}: BEGIN managed block — generated by dsh-update/tools/settings-to-entries.mjs`,
      `${ind}# One entry per section of the retired settings.yaml, on the row whose namespace it addresses.`,
      `${ind}# On 0.1.7+ THIS document is the settings store (configEditor.documentPath), so a value that is`,
      `${ind}# not here is not in force. Edit the settings.yaml source and regenerate; do not hand-edit.`,
      ...emitted,
      `${ind}# <<< ${BLOCK_ID}: END managed block <<<`,
    ].join('\n');
  }
}

/** Row ids are plain identifiers; quote only if the stringifier would need to. */
function quoteIfNeeded(Y, s) {
  const plain = Y.stringify(s, { lineWidth: 0 }).trimEnd();
  return plain === s ? s : JSON.stringify(s);
}

const result = {
  schemaVersion: 1,
  tool: 'settings-to-entries',
  settings: path.resolve(settingsPath),
  style,
  styleWhy,
  sections: sections.length,
  entries: entries.map((e) => ({ section: e.section, row: e.row, renamed: e.renamed })),
  problems,
  blockLines: body ? body.split('\n').length : 0,
  block: body,
};

if (problems.length > 0) {
  if (JSON_MODE) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  else refuse(['settings-to-entries: REFUSED — nothing was written.', ...problems.map((p) => `  - ${p}`)]);
}

if (target) {
  const abs = path.resolve(target);
  let textOut;
  if (installPath) {
    const spliced = spliceBlock(existing, body, BLOCK_ID, style);
    if (spliced.problems) {
      if (JSON_MODE) process.stdout.write(`${JSON.stringify({ ...result, problems: spliced.problems }, null, 2)}\n`);
      else refuse(['settings-to-entries: REFUSED — nothing was written.', ...spliced.problems.map((p) => `  - ${p}`)]);
    }
    textOut = spliced.text;
  } else {
    textOut = `${body}\n`;
  }
  if (ARGS.includes('--check')) {
    const same = fs.readFileSync(abs, 'utf8') === textOut;
    process.stdout.write(`settings-to-entries --check: ${same ? 'UP TO DATE' : 'DRIFT'} — ${abs}\n`);
    process.exit(same ? 0 : 1);
  }
  fs.writeFileSync(abs, textOut);
  result.wrote = abs;
}

if (JSON_MODE) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
else if (ARGS.includes('--print')) process.stdout.write(`${body}\n`);
else {
  process.stdout.write(`settings-to-entries: ${entries.length} entr(ies) from ${sections.length} section(s)`
    + ` in ${style} style${target ? ` -> ${path.resolve(target)}` : ''}\n`
    + `  style: ${styleWhy}\n`
    + entries.map((e) => `  ${e.section.padEnd(22)} -> row ${e.row}${e.renamed ? '  (renamed)' : ''}\n`).join(''));
}
process.exit(0);

/** Replace an existing managed block, or append one in the target's own collection style. */
function spliceBlock(text, bodyText, id, style) {
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const lines = text.split(/\r?\n/);
  const begin = lines.findIndex((l) => l.includes(`${id}: BEGIN`));
  const end = lines.findIndex((l) => l.includes(`${id}: END`));
  const bodyLines = bodyText.split('\n');
  if (begin !== -1 && end !== -1 && end > begin) {
    return { text: [...lines.slice(0, begin), ...bodyLines, ...lines.slice(end + 1)].join(eol) };
  }
  if (begin !== -1 || end !== -1) {
    return { problems: [`the ${id} markers are unbalanced (BEGIN ${begin === -1 ? 0 : 1}, END ${end === -1 ? 0 : 1})`] };
  }
  if (style === 'flow') {
    let close = -1;
    for (let i = lines.length - 1; i >= 0; i -= 1) { if (lines[i].trim() === ']') { close = i; break; } }
    if (close === -1) return { problems: ['the profile patch has no closing `]` line, so there is no flow sequence to append to'] };
    return { text: [...lines.slice(0, close), ...bodyLines, ...lines.slice(close)].join(eol) };
  }
  // Block sequence: append at the end. Keep one blank line of separation, and do not drop a trailing
  // newline the file already had.
  const trimmed = [...lines];
  while (trimmed.length > 0 && trimmed[trimmed.length - 1].trim() === '') trimmed.pop();
  return { text: [...trimmed, '', ...bodyLines, ''].join(eol) };
}
