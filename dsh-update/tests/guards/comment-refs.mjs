#!/usr/bin/env node
/**
 * tests/guards/comment-refs.mjs — the guard for the 2026-09-28 comment defect in lib/consumed.mjs.
 *
 * WHAT HAPPENED, AND WHY THIS FILE EXISTS. `consumed.mjs` matched package names against the whole
 * text of a file, comments included. `harness-config/scripts/make-preset-rows.mjs` holds a generated
 * YAML `#` comment header in JavaScript string literals; line 309 of it named
 * `@deepseek-ai/dsh-agent-presets` and `@deepseek-ai/dsh-agent-preset-registry` inside that prose.
 * The module reported both as consumed by a `kind: "script"` line, `diff.mjs` found that
 * `-presets` is ABSENT from the 0.1.7-rc.2 candidate, and the pipeline's verdict became
 *
 *     F001 [B1] BREAKS @deepseek-ai/dsh-agent-presets   evidenceTier=AUTHORITATIVE
 *
 * which is false, and a false BREAKS is the worst possible output of this pipeline: it refuses a
 * valid upgrade at the tier the SPEC says may only rest on authoritative evidence.
 *
 * WHAT THIS GUARD PROVES, both directions:
 *   1. every name that appears ONLY in a comment is absent from `packageRefs`, AND the name really
 *      is present in the fixture's raw bytes (so its absence is suppression, not a typo);
 *   2. every name that appears in real code or in a string literal IS reported, at its real line,
 *      with the right `kind` — a fix that suppressed real findings would be worse than the bug.
 *
 * HOW IT RUNS. It spawns the real module (`lib/consumed.mjs`) as a subprocess against the fixture
 * tree in `fixtures/comment-refs/`; it never imports it, because `consumed.mjs` is a script whose
 * top-level code scans and exits. The fixture is under `dsh-update/tests/`, which is inside NONE of
 * the module's scan roots, so it cannot contaminate the real inventory.
 *
 *   node dsh-update/tests/guards/comment-refs.mjs        # exit 0 = pass, 1 = the defect is back
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LIB = path.resolve(HERE, '..', '..', 'lib', 'consumed.mjs');
const FIXTURE = path.join(HERE, 'fixtures', 'comment-refs');

/** `file:line:name:subpath:kind` for every reference this fixture MUST produce, exactly. */
const EXPECTED = [
  'multi-window/comment-shapes.html:12:@deepseek-ai/dsh-fixture-html-literal:.:script',
  'multi-window/ts-comments.ts:15:@deepseek-ai/dsh-fixture-ts-string:.:script',
  'scripts/comment-shapes.mjs:14:@deepseek-ai/dsh-fixture-real-string:.:script',
  'scripts/comment-shapes.mjs:15:@deepseek-ai/dsh-fixture-real-rowname:.:script',
  'scripts/comment-shapes.mjs:16:dsh-plugin-fixture-real-own:.:own-plugin',
  'scripts/comment-shapes.mjs:31:@deepseek-ai/dsh-fixture-prose-no-hash:.:script',
  'scripts/comment-shapes.mjs:36:@deepseek-ai/dsh-fixture-url-string:.:script',
  'scripts/ps-comments.ps1:8:@deepseek-ai/dsh-fixture-ps-string:.:script',
  'scripts/ps-comments.ps1:9:dsh-plugin-fixture-ps-own:.:own-plugin',
  'scripts/ps-comments.ps1:10:@deepseek-ai/dsh-fixture-ps-hash-in-string:.:script',
  'scripts/py-comments.py:9:@deepseek-ai/dsh-fixture-py-string:.:script',
  'scripts/py-comments.py:10:dsh-plugin-fixture-py-own:.:own-plugin',
  'scripts/py-comments.py:11:@deepseek-ai/dsh-fixture-py-hash-in-string:.:script',
  'scripts/sh-comments.sh:5:@deepseek-ai/dsh-fixture-sh-string:.:script',
  'scripts/sh-comments.sh:6:dsh-plugin-fixture-sh-own:.:own-plugin',
  'scripts/sh-comments.sh:7:@deepseek-ai/dsh-fixture-sh-hash-in-string:.:script',
];

/**
 * Names that live ONLY inside a comment or a `#`-prefixed string literal. Every one of them must be
 * present in the fixture's raw text and absent from `packageRefs`. The list is grouped by the rule
 * that suppresses it, so a failure says which rule broke.
 */
