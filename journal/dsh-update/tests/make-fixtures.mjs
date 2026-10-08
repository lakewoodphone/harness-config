#!/usr/bin/env node
/**
 * dsh-update / tests/make-fixtures.mjs — REGENERATOR for tests/fixtures/**.
 *
 *   node tests/make-fixtures.mjs [--dump <path to a real --dump-config capture>]
 *                               [--prefix <installRoot>] [--out tests/fixtures]
 *
 * tests/run.mjs never runs this: it reads the static JSON in tests/fixtures/, so the suite needs no
 * engine and no network. This script exists so the fixtures are provably CUT FROM THE REAL SHAPES
 * rather than invented, and can be regenerated after a DSH upgrade:
 *
 *   * trees come from a real `--dump-config` capture (163 rows, parsed with the same line parser
 *     verify.mjs uses, so attribution comments are preserved);
 *   * contract package entries come from the REAL package.json of each named package in the engine
 *     install (`version`, `exports` -> `exportSubpaths`, `dsh`, `dependencies`), and `symbols` are
 *     extracted by regex from the real built JavaScript — deliberately the ADVISORY tier;
 *   * consumed.json points at files and lines that really exist in this deployment.
 *
 * Every deviation from the real data is an explicit named delta applied below, and each delta says
 * which test case needs it.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';
import { parseDump } from '../lib/verify.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const DUMP_PATH = arg('--dump', path.join(process.env.TEMP ?? '/tmp', 'dsh-dump-probe.json'));
const PREFIX = arg('--prefix', path.join(process.env.LOCALAPPDATA ?? '', 'npm-cache', '_npx', '1e7f6d9597241db0'));
const OUT = path.resolve(arg('--out', path.join(HERE, 'fixtures')));
const INSTALL = path.join(PREFIX, 'node_modules');

const BASELINE_VERSION = '0.1.5-rc.1';
const CANDIDATE_VERSION = '0.1.7-rc.1';

/* the packages this deployment names, or whose api it consumes; all real, all installed */
const PACKAGES = [
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh',
  '@deepseek-ai/dsh-agent',
  '@deepseek-ai/dsh-agent-presets',
  '@deepseek-ai/dsh-api-gateway',
  '@deepseek-ai/dsh-base',
  '@deepseek-ai/dsh-client-connection',
  '@deepseek-ai/dsh-headless',
  '@deepseek-ai/dsh-llm',
  '@deepseek-ai/dsh-llm-deepseek',
  '@deepseek-ai/dsh-llm-pi-ai',
  '@deepseek-ai/dsh-session',
  '@deepseek-ai/dsh-settings-file',
  '@deepseek-ai/dsh-tool-subagent',
  '@deepseek-ai/dsh-tool-subagent-control',
  '@deepseek-ai/dsh-tools',
  '@deepseek-ai/dsh-web-app',
  '@deepseek-ai/dsh-workflow',
];

const SYMBOL_RE = /export\s+(?:default\s+)?(?:async\s+)?(?:class|function|const|let|var)\s+([A-Za-z_$][\w$]*)|export\s*\{([^}]*)\}/g;

function symbolsOf(pkgDir) {
  const found = new Set();
  const entry = path.join(pkgDir, 'lib', 'index.js');
  const files = fs.existsSync(entry) ? [entry] : [];
  for (const f of files) {
    let text = '';
    try { text = fs.readFileSync(f, 'utf8'); } catch { continue; }
    let m;
    SYMBOL_RE.lastIndex = 0;
    while ((m = SYMBOL_RE.exec(text)) !== null) {
      if (m[1]) found.add(m[1]);
      if (m[2]) for (const part of m[2].split(',')) {
        const name = part.trim().split(/\s+as\s+/)[0].trim();
        if (/^[A-Za-z_$][\w$]*$/.test(name)) found.add(name);
      }
    }
  }
  return [...found].sort();
}

