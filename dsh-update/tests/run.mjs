#!/usr/bin/env node
/**
 * dsh-update / tests/run.mjs — the detector suite. Node alone: no engine, no network, no install.
 *
 *   node tests/run.mjs                       run every case
 *   node tests/run.mjs --detector <path>     run the cases against a different diff.mjs
 *   node tests/run.mjs --only F-B2           run the cases whose name contains F-B2
 *   node tests/run.mjs --selftest-broken-detector
 *                                            prove this suite is not vacuous: patch a copy of the
 *                                            detector to a plausibly WRONG detector, and assert that
 *                                            F-B2 and F-B3 then FAIL. Exits non-zero unless both are
 *                                            caught. The patched copy is written to the OS temp
 *                                            directory and never to this repository.
 *
 * Every fixture is static JSON under tests/fixtures/, regenerated from this machine's real engine by
 * tests/make-fixtures.mjs. Exits non-zero if any case fails.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const FIX = path.join(HERE, 'fixtures');
const argv = process.argv.slice(2);
const arg = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
const DEFAULT_DETECTOR = path.join(ROOT, 'lib', 'diff.mjs');
const fix = (name) => path.join(FIX, name);

/* ------------------------------------------------------------------ assertions */

function makeAssertions() {
  const results = [];
  const A = {
    ok(cond, label, detail) {
      results.push({ ok: Boolean(cond), label, detail: cond ? undefined : detail });
      return Boolean(cond);
    },
    eq(actual, expected, label) {
      const ok = actual === expected;
      results.push({ ok, label, detail: ok ? undefined : `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}` });
      return ok;
    },
    match(value, re, label) {
      const ok = typeof value === 'string' && re.test(value);
      results.push({ ok, label, detail: ok ? undefined : `${JSON.stringify(String(value).slice(0, 200))} does not match ${re}` });
      return ok;
    },
    result() { return results; },
  };
  return A;
}

function diff(detector, args) {
  const r = spawnSync(process.execPath, [detector, ...args], { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024, cwd: ROOT });
  let json = null;
  try { json = JSON.parse(r.stdout); } catch { /* not JSON: the caller asserts on exit/stderr */ }
  return { status: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '', json };
}

const contract = (name) => ['--baseline-contract', fix('contract-baseline.json'), '--candidate-contract', fix(name), '--consumed', fix('consumed.json')];
const findingsOf = (d, cls) => (d?.findings ?? []).filter((f) => f.class === cls);
const bySeverity = (d, sev) => (d?.findings ?? []).filter((f) => f.severity === sev);
const subjectIs = (f, s) => f.subject === s;

/* ------------------------------------------------------------------ cases */