const MUST_NOT_BE_REPORTED = [
  // JS `//` line comment, `/* … */` block comment, and a trailing comment after real code
  '@deepseek-ai/dsh-fixture-comment-line',
  '@deepseek-ai/dsh-fixture-comment-block',
  '@deepseek-ai/dsh-fixture-comment-trailing',
  // THE MEASURED DEFECT: a generator's YAML `#` header held in single-, double- and backtick strings
  '@deepseek-ai/dsh-fixture-generated-prose-ref',
  '@deepseek-ai/dsh-fixture-generated-prose-dq',
  '@deepseek-ai/dsh-fixture-generated-prose-tpl',
  // our own plugin names go through the same blanking
  'dsh-plugin-fixture-comment-only',
  // Python `#`, a trailing Python comment, and a triple-quoted docstring
  '@deepseek-ai/dsh-fixture-py-comment',
  '@deepseek-ai/dsh-fixture-py-trailing',
  '@deepseek-ai/dsh-fixture-py-docstring',
  // shell `#` and a trailing one
  '@deepseek-ai/dsh-fixture-sh-comment',
  '@deepseek-ai/dsh-fixture-sh-trailing',
  // PowerShell `#`, a `<# … #>` block, and a trailing comment
  '@deepseek-ai/dsh-fixture-ps-comment',
  '@deepseek-ai/dsh-fixture-ps-block',
  '@deepseek-ai/dsh-fixture-ps-trailing',
  // HTML `<!-- … -->` — only for the file family that uses it
  '@deepseek-ai/dsh-fixture-html-comment',
  // the `.ts` arm of the JS family
  '@deepseek-ai/dsh-fixture-ts-comment',
  '@deepseek-ai/dsh-fixture-ts-block',
  '@deepseek-ai/dsh-fixture-ts-prose',
  '@deepseek-ai/dsh-fixture-ts-trailing',
];

/** Every file under the fixture, so "it was there in the raw bytes" is a real reading. */
function walk(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else acc.push(p);
  }
  return acc;
}

const failures = [];
const check = (ok, label, detail) => {
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}\n`);
};

if (!fs.existsSync(LIB)) {
  process.stdout.write(`FAIL  ${LIB} does not exist\n`);
  process.exit(1);
}

const out = path.join(os.tmpdir(), `dsh-guard-comment-refs-${process.pid}.json`);
const run = spawnSync(process.execPath, [
  LIB, '--root', FIXTURE, '--dsh-home', FIXTURE, '--out', out,
], { encoding: 'utf8', timeout: 120000, maxBuffer: 64 * 1024 * 1024 });

check(run.status === 0, 'consumed.mjs exits 0 against the fixture', `exit ${run.status}; stderr: ${(run.stderr || '').trim().slice(0, 400)}`);
if (run.status !== 0) process.exit(1);

let artifact;
try {
  artifact = JSON.parse(fs.readFileSync(out, 'utf8'));
} catch (err) {
  check(false, 'the artifact parses as JSON', err.message);
  process.exit(1);
}
check(true, 'the artifact parses as JSON', `${fs.statSync(out).size} bytes`);

const refs = Array.isArray(artifact.packageRefs) ? artifact.packageRefs : [];
const keyOf = (r) => `${r.file}:${r.line}:${r.name}:${r.subpath}:${r.kind}`;
const actual = refs.map(keyOf).sort();
const names = refs.map((r) => r.name);

/* ---- direction 1: comments are not references ------------------------------------------------- */
const rawText = walk(FIXTURE)
  .map((p) => fs.readFileSync(p, 'utf8'))
  .join('\n');
for (const name of MUST_NOT_BE_REPORTED) {
  const inRaw = rawText.includes(name);
  const reported = names.includes(name);
  const where = refs.filter((r) => r.name === name).map((r) => `${r.file}:${r.line}`).join(', ');
  check(inRaw, `fixture really contains ${name} in its raw bytes`, inRaw ? undefined : 'the fixture no longer exercises this rule');
  check(!reported, `${name} was suppressed as a comment`, reported ? `still reported at ${where}` : undefined);
}

/* ---- direction 2: real references are still found, at their real lines ------------------------ */
check(JSON.stringify(actual) === JSON.stringify([...EXPECTED].sort()),
  `the fixture produces exactly ${EXPECTED.length} reference(s), at their real lines`,
  JSON.stringify(actual) === JSON.stringify([...EXPECTED].sort()) ? undefined
    : `missing: ${EXPECTED.filter((e) => !actual.includes(e)).join(' | ') || '(none)'} ; unexpected: ${actual.filter((a) => !EXPECTED.includes(a)).join(' | ') || '(none)'}`);

/**
 * The two entries deliberately KEPT are the documented limits of the heuristic, asserted here so a
 * later "improvement" cannot quietly change the rule without changing this guard too:
 *   * prose inside a string that does NOT begin with `#` is content, not a comment;
 *   * a `//` inside a string literal is not a comment, because `//` is only a comment outside one.
 */
for (const kept of ['@deepseek-ai/dsh-fixture-prose-no-hash', '@deepseek-ai/dsh-fixture-url-string']) {
  check(names.includes(kept), `${kept} is KEPT (a documented limit, not a bug)`,
    names.includes(kept) ? undefined : 'no longer reported — the rule changed; update this guard and its note');
}

process.stdout.write(`\n${failures.length === 0 ? 'PASS' : `FAIL (${failures.length})`} — tests/guards/comment-refs.mjs\n`);
process.exit(failures.length === 0 ? 0 : 1);