function exportSubpathsOf(exportsRaw) {
  if (exportsRaw === undefined || exportsRaw === null) return ['.'];
  if (typeof exportsRaw === 'string') return ['.'];
  return Object.keys(exportsRaw).sort();
}

function contractEntry(name) {
  const dir = path.join(INSTALL, name);
  const pj = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  const exportsRaw = pj.exports ?? {};
  return [name, {
    version: pj.version,
    dir: path.relative(INSTALL, dir).split(path.sep).join('/'),
    present: true,
    exportSubpaths: exportSubpathsOf(exportsRaw),
    exportsRaw,
    dsh: pj.dsh ?? {},
    dependencies: pj.dependencies ?? {},
    peerDependencies: pj.peerDependencies ?? {},
    provenance: {
      manifest: 'AUTHORITATIVE',
      exportSubpaths: 'AUTHORITATIVE',
      settingsKeys: 'ADVISORY',
      serviceNames: 'ADVISORY',
      toolNames: 'ADVISORY',
      symbols: 'ADVISORY',
    },
    settingsKeys: [],
    serviceNames: [],
    toolNames: [],
    symbols: symbolsOf(dir),
  }];
}

function contractFor(version, mutate) {
  const packages = {};
  for (const name of PACKAGES) {
    const [k, v] = contractEntry(name);
    packages[k] = v;
  }
  const dsh = packages['@deepseek-ai/dsh'];
  const contract = {
    schemaVersion: 1,
    generatedAt: '2026-09-23T20:00:00.000Z',
    host: 'ZABZ-TECH',
    installRoot: PREFIX,
    dsh: {
      name: '@deepseek-ai/dsh',
      version,
      bin: dsh.exportsRaw?.bin ?? { dsh: 'lib/bin.js' },
      exports: dsh.exportsRaw,
      exportSubpaths: dsh.exportSubpaths,
      repository: 'git+https://github.com/deepseek-ai/deepseek-harness.git',
      dsh: dsh.dsh,
      dependencies: dsh.dependencies,
    },
    packages,
    packageCount: Object.keys(packages).length,
    notes: [],
  };
  mutate?.(contract);
  return contract;
}

function treeFromDump(version, mutate) {
  const parsed = parseDump(fs.readFileSync(DUMP_PATH, 'utf8'));
  const tree = {
    schemaVersion: 1,
    generatedAt: '2026-09-23T20:00:00.000Z',
    enginePath: path.join(INSTALL, '@deepseek-ai', 'dsh', 'lib', 'bin.js'),
    engineVersion: version,
    dshHome: 'C:\\Users\\ezabz\\.dsh',
    profile: 'web',
    isolatedHome: null,
    invocation: 'node <bin.js> --profile web --dump-config',
    exitCode: 0,
    durationMs: 180,
    stderr: '',
    rows: parsed.rows,
    rowIds: parsed.rowIds,
    names: [...new Set(parsed.names)],
    layerComments: [...new Set(parsed.layerComments)],
    patchedRowIds: parsed.patchedRowIds,
    disabledRowIds: parsed.rows.filter((r) => r.disabled).map((r) => r.id),
    notes: [],
  };
  mutate?.(tree);
  return tree;
}

const write = (name, value) => {
  const file = path.join(OUT, name);
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
  return `${name} (${fs.statSync(file).size} bytes)`;
};

fs.mkdirSync(path.join(OUT, 'raw'), { recursive: true });

/* the real capture, kept beside the fixtures so the shapes are auditable */
fs.copyFileSync(DUMP_PATH, path.join(OUT, 'raw', 'dump-config-web-0.1.5-rc.1.txt'));

const cordisSymbols = contractEntry('@deepseek-ai/cordis')[1].symbols;
const subagentSymbols = contractEntry('@deepseek-ai/dsh-tool-subagent')[1].symbols;
const consumedSymbol = cordisSymbols.includes('Context') ? 'Context' : cordisSymbols[0];
const consumedSubagentSymbol = subagentSymbols[0];

