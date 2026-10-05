/**
 * settings-to-entries.mjs — turn a `settings.yaml` document into PROFILE-PATCH ENTRIES.
 *
 * WHY THIS IS NEEDED AT ALL (measured 2026-10-05, and it is the whole of this upgrade's settings story).
 * On the 0.1.5 line, `@deepseek-ai/dsh-settings-file` read `<harness home>/settings.yaml` — our file.
 * That package is GONE on 0.1.7+. Its replacement, `@deepseek-ai/dsh-settings`, keeps its document at
 * `configEditor.documentPath`, and that getter is `profileContext.patchPath`
 * (`dsh-config-editor/lib/index.js:24-26`) — i.e. **the profile's own `cordis.patch.yml`**. The only
 * other path, `importLegacyDocument()` (`dsh-settings/lib/index.js:346-363`), is a ONE-SHOT migration:
 * it reads `join(profile.home, 'settings.yaml')`, RENAMES it to `.imported`, and calls `update(section,
 * values)` per section — which is the same write this tool performs, just done implicitly, asynchronously,
 * after the loader settles, with failures logged and left behind in a renamed file.
 *
 * So a `settings.yaml` is not read on 0.1.7+. Its sections have to become `config:` blocks on the rows
 * whose namespaces they address, in the profile patch. Doing that HERE rather than letting the one-shot
 * import do it means the change is reviewable, idempotent, `--check`-able, and it survives a re-stage.
 *
 * WHAT IT DOES NOT DO. It does not invent values and it does not validate them against the candidate
 * schema — `settings-effective` does that, and it is the gate that will tell you whether the entries
 * landed. It also does not guess a row for a section: a section whose row cannot be resolved is REFUSED
 * by name rather than emitted against a plausible-looking id, because a patch entry naming a row that
 * does not exist fails at mount.
 *
 * READ-ONLY unless `--install` or `--out` is given. It starts nothing.
 *
 * ⚠ NOT YET USABLE — THE EMITTER PRODUCES THE WRONG COLLECTION STYLE. Measured 2026-10-05.
 * --------------------------------------------------------------------------------------------
 * A profile patch is a **flow collection**: it opens with `[` on line 1 and closes with `]`, and its
 * entries are flow mappings in the shape
 *
 *     {
 *       id: 'agent-preset-registry',
 *       config: {
 *         default: 'zabz',
 *       },
 *     },
 *
 * with TRAILING COMMAS. This tool currently emits BLOCK-style entries (`- id: 'x'` then an indented
 * `config:`), which is invalid inside a flow sequence, and the engine rejects the whole overlay:
 *
 *     dsh: failed to parse overlay .../profiles/web/cordis.patch.yml:
 *          YAMLException: missed comma between flow collection entries (1622:3)
 *
 * The `--print` output is therefore useful as a STATEMENT OF INTENT — it names, per settings section, the
 * row id the value belongs on, which is the analysis that was missing — but it must not be installed
 * until the emitter is rewritten. The fix is not a string tweak: nested content (llm-deepseek.retryPolicy,
 * llm-pi-ai.providers.deepinfra.models[]) cannot be block style inside a flow mapping at all, so the block
 * body needs a real YAML stringifier emitting flow style with `{flow: true}` on every node — the same
 * problem `scripts/make-preset-rows.mjs` already solved for the preset rows, and its emitter is the thing
 * to reuse rather than re-invent.
 *
 * This note is here rather than in a commit message because the next caller reads THIS file first.
 *
 * Usage:
 *   node dsh-update/tools/settings-to-entries.mjs --settings <settings.yaml> [--print | --out <file>]
 *        [--install <profilePatch>] [--rows <json>] [--check] [--json]
 */

import fs from 'node:fs';
import path from 'node:path';

const ARGS = process.argv.slice(2);
const JSON_MODE = ARGS.includes('--json');
const val = (n) => { const i = ARGS.indexOf(n); return i >= 0 ? ARGS[i + 1] : null; };

/**
 * Sections whose owning row id is NOT the section name.
 *
 * `ui-onboarding` and `ui-developer-tools` are the two the engine's own migration remaps
 * (`dsh-settings/lib/index.js:302-308`, `LEGACY_SECTION_ENTRIES`), so they are not guesses: upstream
 * states them. `agent-presets` is not a row at all on 0.2.0-rc.2 — the namespace moved onto the
 * `agent-preset-registry` row, whose `config.default` is the same value (FINDINGS.md records that the
 * composed tree's registry row reads `default: "standard"` while our document says `zabz`).
 */