const CASES = [
  {
    name: 'F-B2 subpath missing (the known-true breakage: list-agents)',
    expect: 'one BREAKS finding, class B2, subject .../list-agents, with the real preset file:line consumers',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      A.eq(r.status, 0, 'diff.mjs exits 0');
      const d = r.json;
      A.ok(d, 'diff.mjs printed JSON');
      if (!d) return A.result();
      const b2 = findingsOf(d, 'B2');
      A.eq(b2.length, 1, 'exactly one B2 finding (the same subpath in three presets is one breakage)');
      const f = b2[0];
      if (!f) return A.result();
      A.eq(f.severity, 'BREAKS', 'B2 severity is BREAKS');
      A.eq(f.subject, '@deepseek-ai/dsh-tool-subagent-control/list-agents', 'B2 subject is the full package/subpath');
      A.eq(f.evidenceTier, 'AUTHORITATIVE', 'B2 rests on AUTHORITATIVE evidence');
      A.match(f.evidence, /exportSubpaths = \["\.", "\.\/package\.json", "\.\/src\/\*"\]/, 'B2 evidence quotes the candidate exportSubpaths array');
      A.match(f.evidence, /"\.\/list-agents" is not among them/, 'B2 evidence states the missing subpath');
      const hasZabz = f.consumers.some((c) => c.file === 'presets/zabz/agent.cordis.yml' && c.line === 338);
      A.ok(hasZabz, 'B2 consumers include presets/zabz/agent.cordis.yml:338', JSON.stringify(f.consumers));
      A.eq(f.consumers.length, 3, 'all three real consumers are attached');
      A.eq(d.verdict, 'BREAKS', 'verdict is BREAKS');
      A.ok(d.counts.BREAKS === 1, 'counts.BREAKS is 1', `got ${d.counts.BREAKS}`);
      return A.result();
    },
  },
  {
    name: 'F-B3 patch target gone — row still exists, patch stopped applying',
    expect: 'BREAKS/B3 for typert-gateway, and the detail names the sub-case (row exists, no attribution)',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate-b3-patch-lost.json')]);
      A.eq(r.status, 0, 'diff.mjs exits 0');
      const d = r.json;
      if (!d) { A.ok(false, 'diff.mjs printed JSON'); return A.result(); }
      const b3 = findingsOf(d, 'B3');
      A.eq(b3.length, 1, 'exactly one row target is reported lost');
      const f = b3[0];
      if (!f) return A.result();
      A.eq(f.severity, 'BREAKS', 'B3 severity is BREAKS');
      A.eq(f.subject, 'typert-gateway', 'B3 subject is the row id');
      A.match(f.evidence, /silently stopped applying/, "B3 evidence says the patch silently stopped applying");
      A.match(f.evidence, /DOES still exist/, 'B3 evidence names the sub-case (the row still exists)');
      A.ok(f.consumers.some((c) => c.file.endsWith('cordis.patch.yml') && c.line === 28), 'B3 consumers point at the real patch line', JSON.stringify(f.consumers));
      A.eq(d.verdict, 'BREAKS', 'verdict is BREAKS');

      // second sub-case: upstream deleted the row entirely
      const r2 = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate-b3-row-deleted.json')]);
      const f2 = findingsOf(r2.json, 'B3')[0];
      A.eq(r2.json?.verdict, 'BREAKS', 'deleted-row variant is also BREAKS');
      A.match(f2?.evidence, /absent from the candidate tree entirely/, 'deleted-row variant names its own sub-case');
      return A.result();
    },
  },
  {
    name: 'F-B4 patch target moved (row id survives, plugin name changed)',
    expect: 'RISKY/B4 quoting both names',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate-b4-moved.json')]);
      A.eq(r.status, 0, 'diff.mjs exits 0');
      const d = r.json;
      if (!d) { A.ok(false, 'diff.mjs printed JSON'); return A.result(); }
      const b4 = findingsOf(d, 'B4');
      A.eq(b4.length, 1, 'exactly one B4 finding');
      const f = b4[0];
      if (!f) return A.result();
      A.eq(f.severity, 'RISKY', 'B4 severity is RISKY');
      A.eq(f.subject, 'typert-gateway', 'B4 subject is the row id');
      A.match(f.evidence, /"@deepseek-ai\/dsh-api-gateway"/, 'B4 evidence quotes the baseline name');
      A.match(f.evidence, /"@deepseek-ai\/dsh-api-gateway-legacy"/, 'B4 evidence quotes the candidate name');
      A.ok(!findingsOf(d, 'B3').length, 'B4 does not also report B3 (the patch still applies)', JSON.stringify(findingsOf(d, 'B3')));
      return A.result();
    },
  },
  {
    name: 'F-B10 capability gain never worsens the verdict',
    expect: 'verdict SAFE, no BREAKS and no RISKY, CAPABILITY for the extra package and the extra row id',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate-clean.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      A.eq(r.status, 0, 'diff.mjs exits 0');
      const d = r.json;
      if (!d) { A.ok(false, 'diff.mjs printed JSON'); return A.result(); }
      A.eq(d.verdict, 'SAFE', 'verdict is SAFE');
      A.eq(d.counts.BREAKS, 0, 'no BREAKS');
      A.eq(d.counts.RISKY, 0, 'no RISKY');
      A.ok(d.counts.CAPABILITY >= 3, 'at least three capability gains are reported', `got ${d.counts.CAPABILITY}`);
      const pkg = bySeverity(d, 'CAPABILITY').find((f) => subjectIs(f, '@deepseek-ai/dsh-tool-browser'));
      A.ok(pkg, 'the added package is reported as a CAPABILITY', JSON.stringify(bySeverity(d, 'CAPABILITY').map((f) => f.subject)));
      A.match(pkg?.evidence, /absent from 0\.1\.5-rc\.1/, 'the capability evidence names the baseline it is absent from');
      const rows = bySeverity(d, 'CAPABILITY').find((f) => subjectIs(f, 'tree.rowIds'));
      A.ok(rows, 'the added row id is reported as a CAPABILITY');
      A.match(rows?.evidence, /capability-probe-row/, 'the added row id is named');
      A.ok(d.consumed.unverified.length > 0, 'the honest gap list is populated even though the verdict is SAFE');
      return A.result();
    },
  },
  {
    name: 'F-advisory-downgrade BREAKS may not rest on regex-derived evidence',
    expect: 'the same comparison that was BREAKS becomes RISKY and says it was downgraded',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate-advisory.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      A.eq(r.status, 0, 'diff.mjs exits 0');
      const d = r.json;
      if (!d) { A.ok(false, 'diff.mjs printed JSON'); return A.result(); }
      A.eq(bySeverity(d, 'BREAKS').length, 0, 'no finding is BREAKS', JSON.stringify(bySeverity(d, 'BREAKS').map((f) => `${f.class} ${f.subject}`)));
      const b2 = findingsOf(d, 'B2')[0];
      A.ok(b2, 'the B2 comparison is still reported');
      A.eq(b2?.severity, 'RISKY', 'the ADVISORY-backed B2 is RISKY');
      A.eq(b2?.downgradedFrom, 'BREAKS', 'the finding records that it was downgraded from BREAKS');
      A.match(b2?.evidence, /DOWNGRADED BREAKS->RISKY/, 'the evidence explains the downgrade');
      A.eq(d.verdict, 'RISKY', 'verdict is RISKY, not BREAKS');
      A.ok(d.notes.some((n) => /downgraded to RISKY/.test(n)), 'the artifact notes that a downgrade happened');
      return A.result();
    },
  },
  {
    name: 'F-determinism byte-identical output for the same inputs',
    expect: 'two runs with a pinned generatedAt are byte-identical; unpinned runs differ only in generatedAt',
    run: (det) => {
      const A = makeAssertions();
      const args = [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')];
      const env = { ...process.env, SOURCE_DATE_EPOCH: '1780000000' };
      const run2 = () => spawnSync(process.execPath, [det, ...args], { encoding: 'utf8', cwd: ROOT, env, maxBuffer: 256 * 1024 * 1024 });
      const a = run2();
      const b = run2();
      A.eq(a.status, 0, 'first pinned run exits 0');
      A.ok(a.stdout.length > 1000, 'the artifact is non-trivial');
      A.ok(a.stdout === b.stdout, 'pinned runs are byte-identical', `sizes ${a.stdout.length} vs ${b.stdout.length}`);
      A.match(a.stdout, /"generatedAt": "2026-05-28T/, 'the pinned timestamp is honoured');
      const c = diff(det, args);
      const e = diff(det, args);
      const strip = (s) => s.replace(/"generatedAt": "[^"]*"/, '"generatedAt": "<pinned>"');
      A.ok(strip(c.stdout) === strip(e.stdout), 'unpinned runs are identical once the timestamp is normalised');
      return A.result();
    },
  },
  {
    name: 'F-missing-input a nonexistent file fails loudly',
    expect: 'non-zero exit and a diagnostic that names the file',
    run: (det) => {
      const A = makeAssertions();
      const missing = path.join(FIX, 'no-such-contract.json');
      const r = diff(det, ['--baseline-contract', missing, '--candidate-contract', fix('contract-candidate.json'), '--consumed', fix('consumed.json')]);
      A.ok(r.status !== 0, 'exit code is non-zero', `got ${r.status}`);
      A.match(r.stderr, /cannot read/, 'stderr says it could not read the file');
      A.ok(r.stderr.includes('no-such-contract.json'), 'stderr names the file', r.stderr.slice(0, 200));
      A.ok(!r.stdout.includes('"verdict"'), 'no artifact is printed on failure');
      const r2 = diff(det, []);
      A.ok(r2.status !== 0, 'missing required arguments is non-zero too');
      A.match(r2.stderr, /missing required --baseline-contract/, 'and says which argument is missing');
      const r3 = diff(det, ['--help']);
      A.eq(r3.status, 0, '--help exits 0');
      A.match(r3.stdout, /usage: node lib\/diff\.mjs/, '--help prints usage');
      return A.result();
    },
  },
  {
    name: 'F-failed-tree a failed read never looks like health',
    expect: 'a tree with rows:[] and a failure field produces a BREAKS signal and no clean verdict, and patch targets are reported unchecked',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-failed.json')]);
      A.eq(r.status, 0, 'diff.mjs exits 0 (the failure is data, not a crash)');
      const d = r.json;
      if (!d) { A.ok(false, 'diff.mjs printed JSON'); return A.result(); }
      A.ok(d.verdict !== 'SAFE', 'verdict is not SAFE', d.verdict);
      const tree = findingsOf(d, 'TREE');
      A.eq(tree.length, 1, 'exactly one TREE finding');
      A.eq(tree[0]?.severity, 'BREAKS', 'a dump that exited 1 is a BREAKS signal (authoritative: an exit code)');
      A.match(tree[0]?.evidence, /exitCode 1/, 'the evidence carries the exit code');
      A.ok(!findingsOf(d, 'B3').length, 'B3 does not claim the patch applied');
      const gaps = (d.consumed.unverified ?? []).filter((u) => u.kind === 'patch-row-target');
      A.eq(gaps.length, 4, 'all four patch targets are listed as unchecked rather than passed');
      A.match(gaps[0]?.reason, /did not compose cleanly/, 'the gap reason explains why');
      return A.result();
    },
  },
  {
    name: 'F-B1 package missing',
    expect: 'BREAKS/B1 when the package is gone from the candidate contract',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate-b1.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      const b1 = findingsOf(r.json, 'B1');
      const f = b1.find((x) => subjectIs(x, '@deepseek-ai/dsh-tool-subagent-control'));
      A.ok(f, 'B1 reported for the removed package', JSON.stringify(b1.map((x) => x.subject)));
      A.eq(f?.severity, 'BREAKS', 'B1 severity is BREAKS');
      A.match(f?.evidence, /ABSENT/, 'B1 evidence shows the candidate has no such package');
      A.eq(r.json?.verdict, 'BREAKS', 'verdict is BREAKS');
      return A.result();
    },
  },
  {
    name: 'F-B5 bundle missing',
    expect: 'BREAKS/B5 when a profile bundle is gone from the candidate contract',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate-b5.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      const b5 = findingsOf(r.json, 'B5');
      const f = b5.find((x) => subjectIs(x, '@deepseek-ai/dsh-web-app'));
      A.ok(f, 'B5 reported for the removed bundle', JSON.stringify(b5.map((x) => x.subject)));
      A.eq(f?.severity, 'BREAKS', 'B5 severity is BREAKS');
      A.ok(f?.consumers.some((c) => c.file.endsWith('profiles\\web\\package.json')), 'B5 consumers point at the profile package.json', JSON.stringify(f?.consumers));
      A.eq(r.json?.verdict, 'BREAKS', 'verdict is BREAKS');
      // and: a missing bundle must not be reported twice (once as B1, once as B5)
      A.ok(!findingsOf(r.json, 'B1').some((x) => subjectIs(x, '@deepseek-ai/dsh-web-app')), 'the same missing bundle is not double-counted as B1');
      return A.result();
    },
  },
  {
    name: 'F-B8 API drift is ADVISORY and never BREAKS',
    expect: 'RISKY/B8 with the regex-extraction limitation stated in its own evidence',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate-b8.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      const b8 = findingsOf(r.json, 'B8');
      const f = b8.find((x) => x.subject.startsWith('@deepseek-ai/cordis'));
      A.ok(f, 'B8 reported for the dropped symbol', JSON.stringify(b8.map((x) => x.subject)));
      A.eq(f?.severity, 'RISKY', 'B8 severity is RISKY');
      A.eq(f?.evidenceTier, 'ADVISORY', 'B8 evidence tier is ADVISORY');
      A.match(f?.evidence, /LIMITATION/, 'B8 states its extraction limitation');
      A.ok(!bySeverity(r.json, 'BREAKS').some((x) => x.class === 'B8'), 'no B8 finding is BREAKS');
      A.ok((r.json.consumed.unverified ?? []).some((u) => u.kind === 'plugin-import'), 'plugin imports are listed in Not checked');
      return A.result();
    },
  },
  {
    name: 'F-local-packages a local dsh-plugin-* name is never a breakage',
    expect: 'INFO plus an unverified entry, never BREAKS, for our own packages',
    run: (det) => {
      const A = makeAssertions();
      const r = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json')]);
      const local = bySeverity(r.json, 'BREAKS').filter((f) => f.subject.startsWith('dsh-plugin-'));
      A.eq(local.length, 0, 'no local package is reported as a breakage', JSON.stringify(local.map((f) => f.subject)));
      const costRef = (r.json.consumed.unverified ?? []).filter((u) => u.ref === 'dsh-plugin-cost');
      A.eq(costRef.length, 2, 'the local package lands in the gap list for both of its roles', JSON.stringify(costRef.map((u) => u.kind)));
      A.match(costRef[0]?.reason, /verify gate G3/, 'the gap reason says which gate really checks it');
      return A.result();
    },
  },
  {
    name: 'F-report the markdown renders every section, including Not checked',
    expect: 'report.mjs prints the verdict line, the counts table, BREAKS in full and a Not checked section',
    run: (det) => {
      const A = makeAssertions();
      const diffFile = path.join(os.tmpdir(), `dsh-update-test-${process.pid}.diff.json`);
      const r = diff(det, [...contract('contract-candidate.json'), '--baseline-tree', fix('tree-baseline.json'), '--candidate-tree', fix('tree-candidate.json'), '--out', diffFile]);
      A.eq(r.status, 0, 'diff.mjs exits 0');
      const rep = spawnSync(process.execPath, [path.join(ROOT, 'lib', 'report.mjs'), '--diff', diffFile], { encoding: 'utf8', cwd: ROOT });
      A.eq(rep.status, 0, 'report.mjs exits 0');
      const md = rep.stdout ?? '';
      A.match(md, /^# dsh-update: 0\.1\.5-rc\.1 → 0\.1\.7-rc\.1 — BREAKS/, 'one-line verdict with the version pair');
      A.match(md, /\| severity \| count \|/, 'counts table present');
      A.match(md, /## BREAKS \(1\)/, 'BREAKS section present');
      A.match(md, /- \*\*Where we depend on it:\*\* presets\/cordis-bg\/agent\.cordis\.yml:231/, 'BREAKS names a real file:line');
      A.match(md, /## RISKY \(3\)/, 'RISKY section present');
      A.match(md, /## CAPABILITY gains \(2\)/, 'capability section present');
      A.match(md, /## Not checked/, 'Not checked section is present');
      A.match(md, /`spend-guard\.ceilingUsd`/, 'Not checked lists the unresolved settings key verbatim');
      // and with everything resolved it must still print the section
      const emptyPath = path.join(os.tmpdir(), `dsh-update-test-empty-${process.pid}.json`);
      fs.writeFileSync(emptyPath, JSON.stringify({ schemaVersion: 1, verdict: 'SAFE', counts: {}, baseline: { version: 'a' }, candidate: { version: 'b' }, findings: [], consumed: { packagesChecked: 0, unverified: [] } }));
      const rep2 = spawnSync(process.execPath, [path.join(ROOT, 'lib', 'report.mjs'), '--diff', emptyPath], { encoding: 'utf8', cwd: ROOT });
      A.eq(rep2.status, 0, 'report.mjs exits 0 on an empty diff');
      A.match(rep2.stdout, /## Not checked\n\nnothing\./, 'an empty gap list renders as "nothing" rather than being omitted');
      const bad = spawnSync(process.execPath, [path.join(ROOT, 'lib', 'report.mjs'), '--diff', path.join(FIX, 'nope.json')], { encoding: 'utf8', cwd: ROOT });
      A.ok(bad.status !== 0, 'report.mjs exits non-zero on a missing file');
      A.match(bad.stderr, /cannot read/, 'report.mjs says so on stderr');
      return A.result();
    },
  },
];

/* ------------------------------------------------------------------ runner */

function runCases(detector, filter) {
  const chosen = CASES.filter((c) => !filter || c.name.includes(filter));
  let failed = 0;
  for (const c of chosen) {
    const t0 = Date.now();
    let assertions;
    try {
      assertions = c.run(detector);
    } catch (err) {
      assertions = [{ ok: false, label: 'the case threw', detail: err?.stack ?? String(err) }];
    }
    const bad = assertions.filter((a) => !a.ok);
    const ms = Date.now() - t0;
    if (bad.length === 0) {
      console.log(`PASS  ${c.name}  [${assertions.length} assertions, ${ms} ms]`);
      console.log(`      expects: ${c.expect}`);
    } else {
      failed += 1;
      console.log(`FAIL  ${c.name}  [${assertions.length - bad.length}/${assertions.length} assertions, ${ms} ms]`);
      console.log(`      expects: ${c.expect}`);
      for (const a of bad) console.log(`      ✗ ${a.label}${a.detail ? ` — ${a.detail}` : ''}`);
    }
  }
  return { failed, total: chosen.length };
}

/* ------------------------------------------------------------------ broken-detector self-test */

/**
 * A green suite proves nothing unless it can go red. This applies two plausible BUGS to a copy of the
 * detector — "a dropped subpath is informational" and "the patch-target check is not there" — and
 * asserts F-B2 and F-B3 fail against it. The patched copy goes to the OS temp directory.
 */
function selftestBrokenDetector() {
  const original = fs.readFileSync(DEFAULT_DETECTOR, 'utf8');
  const inversions = [
    { what: 'B2 reports a dropped subpath as INFO instead of BREAKS', from: "      class: 'B2',\n      severity: 'BREAKS',", to: "      class: 'B2',\n      severity: 'INFO'," },
    { what: 'the B3 patch-applied check is not reached (every target looks patched)', from: '    if (candidateTree.patchedRowIds.includes(id)) {', to: '    if (true) {' },
  ];
  let broken = original;
  const applied = [];
  for (const inv of inversions) {
    if (!broken.includes(inv.from)) {
      console.log(`SELFTEST ERROR  cannot apply the inversion "${inv.what}": the anchor is not in ${DEFAULT_DETECTOR}`);
      console.log('                (the detector changed shape — update tests/run.mjs so the self-test stays real)');
      return 1;
    }
    broken = broken.replace(inv.from, inv.to);
    applied.push(inv.what);
  }
  if (broken === original) { console.log('SELFTEST ERROR  the inversion produced no change'); return 1; }
  const brokenPath = path.join(os.tmpdir(), `dsh-update-broken-detector-${process.pid}.mjs`);
  fs.writeFileSync(brokenPath, broken);
  console.log(`== deliberate detector break: ${applied.length} inversions applied to a copy of the detector`);
  for (const what of applied) console.log(`   - ${what}`);
  console.log(`   copy: ${brokenPath}`);
  console.log('');
  const { failed, total } = runCases(brokenPath, undefined);
  const caughtFails = [];
  if (failed < 2) caughtFails.push(`only ${failed}/${total} case(s) went red — the suite cannot distinguish a stub from a working detector`);
  if (failed >= 2) {
    console.log('');
    console.log(`== result: the broken detector turned ${failed}/${total} cases red, which is what makes the green run evidence.`);
    return 0;
  }
  console.log('');
  for (const m of caughtFails) console.log(`== SELFTEST FAILED: ${m}`);
  return 1;
}

/* ------------------------------------------------------------------ main */

function main() {
  const mode = argv.includes('--selftest-broken-detector');
  const detector = arg('--detector') ?? DEFAULT_DETECTOR;
  const only = arg('--only');
  if (!fs.existsSync(detector)) {
    console.error(`run.mjs: detector "${detector}" does not exist`);
    return 2;
  }
  if (!fs.existsSync(FIX)) {
    console.error(`run.mjs: no fixtures at ${FIX} — run \`node tests/make-fixtures.mjs\` first`);
    return 2;
  }
  console.log(`dsh-update detector suite — detector: ${detector}`);
  console.log(`fixtures: ${FIX}`);
  console.log('');
  if (mode) return selftestBrokenDetector();
  const { failed, total } = runCases(detector, only);
  console.log('');
  if (failed === 0) {
    console.log(`${total}/${total} cases passed (${CASES.length} cases defined) — exit 0`);
    return 0;
  }
  console.log(`${failed}/${total} cases FAILED — exit 1`);
  return 1;
}

process.exitCode = main();