/* ------------------------------------------------------------------ consumed.json (real paths/lines) */

const consumed = {
  schemaVersion: 1,
  generatedAt: '2026-09-23T20:00:00.000Z',
  configRoot: 'C:\\Users\\ezabz\\Code\\harness-config',
  dshHome: 'C:\\Users\\ezabz\\.dsh',
  profileBundles: [
    { name: '@deepseek-ai/dsh-base', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 9 },
    { name: '@deepseek-ai/dsh-web-app', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 10 },
    { name: 'dsh-plugin-attention', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 11 },
    { name: 'dsh-plugin-attention-badge', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 12 },
    { name: 'dsh-plugin-cost', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 13 },
    { name: 'dsh-plugin-mobile', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 14 },
    { name: 'dsh-plugin-windows', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 15 },
    { name: 'dsh-plugin-health', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 16 },
    { name: 'dsh-plugin-mesh-http', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 17 },
    { name: 'dsh-plugin-remote-fanout', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 18 },
    { name: 'dsh-plugin-session-link', source: 'profile', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\package.json', line: 19 },
  ],
  packageRefs: [
    { name: '@deepseek-ai/dsh-tool-subagent-control', subpath: '.', kind: 'preset-row', file: 'presets/zabz/agent.cordis.yml', line: 304 },
    { name: '@deepseek-ai/dsh-tool-subagent-control/list-agents', subpath: './list-agents', kind: 'preset-row', file: 'presets/zabz/agent.cordis.yml', line: 338 },
    { name: '@deepseek-ai/dsh-tool-subagent-control/list-agents', subpath: './list-agents', kind: 'preset-row', file: 'presets/cordis-bg/agent.cordis.yml', line: 231 },
    { name: '@deepseek-ai/dsh-tool-subagent-control/list-agents', subpath: './list-agents', kind: 'preset-row', file: 'presets/yocheved/agent.cordis.yml', line: 326 },
    { name: '@deepseek-ai/dsh-tool-subagent', subpath: '.', kind: 'preset-row', file: 'presets/zabz/agent.cordis.yml', line: 372 },
    { name: 'dsh-plugin-cost', subpath: './guard', kind: 'preset-row', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\node_modules\\dsh-plugin-cost\\cordis.patch.yml', line: 3 },
  ],
  rowIds: [
    { id: 'tool-subagent-list-agents', file: 'presets/zabz/agent.cordis.yml', line: 337, where: 'preset' },
    { id: 'tool-subagent-remote', file: 'presets/zabz/agent.cordis.yml', line: 372, where: 'preset' },
  ],
  isolateServices: [
    { service: 'workflowEngine', file: 'presets/zabz/agent.cordis.yml', line: 301 },
  ],
  settingsKeys: [
    { key: 'spend-guard.ceilingUsd', value: 150, file: 'settings/base.yaml', line: 41 },
    { key: 'llm-deepseek.streamIdleTimeoutMs', value: 60000, file: 'settings/base.yaml', line: 13 },
    { key: 'ui-onboarding.welcomeNoticeVersion', value: '2026-08-13.1', file: 'settings/base.yaml', line: 1 },
  ],
  cliInvocations: [
    { argv: ['plugin', 'add'], file: 'scripts/dsh-plugin-sync.py', line: 12 },
    { argv: ['web', '--port'], file: 'multi-window/dshw.ps1', line: 249 },
  ],
  pluginImports: [
    { package: 'dsh-plugin-health', module: '@deepseek-ai/cordis', symbols: [consumedSymbol], file: 'packages/plugin-health/src/index.ts', line: 3 },
    { package: 'dsh-plugin-remote-fanout', module: '@deepseek-ai/dsh-tool-subagent', symbols: [consumedSubagentSymbol], file: 'packages/plugin-remote-fanout/src/index.ts', line: 11 },
  ],
  patchRowTargets: [
    { id: 'typert-gateway', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\cordis.patch.yml', line: 28, layer: 'host' },
    { id: 'connection', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\cordis.patch.yml', line: 64, layer: 'host' },
    { id: 'remote-fanout', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\cordis.patch.yml', line: 132, layer: 'host' },
    { id: 'tool-subagent-remote', file: 'C:\\Users\\ezabz\\.dsh\\profiles\\web\\cordis.patch.yml', line: 248, layer: 'host' },
  ],
  notes: ['fixture: file/line pairs are the real lines in this deployment (verified 2026-09-23)'],
};

/* ------------------------------------------------------------------ contracts */

/* DELTA for F-B2: the candidate's dsh-tool-subagent-control drops ./list-agents.
   Real shape: the pinned package.json exports {".":…, "./list-agents":…, "./src/*":…, "./package.json":…}. */
const candidateB2 = contractFor(CANDIDATE_VERSION, (c) => {
  const p = c.packages['@deepseek-ai/dsh-tool-subagent-control'];
  p.exportSubpaths = p.exportSubpaths.filter((s) => s !== './list-agents');
  delete p.exportsRaw['./list-agents'];
  /* version bumps: a real upgrade moves the 0.1.x-rc line and deeper majors stay put (cordis 4.x) */
  for (const v of Object.values(c.packages)) {
    if (String(v.version).startsWith('0.1.')) v.version = CANDIDATE_VERSION;
  }
  /* DELTA for B6: the settings keys our deployment sets on llm-deepseek are announced in the
     baseline and one of them is gone in the candidate. This single field is SYNTHETIC (a real
     contract fills settingsKeys by regex from built JavaScript) and is labelled as synthetic in
     fixtures.json so nothing here pretends to be a measurement. */
  c.packages['@deepseek-ai/dsh-llm-deepseek'].settingsKeys = ['retryPolicy'];
  /* DELTA for B7 RISKY: a surface change on a package we consume, with the version in the summary */
  const llm = c.packages['@deepseek-ai/dsh-llm-deepseek'];
  llm.dsh = { ...llm.dsh, configTrees: [{ mount: 'config/llm', path: 'config', scanRoster: false }] };
});
candidateB2.dsh.version = CANDIDATE_VERSION;

/* DELTA for F-advisory-downgrade: identical to candidateB2 except that the contract declares the
   export-subpath data it rests on to be ADVISORY (regex-derived) rather than AUTHORITATIVE. The same
   B2 comparison must then come out RISKY and say it was downgraded — never BREAKS. */
const candidateAdvisory = JSON.parse(JSON.stringify(candidateB2));
candidateAdvisory.packages['@deepseek-ai/dsh-tool-subagent-control'].provenance.exportSubpaths = 'ADVISORY';

/* DELTA for F-B1: the package is gone from the candidate entirely. */
const candidateB1 = JSON.parse(JSON.stringify(candidateB2));
delete candidateB1.packages['@deepseek-ai/dsh-tool-subagent-control'];
candidateB1.packageCount = Object.keys(candidateB1.packages).length;

/* DELTA for F-B5: a profile bundle is gone from the candidate entirely. */
const candidateB5 = JSON.parse(JSON.stringify(candidateB2));
delete candidateB5.packages['@deepseek-ai/dsh-web-app'];
candidateB5.packageCount = Object.keys(candidateB5.packages).length;

/* DELTA for F-B8: the candidate no longer lists the symbol our plugin imports (still ADVISORY). */
const candidateB8 = JSON.parse(JSON.stringify(candidateB2));
candidateB8.packages['@deepseek-ai/cordis'].symbols = candidateB8.packages['@deepseek-ai/cordis'].symbols.filter((s) => s !== consumedSymbol);

/* DELTA for F-B10: NO removals at all, plus one package the baseline does not have and one new dsh
   config key — a pure capability gain, which must still be SAFE. */
const candidateClean = contractFor(CANDIDATE_VERSION, (c) => {
  for (const v of Object.values(c.packages)) if (String(v.version).startsWith('0.1.')) v.version = CANDIDATE_VERSION;
  c.packages['@deepseek-ai/dsh-llm-deepseek'].settingsKeys = ['streamIdleTimeoutMs', 'retryPolicy'];
  const cordis = c.packages['@deepseek-ai/cordis'];
  c.packages['@deepseek-ai/dsh-tool-browser'] = {
    version: CANDIDATE_VERSION,
    dir: 'node_modules/@deepseek-ai/dsh-tool-browser',
    present: true,
    exportSubpaths: ['.', './package.json'],
    exportsRaw: { '.': './lib/index.js', './package.json': './package.json' },
    dsh: { configTrees: [{ mount: 'config', path: 'config' }] },
    dependencies: {},
    peerDependencies: { '@deepseek-ai/cordis': '^4.0.2' },
    provenance: { manifest: 'AUTHORITATIVE', exportSubpaths: 'AUTHORITATIVE', symbols: 'ADVISORY' },
    settingsKeys: ['browserPath', 'headless'],
    serviceNames: ['browser'],
    toolNames: ['browser'],
    symbols: ['browserTool', 'openPage'],
  };
  const llm = c.packages['@deepseek-ai/dsh-llm-deepseek'];
  llm.dsh = { ...llm.dsh, streamRetryBudget: 3 };
  c.packages['@deepseek-ai/dsh-client-connection'] = {
    ...c.packages['@deepseek-ai/dsh-client-connection'],
    exportSubpaths: [...c.packages['@deepseek-ai/dsh-client-connection'].exportSubpaths, './trusted-hosts'],
  };
  void cordis;
});
candidateClean.dsh.version = CANDIDATE_VERSION;
candidateClean.packageCount = Object.keys(candidateClean.packages).length;

/* ------------------------------------------------------------------ trees */

const treeBaseline = treeFromDump(BASELINE_VERSION);
/* DELTA for F-B10: one extra row id, present in the candidate only. */
const treeCandidate = treeFromDump(CANDIDATE_VERSION, (t) => {
  t.rows = [...t.rows, {
    index: t.rows.length, id: 'capability-probe-row', name: '@deepseek-ai/dsh-tool-browser',
    disabled: false, group: false, config: {}, layers: ['@deepseek-ai/dsh-tool-browser'], patchedBy: null,
  }];
  t.rowIds = [...t.rowIds, 'capability-probe-row'];
  t.names = [...new Set([...t.names, '@deepseek-ai/dsh-tool-browser'])];
  t.layerComments = [...t.layerComments, '@deepseek-ai/dsh-tool-browser'];
});
/* DELTA for F-B3: our patch silently stops applying — the row still exists, the attribution is gone. */
const treeB3PatchLost = treeFromDump(CANDIDATE_VERSION, (t) => {
  t.patchedRowIds = t.patchedRowIds.filter((id) => id !== 'typert-gateway');
  t.rows = t.rows.map((r) => (r.id === 'typert-gateway' ? { ...r, patchedBy: null } : r));
});
/* DELTA for F-B3 (second sub-case): upstream deleted the row our patch targets. */
const treeB3RowDeleted = treeFromDump(CANDIDATE_VERSION, (t) => {
  t.rows = t.rows.filter((r) => r.id !== 'typert-gateway');
  t.rowIds = t.rowIds.filter((id) => id !== 'typert-gateway');
  t.patchedRowIds = t.patchedRowIds.filter((id) => id !== 'typert-gateway');
});
/* DELTA for F-B4: the row survives, still patched, but now mounts a different plugin. */
const treeB4Moved = treeFromDump(CANDIDATE_VERSION, (t) => {
  t.rows = t.rows.map((r) => (r.id === 'typert-gateway' ? { ...r, name: '@deepseek-ai/dsh-api-gateway-legacy' } : r));
  t.names = [...new Set(t.rows.map((r) => r.name).filter(Boolean))];
});
/* DELTA for the failed-read case: the dump exited non-zero and produced nothing. */
const treeFailed = {
  schemaVersion: 1,
  generatedAt: '2026-09-23T20:00:00.000Z',
  enginePath: path.join(INSTALL, '@deepseek-ai', 'dsh', 'lib', 'bin.js'),
  engineVersion: CANDIDATE_VERSION,
  dshHome: 'C:\\Users\\ezabz\\.dsh',
  profile: 'web',
  isolatedHome: 'C:\\Users\\ezabz\\Code\\harness-config\\dsh-update\\state\\candidates\\0.1.7-rc.1\\home',
  invocation: 'node <bin.js> --profile web --dump-config',
  exitCode: 1,
  durationMs: 210,
  stderr: 'dsh: plugin tree failed to load: failed to apply loader entry include (cordis:include)',
  failure: 'exit 1: dsh: plugin tree failed to load: failed to apply loader entry include (cordis:include)',
  rows: [],
  rowIds: [],
  names: [],
  layerComments: [],
  patchedRowIds: [],
  disabledRowIds: [],
  stdoutRef: 'state/logs/verify-0.1.7-rc.1-G1.txt',
  notes: ['fixture: a real failure shape (exit code plus verbatim engine words), rows deliberately empty'],
};

/* ------------------------------------------------------------------ write */

const written = [];
written.push(write('contract-baseline.json', contractFor(BASELINE_VERSION, (c) => {
  c.packages['@deepseek-ai/dsh-llm-deepseek'].settingsKeys = ['streamIdleTimeoutMs', 'retryPolicy'];
})));
written.push(write('contract-candidate.json', candidateB2));
written.push(write('contract-candidate-advisory.json', candidateAdvisory));
written.push(write('contract-candidate-b1.json', candidateB1));
written.push(write('contract-candidate-b5.json', candidateB5));
written.push(write('contract-candidate-b8.json', candidateB8));
written.push(write('contract-candidate-clean.json', candidateClean));
written.push(write('consumed.json', consumed));
written.push(write('tree-baseline.json', treeBaseline));
written.push(write('tree-candidate.json', treeCandidate));
written.push(write('tree-candidate-b3-patch-lost.json', treeB3PatchLost));
written.push(write('tree-candidate-b3-row-deleted.json', treeB3RowDeleted));
written.push(write('tree-candidate-b4-moved.json', treeB4Moved));
written.push(write('tree-failed.json', treeFailed));
written.push(write('fixtures.json', {
  baselineVersion: BASELINE_VERSION,
  candidateVersion: CANDIDATE_VERSION,
  dumpedAt: DUMP_PATH,
  installRoot: PREFIX,
  consumedSymbolForB8: consumedSymbol,
  consumedSubagentSymbolForB8: consumedSubagentSymbol,
  rowCount: treeBaseline.rows.length,
  patchedRowIds: treeBaseline.patchedRowIds,
  syntheticFields: [
    'packages["@deepseek-ai/dsh-llm-deepseek"].settingsKeys (baseline ["streamIdleTimeoutMs","retryPolicy"], candidate ["retryPolicy"]) — the B6 fixture; a real contract fills settingsKeys by regex from built JavaScript',
    'packages["@deepseek-ai/dsh-tool-browser"] in contract-candidate-clean.json — a synthetic package that stands for any package the newer engine adds (the B10 fixture)',
  ],
  generatedBy: 'tests/make-fixtures.mjs',
}));

console.log(`fixtures written to ${OUT}`);
for (const w of written) console.log(`  ${w}`);
console.log(`cordis symbols: ${cordisSymbols.length} (B8 uses ${JSON.stringify(consumedSymbol)})`);
