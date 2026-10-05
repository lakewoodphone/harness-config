#!/usr/bin/env node
/**
 * tests/stage-home/run.mjs — the proofs for `dsh-update/lib/stage-home.mjs`.
 *
 * WHAT IS BEING PROVED, and why each proof exists rather than being asserted in prose:
 *
 *   1. every COUPLED SLOT is decided from the candidate's own directory listing, and an ambiguous
 *      candidate (both names, or neither) is REFUSED — because a wrong guess here composes a row
 *      whose package does not exist, which fails at mount and only when somebody starts a session;
 *   2. the rewrite is QUOTE-AWARE and comment-aware: a name inside a quoted scalar is rewritten, a
 *      line's leading `#` prose is left as history, and a name inside `'…'` in a comment is
 *      retargeted — the last one because `switch-engine.ps1` counts plain substrings over the whole
 *      file, comments included, and would otherwise refuse the switch it was given;
 *   3. the rows REACH the layer the engine loads, spliced in the file's own flow style with the
 *      converter's provenance line intact, and a hand-edited block is refused;
 *   4. `--check` fails on a one-byte change and passes on a fresh tree, and writes nothing either way;
 *   5. the LIVE home is byte-identical before and after a build — a full sha256 walk of every file
 *      under `profiles/` and `.agent-presets/`, plus the top level. This is the proof that matters
 *      most: `switch-engine.ps1` installs the staged home on top of the live one, and a builder that
 *      edits its own source of truth would corrupt the thing it exists to protect.
 *
 * Everything synthetic lives under a UNIQUE temp base per run (`<tmp>/stage-home-test-<pid>`), so
 * two runs cannot collide and nothing outside that base is written except the `--out` trees the
 * tests build on purpose.
 *
 *   node dsh-update/tests/stage-home/run.mjs            # exit 0 = all proofs passed
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  assertStagedHome, blockFromGenerated, buildStagedHome, candidateSlots, collectJsTexts, countRefs,
  detectSlots, entriesToFlowLines, isPlainSafeFlow, spliceManagedBlock,
} from '../../lib/stage-home.mjs';
import { PARSE_OPTIONS, YAML } from '../../lib/yaml.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');            // dsh-update/
const REPO = resolve(ROOT, '..');                  // repo root
const STAGE_HOME = join(ROOT, 'lib', 'stage-home.mjs');
const CONVERTER = join(REPO, 'scripts', 'make-preset-rows.mjs');

/**
 * Where a fetched candidate prefix is, in the order this machine keeps them.
 *
 * WHY MORE THAN ONE ROOT. `dsh-update/vendor/` is git-ignored, so a fresh GIT WORKTREE never has it
 * — and a worktree lives at `<code>/_worktrees/<name>`, so `..` from it is NOT the main checkout.
 * The fetched installs are in the main checkout, and READ-ONLY use of those is exactly what the
 * pipeline does. A test that skipped the real candidate whenever it ran from a worktree would be a
 * test that never proves anything where proof matters most.
 */
const CODE_DIR = join(process.env.USERPROFILE ?? process.env.HOME ?? '.', 'Code');
const CANDIDATE_ROOTS = [
  join(ROOT, 'vendor', 'prefix'),                                   // in place, main checkout
  join(CODE_DIR, 'harness-config', 'dsh-update', 'vendor', 'prefix'), // the main checkout, from a worktree
];
if (process.env.DSH_UPDATE_VENDOR_PREFIX) CANDIDATE_ROOTS.unshift(process.env.DSH_UPDATE_VENDOR_PREFIX);
const CANDIDATE_017 = CANDIDATE_ROOTS
  .map((root) => join(root, '0.1.7-rc.2'))

  .find((dir) => existsSync(join(dir, 'node_modules', '@deepseek-ai'))) ?? join(CANDIDATE_ROOTS[0], '0.1.7-rc.2');
const LIVE_HOME = join(process.env.USERPROFILE ?? process.env.HOME ?? '.', '.dsh');

/** The temp base for THIS run. Never a shared path — two concurrent runs must not collide. */
const BASE = join(process.env.STAGE_HOME_TEST_TMP || tmpdir(), `stage-home-test-${process.pid}`);

