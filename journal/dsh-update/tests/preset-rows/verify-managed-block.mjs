#!/usr/bin/env node
/**
 * verify-managed-block.mjs — prove the `preset-rows` managed block is installed, correct, and safe.
 *
 * WHY THIS EXISTS, AND WHY IT IS NOT THE SAME TEST AS `verify-preset-rows.mjs`
 * ---------------------------------------------------------------------------
 * `verify-preset-rows.mjs` proves the ROWS are right: the standalone artefact round-trips the
 * presets and the candidate engine composes them. It says nothing about whether anything ever
 * MOUNTS them. Measured 2026-09-28: a profile composes from its bundles, then
 * `$DSH_HOME/profiles/<name>/cordis.patch.yml`, then `$DSH_HOME/cordis.patch.yml`, and neither
 * `scripts/sync.py` nor `multi-window/dshw.ps1` mentions `--patch` — so the standalone file alone
 * would never be read and the migration would silently not happen.
 *
 * The wiring is a MARKED MANAGED BLOCK inside the profile layer the engine already loads, and this
 * file proves the four properties that make such a block safe to keep in a hand-edited file:
 *
 *   1. INSTALLED AND EQUAL — the block is between exactly one pair of markers, its entries are the
 *      same patch entries as the standalone artefact (parsed with the same parser, deep-compared),
 *      every `!!js` source text survives, and `!!js undefined` appears nowhere.
 *   2. NOTHING ELSE MOVED — a fresh install into a copy of the real profile patch changes only the
 *      region between (and including) the markers: every byte outside it is identical, checked by
 *      comparing the file with the region removed, before and after.
 *   3. IDEMPOTENT — a second install is a byte-identical no-op.
 *   4. REFUSES — unbalanced markers, duplicated markers, a file with no final `]`, and a filtered
 *      install (`--names` + `--install`) all exit non-zero and leave the file byte-identical.
 *
 * It never writes to the repository's profile patch: every mutation happens in a temp directory, and
 * the repository file is only ever read. `--check` is also run read-only against the committed pair.
 *
 * Usage:
 *   node dsh-update/tests/preset-rows/verify-managed-block.mjs [--target <file>] [--out <file>]
 *
 * Exit 0 when every check passes, 1 otherwise. A failed read is a FAILURE, never an empty pass.
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import { PARSE_OPTIONS, YAML } from '../../lib/yaml.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..');
const SCRIPT = join(REPO_ROOT, 'scripts', 'make-preset-rows.mjs');

const DEFAULTS = {
  target: join(REPO_ROOT, 'profiles', 'web', 'cordis.patch.yml'),
  out: join(REPO_ROOT, 'profiles', 'web', 'presets.generated.patch.yml'),
};

const BEGIN_RE = /^#\s*<<<\s*preset-rows:\s*BEGIN managed block\b/;
const END_RE = /^#\s*<<<\s*preset-rows:\s*END managed block\b/;

const sha256 = (text) => createHash('sha256').update(text, 'utf8').digest('hex');
const isJs = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v) && typeof v.__js === 'string';
/** Escape a literal string for use inside a RegExp. */
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Every `!!js` source text in a value, in document order. */
function collectJsTexts(node, acc = []) {
  if (isJs(node)) acc.push(node.__js);
  else if (Array.isArray(node)) node.forEach((child) => collectJsTexts(child, acc));
  else if (node && typeof node === 'object') Object.values(node).forEach((child) => collectJsTexts(child, acc));
  return acc;
}

/**
 * The block's line range in a file, as [begin, end] 0-based, plus the region the installer owns.
 * The region starts at the blank separator line immediately above BEGIN when there is one, because
 * an APPEND splice inserts that blank line and must therefore own it.
 */
function findBlock(text) {
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const lines = text.split(eol);
  const begins = [];
  const ends = [];
  lines.forEach((line, i) => {
    const t = line.trim();
    if (BEGIN_RE.test(t)) begins.push(i);
    if (END_RE.test(t)) ends.push(i);
  });
  if (begins.length !== 1 || ends.length !== 1 || begins[0] >= ends[0]) {
    return { eol, lines, begins, ends, begin: null, end: null, regionStart: null };
  }
  let regionStart = begins[0];
  while (regionStart > 0 && lines[regionStart - 1].trim() === '') regionStart -= 1;
  return { eol, lines, begins, ends, begin: begins[0], end: ends[0], regionStart };
}

/** The file with the block region removed — the bytes the installer promises never to touch. */
function outsideRegion(text) {
  const { eol, lines, begin, end, regionStart } = findBlock(text);
  if (begin === null) return text;
  return [...lines.slice(0, regionStart), ...lines.slice(end + 1)].join(eol);
}