const ROW_FOR_SECTION = new Map([
  ['ui-onboarding', 'ui-settings-general'],
  ['ui-developer-tools', 'ui-settings'],
  ['agent-presets', 'agent-preset-registry'],
]);

/** A minimal, dependency-free reader for the flat two-level YAML our settings document is. */
function parseFlatYaml(text) {
  const out = {};
  const lines = text.split(/\r?\n/);
  let current = null;
  let childKey = null;
  for (const raw of lines) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    const indent = raw.match(/^\s*/)[0].length;
    const line = raw.trimEnd();
    if (indent === 0) {
      const m = line.match(/^([^:\s][^:]*):\s*(.*)$/);
      if (!m) continue;
      current = m[1].trim();
      childKey = null;
      out[current] = m[2].trim() === '' ? {} : m[2].trim();
    } else if (current && indent <= 2) {
      const m = line.match(/^\s+([^:\s][^:]*):\s*(.*)$/);
      if (!m) continue;
      childKey = m[1].trim();
      if (typeof out[current] !== 'object' || out[current] === null) out[current] = {};
      out[current][childKey] = m[2].trim() === '' ? {} : m[2].trim();
    }
  }
  return out;
}

const settingsPath = val('--settings');
if (!settingsPath) {
  process.stdout.write('usage: node dsh-update/tools/settings-to-entries.mjs --settings <settings.yaml> '
    + '[--print | --out <file> | --install <profilePatch>] [--rows <json>] [--check] [--json]\n');
  process.exit(2);
}
let text;
try { text = fs.readFileSync(settingsPath, 'utf8'); } catch (e) {
  process.stdout.write(`settings-to-entries: cannot read ${settingsPath}: ${e.message}\n`);
  process.exit(2);
}

// FAIL CLOSED until the emitter emits flow style. `--print` is honest analysis; `--install` would write
// YAML the engine rejects, into the file a switch installs. A tool that can break the profile patch must
// not be usable by accident — the defect above is recorded, and this is the mechanism that enforces it
// rather than a note asking politely.
if (ARGS.includes('--install') || ARGS.includes('--out')) {
  process.stdout.write('settings-to-entries: REFUSED — this emitter produces BLOCK-style entries, and a\n'
    + 'profile patch is a FLOW collection (`[` ... `]` with trailing commas), so the engine rejects the\n'
    + 'result with "missed comma between flow collection entries". Nothing was written.\n'
    + '  Use `--print` (the row mapping is correct and useful), and fix the emitter to emit flow style\n'
    + '  before unblocking this — see the note at the top of this file.\n');
  process.exit(7);
}

const rowsOverride = val('--rows') ? JSON.parse(fs.readFileSync(val('--rows'), 'utf8')) : null;
if (rowsOverride) for (const [k, v] of Object.entries(rowsOverride)) ROW_FOR_SECTION.set(k, v);

/**
 * The document is nested deeper than `parseFlatYaml` models (llm-pi-ai.providers.deepinfra.* and
 * llm-deepseek.retryPolicy.backoff.*). Rather than hand-roll a YAML emitter for nested maps, take the
 * section bodies VERBATIM from the source text and emit them as block-style `config:` bodies. That keeps
 * every value byte-identical to what the operator wrote, which is the property that matters.
 */
const sections = [];
{
  const lines = text.split(/\r?\n/);
  let cur = null;
  let body = [];
  const flush = () => { if (cur) sections.push({ name: cur, body: body.join('\n').replace(/\s+$/, '') }); };
  for (const line of lines) {
    if (!line.trim() || line.trim().startsWith('#')) { if (cur) body.push(line); continue; }
    const indent = line.match(/^\s*/)[0].length;
    if (indent === 0) { flush(); cur = line.match(/^([^:]+):/)?.[1]?.trim() ?? null; body = []; continue; }
    if (cur) body.push(line);
  }
  flush();
}

const problems = [];
const entries = [];
for (const s of sections) {
  if (!s.name) continue;
  const row = ROW_FOR_SECTION.get(s.name) ?? s.name;
  const bodyLines = s.body.split('\n').map((l) => `    ${l.trimEnd()}`);
  if (bodyLines.length === 0) { problems.push(`section "${s.name}" has no body, so there is nothing to emit`); continue; }
  entries.push({
    section: s.name,
    row,
    renamed: row !== s.name,
    text: [`- id: '${row}'`, '  config:', ...bodyLines].join('\n'),
  });
}