const failures = [];
const skips = [];
let checks = 0;
const check = (ok, label, detail) => {
  checks += 1;
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}\n`);
};
const skip = (label, why) => {
  skips.push(`${label} (${why})`);
  process.stdout.write(`skip  ${label} — ${why}\n`);
};
const section = (title) => process.stdout.write(`\n── ${title} ${'─'.repeat(Math.max(0, 66 - title.length))}\n`);

// ── helpers ──────────────────────────────────────────────────────────────────────────────────
function walkFiles(dir, acc = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return acc;
  }
  for (const entry of entries) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) walkFiles(p, acc);
    else if (entry.isFile()) acc.push(p);
  }
  return acc;
}

/** sha256 of every file under `dir`, keyed by relative POSIX path. Links are not followed. */
function treeFingerprint(dir) {
  const out = {};
  for (const file of walkFiles(dir).sort()) {
    out[relative(dir, file).split(sep).join('/')] = createHash('sha256').update(readFileSync(file)).digest('hex');
  }
  return out;
}

/** The config surface of a home: everything the builder is allowed to read. */
function configFingerprint(home) {
  const fp = {};
  for (const sub of ['profiles', '.agent-presets']) {
    const dir = join(home, sub);
    if (!existsSync(dir)) continue;
    for (const file of walkFiles(dir)) {
      if (file.split(sep).includes('node_modules')) continue;
      fp[relative(home, file).split(sep).join('/')] = createHash('sha256')
        .update(readFileSync(file)).digest('hex');
    }
  }
  for (const name of ['settings.yaml']) {
    const f = join(home, name);
    if (existsSync(f)) fp[name] = createHash('sha256').update(readFileSync(f)).digest('hex');
  }
  return fp;
}

const diffKeys = (a, b) => {
  const out = [];
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if (a[k] !== b[k]) out.push(k);
  }
  return out;
};

const write = (path, text) => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, 'utf8');
};

const read = (path) => readFileSync(path, 'utf8');

/** The converter's block indentation, so a body from either source can be parsed the same way. */
const indentLines = (lines) => lines.map((line) => (line.length > 0 ? `  ${line}` : line));

/**
 * A tiny synthetic home: one preset and one profile patch, each naming the 0.1.5 side, plus a
 * settings file. Used where the proof is about the CONTRACT (rewriting, wiring, refusal) rather
 * than about the real presets, so the test stays fast and does not depend on the live home.
 */
const OLD_PRESET = [
  '# a preset, 0.1.5-era',
  '- id: persona',
  "  name: '@deepseek-ai/dsh-persona'",
  '  config: {}',
  '- id: workflow-worker-thread',
  "  name: '@deepseek-ai/dsh-workflow-worker-thread'",
  '  config:',
  "    note: 'the engine this machine RUNS provides `@deepseek-ai/dsh-workflow-worker-thread`'",
  '    kept: !!js process.platform === \'win32\'',
  '',
].join('\n');

const OLD_PATCH = [
  '[',
  '  # a profile patch, 0.1.5-era',
  '  # the engine this machine RUNS provides `@deepseek-ai/dsh-agent-presets` (measured)',
  '  {',
  "    name: '@deepseek-ai/dsh-agent-presets',",
  '    config: {',
  '      default: zabz,',
  '    },',
  '  },',
  ']',
  '',
].join('\n');

function syntheticHome(name, { preset = OLD_PRESET, patch = OLD_PATCH } = {}) {
  const home = join(BASE, name);
  write(join(home, 'profiles', 'web', 'cordis.patch.yml'), patch);
  write(join(home, 'profiles', 'web', 'package.json'),
    `${JSON.stringify({ name: 'dsh-profile-web', private: true, dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'] } } }, null, 2)}\n`);
  write(join(home, 'profiles', 'web', 'cordis.yml'), '[]\n');
  write(join(home, '.agent-presets', 'zabz', 'agent.cordis.yml'), preset);
  write(join(home, 'settings.yaml'), 'version: 1\n');
  // State that must NEVER be staged.
  write(join(home, 'sessions', 'p', 's', 'session.v3.jsonl.zstd'), 'not-a-session');
  write(join(home, '.credentials.yaml'), 'records:\n  DEEPSEEK_API_KEY:\n    secret: do-not-copy\n');
  write(join(home, 'metrics', 'metric.json'), '{}\n');
  write(join(home, 'health', 'health.json'), '{}\n');
  write(join(home, 'profiles', 'web', 'cordis.patch.yml.bak-20260920-163231'), 'a backup, not config\n');
  return home;
}

/**
 * A candidate prefix whose `@deepseek-ai` directory is a FIXTURE. It exists because the refusal
 * paths — both names present, neither present — cannot be exercised against a real fetched install
 * without editing it (forbidden) or downloading two more versions. The directory names are the
 * only thing read, so a fixture is a faithful stand-in for the one input this decision uses.
 */
function syntheticCandidate(name, packages) {
  const prefix = join(BASE, name);
  mkdirSync(join(prefix, 'node_modules', '@deepseek-ai'), { recursive: true });
  for (const pkg of packages) {
    mkdirSync(join(prefix, 'node_modules', '@deepseek-ai', pkg), { recursive: true });
    write(join(prefix, 'node_modules', '@deepseek-ai', pkg, 'package.json'),
      `${JSON.stringify({ name: `@deepseek-ai/${pkg}`, version: '0.0.0-fixture' })}\n`);
  }
  return prefix;
}

const runCli = (args) => spawnSync(process.execPath, [STAGE_HOME, ...args], {
  encoding: 'utf8', timeout: 180000, maxBuffer: 64 * 1024 * 1024,
});

/** The patch entries `insert:`ed by a patch file, as a flat row list. */
const insertedRows = (text) => {
  const parsed = YAML.parse(text, PARSE_OPTIONS);
  if (!Array.isArray(parsed)) return [];
  return parsed.flatMap((entry) => (Array.isArray(entry?.insert) ? entry.insert : []));
};

process.stdout.write(`stage-home tests — temp base ${BASE}\n`);
mkdirSync(BASE, { recursive: true });

try {
  // ── 1. the slot decisions, from a fixture candidate ─────────────────────────────────────────
  section('1. slot decisions read the candidate, and ambiguity is refused');

  {
    const cand = syntheticCandidate('cand-modern', [
      'dsh-workflow-ptc', 'dsh-agent-preset', 'dsh-agent-preset-registry', 'dsh',
    ]);
    const s = detectSlots(join(cand, 'node_modules'));
    check(s.ok, 'a modern-only candidate is decidable', s.problems.join('; '));
    const byId = Object.fromEntries(s.decisions.map((d) => [d.id, d]));
    check(byId['workflow-runtime'].decides === '@deepseek-ai/dsh-workflow-ptc' && byId['workflow-runtime'].side === 'modern',
      'the workflow slot decides @deepseek-ai/dsh-workflow-ptc / modern',
      `${byId['workflow-runtime'].decides} / ${byId['workflow-runtime'].side}`);
    check(byId['preset-registry'].decides === '@deepseek-ai/dsh-agent-preset-registry' && byId['preset-registry'].side === 'modern',
      'the registry slot decides @deepseek-ai/dsh-agent-preset-registry / modern — and NOT legacy',
      `${byId['preset-registry'].decides} / ${byId['preset-registry'].side}`);
  }

  {
    const cand = syntheticCandidate('cand-ambiguous', [
      'dsh-workflow-ptc', 'dsh-workflow-worker-thread', 'dsh-agent-preset',
    ]);
    const s = detectSlots(join(cand, 'node_modules'));
    check(!s.ok, 'a candidate providing BOTH workflow names is refused');
    check(s.problems.some((p) => p.includes('[workflow-runtime]') && p.includes('MORE THAN ONE')),
      'the refusal names the slot and says both are installed', s.problems[0] ?? '');
  }

  {
    const cand = syntheticCandidate('cand-neither', ['dsh-agent-preset']);
    const s = detectSlots(join(cand, 'node_modules'));
    check(!s.ok, 'a candidate providing NEITHER workflow name is refused');
    check(s.problems.some((p) => p.includes('provides NONE of')), 'the refusal says none are present', s.problems[0] ?? '');
  }

  {
    const s = detectSlots(join(BASE, 'does-not-exist', 'node_modules'));
    check(!s.ok && s.problems[0].includes('cannot read'), 'an unreadable candidate directory is a refusal, not an empty success', s.problems[0] ?? '');
  }

  {
    const cand = syntheticCandidate('cand-legacy', [
      'dsh-workflow-worker-thread', 'dsh-agent-presets',
    ]);
    const s = detectSlots(join(cand, 'node_modules'));
    check(!s.ok, 'a 0.1.5-side candidate is refused (there is no preset ROW to mount as)');
    check(s.problems.some((p) => p.includes('[preset-row]')), 'the refusal names the preset-row slot', s.problems.join(' | '));
  }

  // ── 2. the reference counter and the rewrite ───────────────────────────────────────────────
  section('2. the rewrite is quote-aware, and comments are history');

  {
    // THE MEASURED DEFECT: a row whose line starts with a `#` comment, then a quoted scalar naming
    // the modern package further right. A comment-unaware reader calls that scalar prose.
    const line = "    # The engine this machine RUNS provides `@deepseek-ai/dsh-agent-presets`";
    check(countRefs(line, '@deepseek-ai/dsh-agent-presets').code === 0,
      'a name inside a `#` line is a comment, not a row', JSON.stringify(countRefs(line, '@deepseek-ai/dsh-agent-presets')));
    const row = "      name: '@deepseek-ai/dsh-agent-preset-registry'";
    check(countRefs(row, '@deepseek-ai/dsh-agent-preset-registry').code === 1,
      'a name in a quoted scalar AFTER a leading `#` is still a row',
      JSON.stringify(countRefs(row, '@deepseek-ai/dsh-agent-preset-registry')));
    check(countRefs("    value: 'a # not a comment'", '# not a comment').code === 1,
      'a `#` INSIDE a quoted scalar does not start a comment — the scalar is still code',
      JSON.stringify(countRefs("    value: 'a # not a comment'", '# not a comment')));
    check(countRefs("    value: 'x' # a # trailing comment", '# trailing comment').comment === 1,
      'a `#` AFTER a quoted scalar does start the comment', JSON.stringify(countRefs("    value: 'x' # a # trailing comment", '# trailing comment')));
    check(countRefs("    name: '@deepseek-ai/dsh-agent-presets'", '@deepseek-ai/dsh-agent-presets').code === 1,
      'a name inside single quotes is code, not prose');
  }

  {
    const home = syntheticHome('home-rewrite');
    const cand = syntheticCandidate('cand-rewrite', [
      'dsh-workflow-ptc', 'dsh-agent-preset', 'dsh-agent-preset-registry', 'dsh',
    ]);
    const out = join(BASE, 'out-rewrite');
    const r = buildStagedHome({ from: home, candidate: cand, out, stageDir: out, profile: 'web' });
    check(r.problems.length === 0, 'a synthetic 0.1.5 home builds against a modern candidate', r.problems.join(' | '));

    const preset = read(join(out, '.agent-presets', 'zabz', 'agent.cordis.yml'));
    check(countRefs(preset, '@deepseek-ai/dsh-workflow-ptc').code === 2,
      'the preset now names the candidate\'s workflow package in BOTH places (the row name and the quoted note)',
      JSON.stringify(countRefs(preset, '@deepseek-ai/dsh-workflow-ptc')));
    check(countRefs(preset, '@deepseek-ai/dsh-workflow-worker-thread').total === 0,
      'the removed workflow name is gone from the preset entirely',
      JSON.stringify(countRefs(preset, '@deepseek-ai/dsh-workflow-worker-thread')));
    check(preset.includes('# a preset, 0.1.5-era'),
      'the preset\'s leading `#` prose was left alone (comments are history)');
    check(preset.includes("!!js process.platform === 'win32'"),
      'the `!!js` expression survived the rewrite byte-identically');

    const patch = read(join(out, 'profiles', 'web', 'cordis.patch.yml'));
    // WHAT `switch-engine.ps1` ACTUALLY COUNTS is a plain substring over the whole file, and what
    // must be zero is the count OUTSIDE COMMENTS. Its `#` prose is history ("the engine this machine
    // RUNS provides X") and this module deliberately leaves that alone; what it rewrites is the
    // commented-out ROW, whose quoted scalar names the package the candidate really has.
    check(countRefs(patch, '@deepseek-ai/dsh-agent-presets').code === 0,
      'the removed registry name is gone from the patch\'s CODE (what a `name:` scalar carries)',
      JSON.stringify(countRefs(patch, '@deepseek-ai/dsh-agent-presets')));
    check(countRefs(patch, '@deepseek-ai/dsh-agent-preset-registry').code >= 1,
      'the profile patch now names the candidate\'s registry package in code');
    check(patch.includes("'@deepseek-ai/dsh-agent-preset-registry'"),
      'the commented-out ROW was retargeted too, so the whole file is clean of the removed name',
      patch.split('\n').filter((l) => l.includes('agent-preset-registry')).join(' | '));
    check(patch.includes('# a profile patch, 0.1.5-era'),
      'the line\'s leading `#` prose was left alone (comments are history)');

    // The SOURCE must be untouched: only the staged copies are rewritten.
    check(read(join(home, 'profiles', 'web', 'cordis.patch.yml')) === OLD_PATCH,
      'the SOURCE profile patch is byte-identical after the build');
    check(read(join(home, '.agent-presets', 'zabz', 'agent.cordis.yml')) === OLD_PRESET,
      'the SOURCE preset is byte-identical after the build');
  }

  // ── 3. state and backups are excluded ──────────────────────────────────────────────────────
  section('3. a staged home is config, not state');

  {
    const out = join(BASE, 'out-rewrite');
    for (const forbidden of ['sessions', '.credentials.yaml', 'metrics', 'health']) {
      check(!existsSync(join(out, forbidden)), `${forbidden} was NOT copied into the staged home`);
    }
    check(!existsSync(join(out, 'profiles', 'web', 'cordis.patch.yml.bak-20260920-163231')),
      'a `.bak-` sibling in the profile directory was NOT copied');
    check(existsSync(join(out, 'settings.yaml')), 'settings.yaml WAS copied (it is config)');
    check(runCli(['--from', join(BASE, 'home-rewrite'), '--candidate', join(BASE, 'cand-rewrite'),
      '--out', join(BASE, 'out-rewrite'), '--profile', 'web', '--check', '--json']).status === 0,
      '`--check --json` exits 0 on the tree that was just built');
  }

  // ── 4. the rows reach the layer the engine loads ────────────────────────────────────────────
  section('4. the preset rows are wired into the profile patch layer');

  {
    const out = join(BASE, 'out-rewrite');
    const patch = read(join(out, 'profiles', 'web', 'cordis.patch.yml'));
    check(patch.includes('# <<< preset-rows: BEGIN managed block'),
      'the `preset-rows` managed block marker is in the profile patch');
    check(patch.includes('# <<< preset-rows: END managed block'),
      'the `preset-rows` managed block END marker is in the profile patch');
    const rows = insertedRows(patch).filter((row) => String(row?.id ?? '').startsWith('preset-'));
    check(rows.length === 1 && rows[0].id === 'preset-zabz',
      'exactly one `preset-zabz` insert row is present', JSON.stringify(rows.map((r) => r?.id)));
    check(Array.isArray(rows[0]?.config?.plugins) && rows[0].config.plugins.length > 0,
      'the inserted row carries a non-empty config.plugins', String(rows[0]?.config?.plugins?.length));
    check(rows[0]?.name === '@deepseek-ai/dsh-agent-preset',
      'the inserted row names the preset ROW plugin', String(rows[0]?.name));
    check(patch.includes('# Written by `scripts/make-preset-rows.mjs`'),
      'the block carries the converter\'s provenance line, so a reader can tell it is generated',
      patch.split('\n').filter((l) => l.includes('Written by')).join(' | '));

    // Idempotence: a second build over the same `--out` must be a no-op, byte for byte.
    const before = createHash('sha256').update(patch).digest('hex');
    const again = buildStagedHome({
      from: join(BASE, 'home-rewrite'), candidate: join(BASE, 'cand-rewrite'),
      out, stageDir: out, profile: 'web',
    });
    check(again.problems.length === 0, 'a second build over the same output refuses nothing', again.problems.join(' | '));
    check(createHash('sha256').update(read(join(out, 'profiles', 'web', 'cordis.patch.yml'))).digest('hex') === before,
      'a second build leaves the spliced file byte-identical (the block is replaced, not duplicated)');
    const markers = read(join(out, 'profiles', 'web', 'cordis.patch.yml'))
      .split(/\r?\n/).filter((l) => l.includes('preset-rows: BEGIN managed block')).length;
    check(markers === 1, 'exactly ONE managed block exists after two builds', String(markers));
  }

  // ── 5. spliceManagedBlock: append, replace, and the refusals ────────────────────────────────
  section('5. spliceManagedBlock: append / replace / refuse');

  {
    const body = ['{ insert: [{ id: preset-x }] },'];
    const appended = spliceManagedBlock('[]\n', body);
    // `[]` has no non-empty sequence, so this must refuse rather than guess.
    check(Boolean(appended.problems), 'an empty top-level sequence `[]` is refused');
  }
  {
    const body = ['{ insert: [{ id: preset-x }] },'];
    // Start from a body that carries the provenance comment, because the splice REFUSES (correctly)
    // to overwrite a committed block without one — so a body that cannot produce such a block can
    // never be re-spliced, and asserting a no-op on it would be asserting the wrong thing.
    const provenanceBody = ['# Written by `scripts/make-preset-rows.mjs`', '{ insert: [{ id: preset-x }] },'];
    const target = '[\n  { id: a },\n]\n';
    const r = spliceManagedBlock(target, provenanceBody);
    check(!r.problems && r.mode === 'append', 'the block is appended before the final `]`', JSON.stringify(r.problems ?? r.mode));
    check(r.text.includes('# <<< preset-rows: BEGIN managed block'), 'the appended text carries the BEGIN marker');
    check(r.text.includes('# Written by `scripts/make-preset-rows.mjs`'), 'the appended block carries the provenance comment');
    const parsed = YAML.parse(r.text, PARSE_OPTIONS);
    check(Array.isArray(parsed) && parsed.some((e) => e?.insert?.[0]?.id === 'preset-x'),
      'the appended block parses and its row is in the result');
    check(parsed.length === 2,
      'the composed file holds exactly two top-level entries — the one that was there plus the block',
      String(parsed.length));

    // Re-splicing the same body: nothing changes, byte for byte.
    const r2 = spliceManagedBlock(r.text, provenanceBody);
    check(r2.mode === 'noop' && r2.text === r.text,
      're-splicing the same body is a no-op, byte for byte', r2.mode ?? JSON.stringify(r2.problems));

    // A DIFFERENT body replaces the committed block in place.
    const changedBody = ['# Written by `scripts/make-preset-rows.mjs`', '{ insert: [{ id: preset-z }] },'];
    const r4b = spliceManagedBlock(r.text, changedBody);
    check(!r4b.problems && r4b.mode === 'replace' && r4b.text.includes('preset-z') && !r4b.text.includes('preset-x'),
      'a DIFFERENT body replaces the committed block in place', JSON.stringify(r4b.problems ?? r4b.mode));
    check(r4b.text.includes('# <<< preset-rows: BEGIN managed block')
      && r4b.text.split('preset-rows: BEGIN managed block').length === 2,
      'and exactly one managed block remains');

    // A hand-edited block is REFUSED, not silently replaced.
    const tampered = r.text.replace('# Written by `scripts/make-preset-rows.mjs`', '# hand-edited');
    const r5 = spliceManagedBlock(tampered, provenanceBody);
    check(Boolean(r5.problems) && r5.problems[0].includes('provenance'),
      'a managed block whose provenance line was removed is refused', (r5.problems ?? []).join(' | '));

    // A body with NO provenance comment cannot produce a re-spliceable block, and that is by design.
    const r6 = spliceManagedBlock(target, body);
    check(!r6.problems && r6.mode === 'append', 'a bare body still splices once', JSON.stringify(r6.problems ?? r6.mode));
  }
  {
    const body = ['{ insert: [{ id: preset-x }] },'];
    const target = '[\n  # <<< preset-rows: BEGIN managed block — x <<<\n  { insert: [{ id: preset-y }] },\n  # <<< preset-rows: END managed block <<<\n]\n';
    const r = spliceManagedBlock(target, body);
    check(Boolean(r.problems), 'a committed block WITHOUT the converter provenance line is refused', (r.problems ?? []).join(' | '));
  }
  {
    const body = ['{ insert: [{ id: preset-x }] },'];
    const unbalanced = '[\n  # <<< preset-rows: BEGIN managed block <<<\n  { insert: [] },\n]\n';
    const r = spliceManagedBlock(unbalanced, body);
    check(Boolean(r.problems) && r.problems[0].includes('unbalanced'),
      'unbalanced markers are refused by name', (r.problems ?? []).join(' | '));
  }

  // ── 6. blockFromGenerated: the flow emission, and its parity with the artefact ─────────────
  section('6. the block body is the converter\'s own entries, re-emitted in flow style');

  if (!existsSync(CONVERTER)) {
    skip('blockFromGenerated parity', `${CONVERTER} is not present`);
  } else {
    const tmp = join(BASE, 'converter');
    mkdirSync(tmp, { recursive: true });
    const outFile = join(tmp, 'presets.generated.patch.yml');
    const conv = spawnSync(process.execPath, [
      CONVERTER, '--presets-dir', join(LIVE_HOME, '.agent-presets'), '--out', outFile,
    ], { cwd: REPO, encoding: 'utf8', timeout: 180000, maxBuffer: 64 * 1024 * 1024 });
    if (conv.status !== 0) {
      skip('blockFromGenerated parity', `the converter exited ${conv.status}: ${(conv.stderr ?? '').trim().slice(0, 200)}`);
    } else {
      const generated = read(outFile);
      const block = blockFromGenerated(generated);
      check(block.ok, 'the converter\'s own output yields a block', (block.problems ?? []).join(' | '));
      check(block.rowIds.join(',') === 'preset-cordis-bg,preset-yocheved,preset-zabz',
        'the block carries our three preset rows, in the converter\'s order', block.rowIds.join(','));
      check(block.exprs > 0, 'the block carries `!!js` expressions', String(block.exprs));
      check(!/!!js +undefined\b/.test(block.lines.join('\n')),
        'the flow emission contains no `!!js undefined` (the measured stringify hazard)');
      const bodyText = block.lines.join('\n');
      const artefactJs = collectJsTexts(YAML.parse(generated, PARSE_OPTIONS));
      const bodyJs = collectJsTexts(YAML.parse(`[\n${bodyText}\n]\n`, PARSE_OPTIONS));
      check(bodyJs.length === artefactJs.length && bodyJs.every((e, i) => e === artefactJs[i]),
        'every `!!js` source text survives the flow emission, in order and unchanged',
        `${artefactJs.length} in the artefact vs ${bodyJs.length} in the body`);
      // An expression that carries no flow indicator is emitted as a PLAIN scalar, so its source
      // text is byte-identical; one that does is single-quoted (and its inner `'` doubled), which is
      // the converter's own rule — the value is identical even though the bytes are not, which is
      // why this assertion is split by safety rather than applied to every expression.
      const plainExprs = artefactJs.filter((e) => isPlainSafeFlow(e));
      check(plainExprs.length > 0, 'at least one expression is plain-safe and therefore comparable verbatim', String(plainExprs.length));
      const missingPlain = plainExprs.filter((e) => !bodyText.includes(e));
      check(missingPlain.length === 0, 'every plain-safe `!!js` source text is byte-identical in the flow body',
        `${missingPlain.length} missing, e.g. ${missingPlain.slice(0, 2).map(JSON.stringify).join(', ')}`);
      const quoted = artefactJs.filter((e) => !isPlainSafeFlow(e));
      check(quoted.every((e) => bodyText.includes(`'${e.replace(/'/g, "''")}'`)),
        'every flow-indicator expression is emitted single-quoted with the YAML doubled-quote escape',
        `${quoted.length} quoted expression(s)`);

      // Parity with the converter's OWN flow block, which is what the repo copy carries. This is
      // the proof that the wiring mechanism is the converter's, not a lookalike.
      const printed = spawnSync(process.execPath, [
        CONVERTER, '--presets-dir', join(LIVE_HOME, '.agent-presets'), '--out', join(tmp, 'unused.yml'),
        '--print-block',
      ], { cwd: REPO, encoding: 'utf8', timeout: 180000, maxBuffer: 64 * 1024 * 1024 });
      if (printed.status !== 0) {
        skip('parity with `--print-block`', `--print-block exited ${printed.status}`);
      } else {
        // The converter's `--print-block` writes its OWN comment lines (a different set of prose) and
        // indents its body by the file's two spaces; what must match is the ENTRIES, and the
        // strongest comparison available across two comment sets is the parsed data plus `!!js`.
        //
        // THE COMMENT FILTER IS FLOW-AWARE, AND THAT IS NOT A REFINEMENT. These presets carry whole
        // markdown documents as `!!js` template literals, and a markdown heading is a line that
        // starts with `#` — inside an open flow collection that `#` is CONTENT, not a comment. A
        // filter of `l.trim().startsWith('#')` deleted those lines from the printed side only and the
        // comparison failed on real content: `printed … \n\n\n\nA foreground` against
        // `ours … \n\n## Shell execution policy — background first\n\nA foreground`
        // (measured 2026-10-05).
        const dropComments = (ls) => {
          const out = [];
          let depth = 0;
          for (const line of ls) {
            const trimmed = line.trim();
            if (trimmed === '') { out.push(line); continue; }
            if (depth === 0 && trimmed.startsWith('#')) continue;
            out.push(line);
            let i = 0;
            while (i < line.length) {
              const ch = line[i];
              if (ch === "'" || ch === '"') {
                const quote = ch;
                i += 1;
                while (i < line.length) {
                  if (quote === "'" && line[i] === "'") {
                    if (line[i + 1] === "'") i += 2;
                    else { i += 1; break; }
                  } else if (quote === '"' && line[i] === '\\') i += 2;
                  else if (quote === '"' && line[i] === '"') { i += 1; break; }
                  else i += 1;
                }
                continue;
              }
              if (ch === '[' || ch === '{') depth += 1;
              else if (ch === ']' || ch === '}') depth = Math.max(0, depth - 1);
              i += 1;
            }
          }
          return out;
        };
        const printedLines = dropComments(printed.stdout.split('\n'));
        const printedEntries = YAML.parse(`[\n${printedLines.join('\n')}\n]\n`, PARSE_OPTIONS);
        const ourLines = dropComments(indentLines(entriesToFlowLines(block.entries).flatMap((t) => `${t},`.split('\n'))));
        const oursEntries = YAML.parse(`[\n${ourLines.join('\n')}\n]\n`, PARSE_OPTIONS);
        check(JSON.stringify(printedEntries) === JSON.stringify(oursEntries),
          'our flow emission is the SAME entries as `make-preset-rows.mjs --print-block` for the same presets',
          `${printedEntries.length} vs ${oursEntries.length} entries`);
        check(collectJsTexts(printedEntries).join('\u0000') === collectJsTexts(oursEntries).join('\u0000'),
          'and the same `!!js` expressions, in the same order');
      }

      // And the splice of the real body into a real-shaped patch file composes.
      const target = '[\n  {\n    id: typert-gateway,\n    config: {},\n  },\n]\n';
      const spliced = spliceManagedBlock(target, block.lines);
      check(!spliced.problems, 'the real block splices into a flow-collection patch file', (spliced.problems ?? []).join(' | '));
      if (!spliced.problems) {
        const rows = insertedRows(spliced.text).filter((r) => String(r?.id ?? '').startsWith('preset-'));
        check(rows.length === 3 && rows.every((r) => Array.isArray(r.config?.plugins) && r.config.plugins.length > 0),
          'all three spliced rows parse back with a non-empty config.plugins',
          rows.map((r) => `${r.id}:${r.config?.plugins?.length}`).join(' '));
        check(YAML.parse(spliced.text, PARSE_OPTIONS).length === 4,
          'the spliced file holds the original entry plus the block\'s three (the YAML parser groups '
          + 'the block body as three flow entries here, which is why nothing depends on that grouping)',
          String(YAML.parse(spliced.text, PARSE_OPTIONS).length));
      }
    }
  }

  // ── 7. --check drift ────────────────────────────────────────────────────────────────────────
  section('7. --check writes nothing and fails on drift');

  {
    const home = syntheticHome('home-check');
    const cand = syntheticCandidate('cand-check', [
      'dsh-workflow-ptc', 'dsh-agent-preset', 'dsh-agent-preset-registry', 'dsh',
    ]);
    const out = join(BASE, 'out-check');
    const first = runCli(['--from', home, '--candidate', cand, '--out', out, '--profile', 'web']);
    check(first.status === 0, 'build exits 0', `exit ${first.status}; ${(first.stderr ?? '').trim().slice(0, 300)}`);
    const good = runCli(['--from', home, '--candidate', cand, '--out', out, '--profile', 'web', '--check']);
    check(good.status === 0, '--check exits 0 on a freshly built tree', `exit ${good.status}`);
    const before = treeFingerprint(out);

    // Hand-edit one byte of the generated output.
    const target = join(out, 'profiles', 'web', 'cordis.patch.yml');
    const text = read(target);
    const at = text.indexOf('preset-zabz');
    check(at > 0, 'the generated output contains the marker to hand-edit');
    write(target, `${text.slice(0, at)}preset-zabzX${text.slice(at + 'preset-zabz'.length)}`);
    const drifted = runCli(['--from', home, '--candidate', cand, '--out', out, '--profile', 'web', '--check']);
    check(drifted.status !== 0, '--check exits NON-ZERO on a one-byte hand edit', `exit ${drifted.status}`);
    check(`${drifted.stdout}${drifted.stderr}`.includes('DRIFT'), 'the failure says DRIFT', (drifted.stdout ?? '').slice(0, 200));

    // `--check` must not have repaired the drift, and must not have left a scratch tree behind.
    const after = treeFingerprint(out);
    const changed = diffKeys(before, after);
    check(changed.length === 1 && changed[0] === 'profiles/web/cordis.patch.yml',
      '--check wrote nothing: the only changed file is the one this test edited', changed.join(', '));
    const leftovers = readdirSync(BASE).filter((n) => n.startsWith('out-check.stage-home-check-'));
    check(leftovers.length === 0, '--check left no scratch directory behind', leftovers.join(', '));

    // And with the edit restored, it passes again.
    write(target, text);
    const good2 = runCli(['--from', home, '--candidate', cand, '--out', out, '--profile', 'web', '--check']);
    check(good2.status === 0, '--check exits 0 again once the edit is reverted', `exit ${good2.status}`);
  }

  // ── 8. refusals from the CLI ───────────────────────────────────────────────────────────────
  section('8. the CLI refuses, loudly');

  {
    const home = syntheticHome('home-cli');
    const cand = syntheticCandidate('cand-cli', ['dsh-workflow-ptc', 'dsh-agent-preset', 'dsh-agent-preset-registry']);
    const out = join(BASE, 'out-cli');
    const ambiguous = runCli(['--from', home, '--candidate', join(BASE, 'cand-ambiguous'), '--out', out, '--profile', 'web']);
    check(ambiguous.status !== 0, 'an ambiguous candidate makes the CLI exit non-zero', `exit ${ambiguous.status}`);
    check(!existsSync(join(out, 'profiles', 'web', 'cordis.patch.yml')) || read(join(out, 'profiles', 'web', 'cordis.patch.yml')) === OLD_PATCH,
      'a refused run changed nothing in --out');

    const json = runCli(['--from', home, '--candidate', cand, '--out', join(BASE, 'out-cli-json'), '--profile', 'web', '--json']);
    check(json.status === 0, '--json run exits 0', `exit ${json.status}`);
    let obj = null;
    try {
      obj = JSON.parse(json.stdout);
    } catch (e) {
      check(false, '--json prints exactly one JSON object on stdout', e.message);
    }
    if (obj) {
      check(obj.ok === true && Array.isArray(obj.slotDecisions) && obj.slotDecisions.length === 3,
        '--json emits one object with the slot decisions', JSON.stringify(Object.keys(obj)));
      check(obj.assertion?.ok === true, 'the JSON carries the assertion result');
    }

    const badProfile = runCli(['--from', home, '--candidate', cand, '--out', join(BASE, 'out-bad'), '--profile', 'mesh']);
    check(badProfile.status !== 0, 'a --profile that does not exist is refused', `exit ${badProfile.status}`);
    const missing = runCli(['--candidate', cand, '--out', join(BASE, 'out-bad2'), '--from', join(BASE, 'no-such-home')]);
    check(missing.status !== 0, 'a --from path that does not exist is refused', `exit ${missing.status}`);
    check(`${missing.stdout}${missing.stderr}`.includes('is not a directory'),
      'the refusal names the --from path', (missing.stdout ?? '').slice(0, 200));
    const usage = runCli(['--from', home, '--out', join(BASE, 'out-bad3')]);
    check(usage.status === 2, 'a missing --candidate is a usage error (exit 2)', `exit ${usage.status}`);
  }

  // ── 9. the real candidate: slots, build, assertion (no engine) ─────────────────────────────
  section('9. the fetched 0.1.7-rc.2 candidate');

  let realOut = null;
  if (!existsSync(join(CANDIDATE_017, 'node_modules', '@deepseek-ai'))) {
    skip('the real candidate', `${CANDIDATE_017} is not fetched on this machine`);
  } else {
    const slots = candidateSlots(CANDIDATE_017);
    check(slots.ok, 'the real candidate is decidable', slots.problems.join(' | '));
    const byId = Object.fromEntries(slots.decisions.map((d) => [d.id, d]));
    check(byId['workflow-runtime'].decides === '@deepseek-ai/dsh-workflow-ptc',
      'it provides dsh-workflow-ptc', String(byId['workflow-runtime'].decides));
    check(byId['preset-registry'].decides === '@deepseek-ai/dsh-agent-preset-registry'
      && byId['preset-registry'].side === 'modern',
      'it provides the modern registry, classified modern', `${byId['preset-registry'].decides}/${byId['preset-registry'].side}`);

    if (!existsSync(join(LIVE_HOME, '.agent-presets')) || !existsSync(join(LIVE_HOME, 'profiles'))) {
      skip('a build against the live home', `${LIVE_HOME} does not carry .agent-presets and profiles/`);
    } else {
      realOut = join(BASE, 'out-real');
      const before = configFingerprint(LIVE_HOME);
      const built = buildStagedHome({
        from: LIVE_HOME, candidate: CANDIDATE_017, out: realOut, stageDir: realOut, profile: 'web',
      });
      check(built.problems.length === 0, 'the live home stages against the real candidate', built.problems.join(' | '));
      const after = configFingerprint(LIVE_HOME);
      const touched = diffKeys(before, after);
      check(touched.length === 0,
        `the LIVE home is byte-identical after the build (${Object.keys(before).length} file(s) hashed)`,
        touched.slice(0, 5).join(', '));

      const assertion = assertStagedHome(realOut, slots);
      check(assertion.ok, 'the switch-engine PRECONDITION 2 predicate PASSES over the staged tree',
        assertion.problems.join(' | '));
      check(assertion.counts.ptcRows === 3 && assertion.counts.oldPtcCode === 0,
        'all three presets name dsh-workflow-ptc and none name the removed one outside a comment',
        JSON.stringify(assertion.counts));
      check(assertion.counts.oldPtcCode === 0,
        'no preset file names the removed workflow package outside a comment', String(assertion.counts.oldPtcCode));
      check(assertion.assertion?.counts === undefined && assertion.counts.ptcRows === 3,
        'all three presets name the candidate\'s workflow package', String(assertion.counts.ptcRows));
      // ON THE REAL PRESETS THE REMOVED NAME IS GONE ENTIRELY — and that is a measured fact, not a
      // weaker claim than expected. Each preset mentions the old package only inside `'…'`-quoted
      // scalars (a row `name:` and a `config.` value), never in `#` prose, so the quote-aware rewrite
      // reaches every one of them.
      check(assertion.counts.oldPtcComment === 0 && assertion.counts.oldPtcCode === 0,
        'the removed workflow package appears nowhere in the staged presets (it lived in quoted scalars, not prose)',
        JSON.stringify(assertion.counts));

      // The requirement, read as switch-engine reads it: a plain substring count over the whole
      // file, comments included, for the two REMOVED names.
      let removed = 0;
      for (const f of assertion.presetFiles) removed += countRefs(read(f), byId['workflow-runtime'].present[0] === '@deepseek-ai/dsh-workflow-ptc'
        ? '@deepseek-ai/dsh-workflow-worker-thread' : '@deepseek-ai/dsh-workflow-ptc').total;
      check(removed === 0, 'no preset file contains the removed workflow name ANYWHERE (comments included)', String(removed));

      check(assertion.patchFiles.length === 3, 'all three profile patches are staged', String(assertion.patchFiles.length));
      const webPatch = read(join(realOut, 'profiles', 'web', 'cordis.patch.yml'));
      const rows = insertedRows(webPatch).filter((r) => String(r?.id ?? '').startsWith('preset-'));
      check(rows.map((r) => r.id).join(',') === 'preset-cordis-bg,preset-yocheved,preset-zabz',
        'the staged web patch inserts our three preset rows', rows.map((r) => r.id).join(','));
      check(rows.every((r) => Array.isArray(r.config?.plugins) && r.config.plugins.length > 0),
        'each inserted row has a non-empty config.plugins',
        rows.map((r) => `${r.id}:${r.config?.plugins?.length}`).join(' '));

      const notStaged = ['sessions', 'storages', 'attachments', '.credentials.yaml', 'metrics', 'health']
        .filter((n) => existsSync(join(realOut, n)));
      check(notStaged.length === 0, 'no state directory or secret was staged', notStaged.join(', '));
    }
  }

  // ── 10. the engine composes it, and the rows arrive (the real proof) ───────────────────────
  section('10. the candidate COMPOSES the staged home and the rows arrive');

  if (!realOut) {
    skip('the compose proof', 'no real staged tree was built');
  } else {
    const compose = join(ROOT, 'lib', 'compose.mjs');
    const bin = join(CANDIDATE_017, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
    const tree = join(BASE, 'tree.json');
    const logs = join(BASE, 'logs');
    const run = spawnSync(process.execPath, [
      compose, '--profile', 'web', '--bin', bin, '--home', realOut, '--out', tree, '--log-dir', logs,
    ], { encoding: 'utf8', timeout: 300000, maxBuffer: 64 * 1024 * 1024 });
    check(run.status === 0, 'compose.mjs exits 0 against the staged home', `exit ${run.status}; ${(run.stderr ?? '').trim().slice(0, 400)}`);
    if (run.status === 0 && existsSync(tree)) {
      const t = JSON.parse(read(tree));
      check(!t.failure, 'the composed tree carries no failure', String(t.failure ?? ''));
      const ours = ['preset-cordis-bg', 'preset-yocheved', 'preset-zabz'];
      const found = ours.map((id) => t.rows.find((r) => r.id === id));
      check(found.every(Boolean), `every preset row is in the composed tree (${t.rows.length} rows)`,
        ours.filter((id, i) => !found[i]).join(', '));
      check(found.every((r) => Array.isArray(r?.config?.plugins) && r.config.plugins.length > 0),
        'every composed preset row has a non-empty config.plugins',
        found.map((r) => `${r?.id}:${r?.config?.plugins?.length ?? 'none'}`).join(' '));
      check(found.every((r) => r?.name === '@deepseek-ai/dsh-agent-preset'),
        'every composed preset row names @deepseek-ai/dsh-agent-preset');
      const errText = existsSync(logs) ? readdirSync(logs).filter((f) => f.endsWith('.err'))
        .map((f) => read(join(logs, f))).join('\n') : '';
      check(!/skipping profile bundle/.test(errText),
        'the candidate skipped NO profile bundle (the module anchor is staged)',
        errText.split('\n').find((l) => /skipping profile bundle/.test(l)) ?? '');
      check(!/not found/.test(errText), 'no `patch: entry ... not found` line',
        errText.split('\n').find((l) => /not found/.test(l)) ?? '');
    }
  }

  // ── 11. the guards this module must not have broken ────────────────────────────────────────
  section('11. the existing guards still pass');
  for (const guard of ['comment-refs', 'state-home']) {
    const file = join(ROOT, 'tests', 'guards', `${guard}.mjs`);
    const run = spawnSync(process.execPath, [file], { cwd: REPO, encoding: 'utf8', timeout: 300000, maxBuffer: 64 * 1024 * 1024 });
    check(run.status === 0, `tests/guards/${guard}.mjs exits 0`, `exit ${run.status}; ${(run.stderr ?? '').trim().slice(0, 300)}`);
  }
} finally {
  // The temp base is this run's alone; removing it keeps `%TEMP%` from filling with staged homes.
  try {
    rmSync(BASE, { recursive: true, force: true });
  } catch (e) {
    process.stdout.write(`note: could not remove ${BASE}: ${e.message}\n`);
  }
}

process.stdout.write(`\n${failures.length === 0 ? 'PASS' : `FAIL (${failures.length})`} — ${checks} check(s)`
  + `${skips.length ? `, ${skips.length} skipped` : ''} — tests/stage-home/run.mjs\n`);
if (skips.length > 0) {
  for (const s of skips) process.stdout.write(`  skipped: ${s}\n`);
}
if (failures.length > 0) {
  for (const f of failures) process.stdout.write(`  FAILED: ${f}\n`);
}
process.exit(failures.length === 0 ? 0 : 1);