function parseArgs(argv) {
  const args = { ...DEFAULTS };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--target') args.target = need('--target');
    else if (a === '--out') args.out = need('--out');
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

const rel = (p) => (p.startsWith(REPO_ROOT) ? p.slice(REPO_ROOT.length + 1).replace(/\\/g, '/') : p);

function main() {
  const args = parseArgs(process.argv.slice(2));
  const failures = [];
  const abs = (p) => (isAbsolute(p) ? p : resolve(process.cwd(), p));
  const target = abs(args.target);
  const outFile = abs(args.out);
  const work = mkdtempSync(join(tmpdir(), 'preset-rows-block-'));
  const ctl = (label, ok, detail = '') => {
    if (!ok) failures.push(label + (detail ? ` — ${detail}` : ''));
    console.log(`  [${ok ? 'ok  ' : 'FAIL'}] ${label}${detail ? `  ${detail}` : ''}`);
  };
  /** Run the converter; returns { status, stdout, stderr }. */
  const run = (argv) => {
    const r = spawnSync(process.execPath, [SCRIPT, ...argv], { cwd: REPO_ROOT, encoding: 'utf8' });
    return { status: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
  };

  for (const [label, file] of [['--target', target], ['--out', outFile]]) {
    if (!existsSync(file)) {
      console.error(`FAIL: ${label} does not exist: ${file}`);
      return 1;
    }
  }

  const committedTarget = readFileSync(target, 'utf8');
  const committedOut = readFileSync(outFile, 'utf8');

  // ── 1. the committed pair is installed, marked once, and equal ───────────────────────────────
  console.log('== 1. the committed block: markers, entries, and equality with the standalone artefact ==');
  const found = findBlock(committedTarget);
  ctl('exactly one BEGIN marker and one END marker, BEGIN before END',
    found.begin !== null,
    found.begin === null
      ? `BEGIN x${found.begins.length}, END x${found.ends.length}`
      : `BEGIN line ${found.begin + 1}, END line ${found.end + 1}`);
  if (found.begin === null) {
    console.log('\nRESULT: FAIL — the block is not installed; nothing else can be checked');
    for (const f of failures) console.log(`  - ${f}`);
    return 1;
  }
  console.log(`    begin: ${found.lines[found.begin].trim()}`);
  console.log(`    end  : ${found.lines[found.end].trim()}`);

  const bodyText = found.lines.slice(found.begin + 1, found.end).join(found.eol);
  let blockValue;
  try {
    blockValue = YAML.parse(`[\n${bodyText}\n]\n`, PARSE_OPTIONS);
  } catch (e) {
    ctl('the block body parses as a flow sequence of patch entries', false, e.message);
    blockValue = null;
  }
  if (blockValue) {
    ctl('the block body parses as a flow sequence of patch entries', Array.isArray(blockValue),
      `${Array.isArray(blockValue) ? blockValue.length : '?'} entries`);
  }
  const standaloneValue = YAML.parse(committedOut, PARSE_OPTIONS);
  ctl('the block carries the same patch entries as the standalone artefact',
    blockValue !== null && isDeepStrictEqual(blockValue, standaloneValue),
    `${blockValue?.length} vs ${standaloneValue.length} entries`);
  const blockJs = blockValue ? collectJsTexts(blockValue) : [];
  const sourceJs = collectJsTexts(standaloneValue);
  ctl('every `!!js` source text survives (count and order)', isDeepStrictEqual(blockJs, sourceJs),
    `${blockJs.length} vs ${sourceJs.length}`);
  const undefinedTags = (bodyText.match(/!!js +undefined\b/g) ?? []).length;
  ctl('no `!!js undefined` anywhere in the block', undefinedTags === 0, `${undefinedTags} found`);

  // ── 2. `--print-block` reproduces the committed region exactly ───────────────────────────────
  console.log('');
  console.log('== 2. `--print-block` reproduces the committed region byte for byte ==');
  const printed = run(['--print-block', '--install-target', target]);
  ctl('--print-block exits 0', printed.status === 0, `exit ${printed.status}`);
  ctl('--print-block output == the committed block body', printed.stdout.trimEnd() === bodyText.trimEnd(),
    `${Buffer.byteLength(printed.stdout, 'utf8')} vs ${Buffer.byteLength(bodyText, 'utf8')} bytes`);

  // ── 3. `--check` passes on the committed pair ────────────────────────────────────────────────
  console.log('');
  console.log('== 3. `--check` on the committed pair ==');
  const checked = run(['--check', '--install-target', target]);
  ctl('`--check` exits 0', checked.status === 0, `exit ${checked.status}`);
  console.log(`    ${checked.stdout.trim().split('\n').slice(-2).join('\n    ')}`);

  // ── 4. a fresh install changes nothing outside the region, and is idempotent ─────────────────
  console.log('');
  console.log('== 4. install into a copy: only the region changes; a second install is a no-op ==');
  const fresh = join(work, 'cordis.patch.yml');
  writeFileSync(fresh, outsideRegion(committedTarget), 'utf8');
  const freshBefore = readFileSync(fresh, 'utf8');
  const install1 = run(['--install', '--install-target', fresh]);
  ctl('the first --install exits 0', install1.status === 0, `exit ${install1.status}`);
  const after1 = readFileSync(fresh, 'utf8');
  ctl('a block was created in the copy', findBlock(after1).begin !== null);
  ctl('everything outside the region is byte-identical (sha256 of the region-stripped file)',
    sha256(outsideRegion(after1)) === sha256(freshBefore),
    `${sha256(outsideRegion(after1)).slice(0, 16)}… vs ${sha256(freshBefore).slice(0, 16)}…`);
  ctl('the installed copy equals the committed file (so the region rule is the real one)',
    sha256(after1) === sha256(committedTarget),
    `${sha256(after1).slice(0, 16)}… vs ${sha256(committedTarget).slice(0, 16)}…`);
  const install2 = run(['--install', '--install-target', fresh]);
  const after2 = readFileSync(fresh, 'utf8');
  ctl('the second --install exits 0 and is a byte-identical no-op', install2.status === 0 && sha256(after2) === sha256(after1),
    `${sha256(after2).slice(0, 16)}…`);
  ctl('the no-op says so rather than silently rewriting',
    /already up to date/.test(install2.stdout + install2.stderr));

  // ── 5. refusals: the file must come out byte-identical ───────────────────────────────────────
  console.log('');
  console.log('== 5. refusals change nothing ==');
  const tamperCases = [
    ['BEGIN without END', (t) => {
      const line = new RegExp(`^.*${esc(found.lines[found.end].trim())}.*\\r?\\n`, 'm');
      return t.replace(line, '');
    }],
    ['END without BEGIN', (t) => {
      const line = new RegExp(`^.*${esc(found.lines[found.begin].trim())}.*\\r?\\n`, 'm');
      return t.replace(line, '');
    }],
    ['the BEGIN marker duplicated', (t) => t.replace(found.lines[found.begin],
      `${found.lines[found.begin]}\n${found.lines[found.begin]}`)],
    ['no final `]` line', (t) => t.replace(/\n\]\s*$/, '\n')],
  ];
  for (const [index, [label, mutate]] of tamperCases.entries()) {
    const file = join(work, `tampered-${index}.yml`);
    const mutated = mutate(committedTarget);
    ctl(`${label}: the tamper actually changed the file`, mutated !== committedTarget);
    writeFileSync(file, mutated, 'utf8');
    const r = run(['--install', '--install-target', file]);
    const after = readFileSync(file, 'utf8');
    ctl(`${label}: --install refuses and the file is byte-identical`,
      r.status !== 0 && after === mutated,
      `exit ${r.status}, ${after === mutated ? 'unchanged' : 'CHANGED'}`);
    const first = (r.stderr.split('\n').find((l) => l.includes('REFUSING')) ?? '').trim();
    if (first) console.log(`      ${first}`);
  }
  const filtered = run(['--install', '--names', 'zabz', '--install-target', join(work, 'filtered.yml')]);
  ctl('--install refuses --names (a filtered block would drop presets from the boot layer)',
    filtered.status === 2, `exit ${filtered.status}`);

  // ── 6. `--check` catches a one-character edit, and the install heals it ──────────────────────
  console.log('');
  console.log('== 6. drift detection: a one-character edit inside the block ==');
  const drift = join(work, 'drift.yml');
  const needle = 'rows=19  order=10';
  const hits = committedTarget.split(needle).length - 1;
  if (hits !== 1) {
    ctl(`the drift needle appears exactly once (found ${hits})`, false, needle);
  } else {
    writeFileSync(drift, committedTarget.replace(needle, 'rows=19  order=11'), 'utf8');
    const r = run(['--check', '--install-target', drift]);
    ctl('--check exits 1 on the edit', r.status !== 0, `exit ${r.status}`);
    ctl('--check names the block as the drifting artefact',
      /DRIFT/.test(r.stderr) && /preset-rows/.test(r.stderr));
    const heal = run(['--install', '--install-target', drift]);
    ctl('--install heals it back to the committed bytes',
      heal.status === 0 && sha256(readFileSync(drift, 'utf8')) === sha256(committedTarget));
    ctl('--check exits 0 again after the heal',
      run(['--check', '--install-target', drift]).status === 0);
  }

  console.log('');
  if (failures.length > 0) {
    console.log(`RESULT: FAIL — ${failures.length} problem(s)`);
    for (const f of failures) console.log(`  - ${f}`);
    return 1;
  }
  console.log(`RESULT: PASS — every checked claim held (work dir ${work})`);
  return 0;
}

process.exit(main());