const unnameable = entries.filter((e) => !e.row);
for (const e of unnameable) problems.push(`section "${e.section}" maps to no row id`);

const BLOCK_ID = 'settings-from-yaml';
const block = [
  `  # >>> ${BLOCK_ID}: BEGIN managed block — generated by dsh-update/tools/settings-to-entries.mjs`,
  '  # Each entry puts one section of the retired settings.yaml onto the profile row whose namespace it',
  '  # addresses. On 0.1.7+ this document IS the settings store (configEditor.documentPath), so a value',
  '  # that is not here is not in force. Edit the settings.yaml source and regenerate; do not hand-edit.',
  ...entries.map((e) => e.text.split('\n').map((l) => `  ${l}`).join('\n')),
  `  # <<< ${BLOCK_ID}: END managed block <<<`,
].join('\n');

const result = {
  schemaVersion: 1,
  tool: 'settings-to-entries',
  settings: path.resolve(settingsPath),
  sections: self_reported(sections),
  entries: entries.map((e) => ({ section: e.section, row: e.row, renamed: e.renamed })),
  problems,
  blockLines: block.split('\n').length,
  block,
};
function self_reported(ss) { return ss.map((s) => s.name); }

const installPath = val('--install');
const outPath = val('--out');
const wantPrint = ARGS.includes('--print') || (!installPath && !outPath && !JSON_MODE);

if (problems.length > 0) {
  if (JSON_MODE) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  else {
    process.stdout.write('settings-to-entries: REFUSED — nothing was written.\n');
    for (const p of problems) process.stdout.write(`  - ${p}\n`);
  }
  process.exit(7);
}

const target = installPath ?? outPath;
if (target) {
  const abs = path.resolve(target);
  const next = installPath ? spliceBlock(fs.readFileSync(abs, 'utf8'), block, BLOCK_ID) : `${block}\n`;
  if (installPath && next.problems) {
    if (JSON_MODE) process.stdout.write(`${JSON.stringify({ ...result, problems: next.problems }, null, 2)}\n`);
    else { process.stdout.write('settings-to-entries: REFUSED — nothing was written.\n'); for (const p of next.problems) process.stdout.write(`  - ${p}\n`); }
    process.exit(7);
  }
  const textOut = installPath ? next.text : next;
  if (ARGS.includes('--check')) {
    const same = fs.readFileSync(abs, 'utf8') === textOut;
    process.stdout.write(`settings-to-entries --check: ${same ? 'UP TO DATE' : 'DRIFT'} — ${abs}\n`);
    process.exit(same ? 0 : 1);
  }
  fs.writeFileSync(abs, textOut);
  result.wrote = abs;
}

if (JSON_MODE) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
else if (wantPrint) process.stdout.write(`${block}\n`);
else process.stdout.write(`settings-to-entries: ${entries.length} entr(ies) from ${sections.length} section(s)`
  + `${target ? ` -> ${path.resolve(target)}` : ''}\n`
  + entries.map((e) => `  ${e.section.padEnd(22)} -> row ${e.row}${e.renamed ? '  (renamed)' : ''}\n`).join(''));
process.exit(0);

/** Replace an existing managed block, or append one before the sequence's closing bracket. */
function spliceBlock(text, body, id) {
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const lines = text.split(/\r?\n/);
  const begin = lines.findIndex((l) => l.includes(`${id}: BEGIN`));
  const end = lines.findIndex((l) => l.includes(`${id}: END`));
  const bodyLines = body.split('\n');
  if (begin !== -1 && end !== -1 && end > begin) {
    const next = [...lines.slice(0, begin), ...bodyLines, ...lines.slice(end + 1)].join(eol);
    return { text: next };
  }
  if (begin !== -1 || end !== -1) {
    return { problems: [`the ${id} markers are unbalanced (BEGIN ${begin === -1 ? 0 : 1}, END ${end === -1 ? 0 : 1}); refusing to guess which region is ours`] };
  }
  let close = -1;
  for (let i = lines.length - 1; i >= 0; i -= 1) { if (lines[i].trim() === ']') { close = i; break; } }
  if (close === -1) return { problems: ['the profile patch has no closing `]` line, so there is no sequence to append to'] };
  const next = [...lines.slice(0, close), ...bodyLines, ...lines.slice(close)].join(eol);
  return { text: next };
}
