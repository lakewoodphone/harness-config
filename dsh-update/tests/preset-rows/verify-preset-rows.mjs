#!/usr/bin/env node
/**
 * verify-preset-rows.mjs — prove the generated `preset-*` rows actually work under 0.1.7.
 *
 * WHAT IS BEING PROVED, AND WHY EACH CHECK IS THE RIGHT ONE
 * --------------------------------------------------------
 * 1. ROUND-TRIP. The `plugins` array of each emitted row must be the source `agent.cordis.yml` row
 *    list, row for row. A converter that drops or reorders rows silently loses capability, so the
 *    comparison is the real test — counts, ids in order, and every `!!js` source text. Both sides
 *    are parsed with the same YAML parser so the comparison is of values, not of formatting.
 *
 * 2. BYTE-FOR-BYTE `!!js`. `!!js` is the one field whose *loss* is silent: a tag resolved to
 *    `undefined` leaves a `disabled: !!js undefined` that the engine evaluates as false, quietly
 *    enabling platform-gated rows. So each source expression must appear verbatim in the emitted
 *    bytes, and the string `!!js undefined` must appear nowhere.
 *
 * 3. THE ENGINE AGREES. The strongest available check is not our own parse of our own file — it is
 *    `--dump-config` under the candidate engine, composing the real profile with this file as
 *    `--patch`. That runs the same `applyEntryPatches` the boot path runs. If the rows appear there
 *    with our plugins inside, the composition is what will boot.
 *
 * Usage:
 *   node tests/preset-rows/verify-preset-rows.mjs [--patch <file>] [--presets-dir <dir>]
 *        [--tree <composed.json>] [--bin <0.1.7 engine bin.js>] [--profile web] [--names a,b,c]
 *
 *   --tree   reuse an existing compose.mjs artifact instead of invoking the engine.
 *   --bin    the candidate engine to compose with when --tree is not given (required then).
 *
 * Exit 0 when every check passes; 1 otherwise. A failed read is reported as a failure, never as an
 * empty pass.
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import { PARSE_OPTIONS, YAML } from '../../lib/yaml.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..');
const COMPOSE = resolve(HERE, '..', '..', 'lib', 'compose.mjs');

const DEFAULTS = {
  patch: join(REPO_ROOT, 'profiles', 'web', 'presets.generated.patch.yml'),
  presetsDir: join(REPO_ROOT, 'presets'),
  profile: 'web',
};

const isJs = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v) && typeof v.__js === 'string';

/** Every `!!js` source text in a value, in document order. */
function collectJsTexts(node, acc = []) {
  if (isJs(node)) acc.push(node.__js);
  else if (Array.isArray(node)) node.forEach((child) => collectJsTexts(child, acc));
  else if (node && typeof node === 'object') Object.values(node).forEach((child) => collectJsTexts(child, acc));
  return acc;
}

const idsOf = (rows) => rows.map((r) => r.id);

/** Compare two row lists the way the brief defines correctness: count, ids in order, `!!js` texts. */
function compare(sourceRows, emittedRows) {
  const sourceIds = idsOf(sourceRows);
  const emittedIds = idsOf(emittedRows);
  const sourceJs = collectJsTexts(sourceRows);
  const emittedJs = collectJsTexts(emittedRows);
  const differing = sourceIds.filter((id, i) => emittedIds[i] !== id);
  return {
    sourceCount: sourceRows.length,
    emittedCount: emittedRows.length,
    countMatches: sourceRows.length === emittedRows.length,
    sourceIds,
    emittedIds,
    idsMatchInOrder: isDeepStrictEqual(sourceIds, emittedIds),
    differingIds: differing,
    sourceJsCount: sourceJs.length,
    emittedJsCount: emittedJs.length,
    jsTextsMatch: isDeepStrictEqual(sourceJs, emittedJs),
    jsTextsThatDiffer: sourceJs.filter((t, i) => emittedJs[i] !== t),
    deepEqual: isDeepStrictEqual(sourceRows, emittedRows),
  };
}

function parseArgs(argv) {
  const args = { ...DEFAULTS, tree: null, bin: null, names: null };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--patch') args.patch = need('--patch');
    else if (a === '--presets-dir') args.presetsDir = need('--presets-dir');
    else if (a === '--tree') args.tree = need('--tree');
    else if (a === '--bin') args.bin = need('--bin');
    else if (a === '--profile') args.profile = need('--profile');
    else if (a === '--names') args.names = need('--names').split(',').map((s) => s.trim()).filter(Boolean);
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const failures = [];
  const rel = (p) => p.replace(`${REPO_ROOT}\\`, '').replace(`${REPO_ROOT}/`, '');
  const abs = (p) => (isAbsolute(p) ? p : resolve(process.cwd(), p));

  const patchFile = abs(args.patch);
  const presetsDir = abs(args.presetsDir);

  // ── read the emitted patch file ────────────────────────────────────────────────────────────
  if (!existsSync(patchFile)) {
    console.error(`FAIL: the generated patch file does not exist: ${patchFile}`);
    return 1;
  }
  const patchBytes = readFileSync(patchFile, 'utf8');
  let patchDoc;
  try {
    patchDoc = YAML.parse(patchBytes, PARSE_OPTIONS);
  } catch (e) {
    console.error(`FAIL: cannot parse ${patchFile}: ${e.message}`);
    return 1;
  }
  if (!Array.isArray(patchDoc) || patchDoc.length === 0) {
    console.error(`FAIL: ${patchFile} is not a non-empty top-level YAML array (patch files must be)`);
    return 1;
  }
  console.log(`patch file: ${rel(patchFile)} (${Buffer.byteLength(patchBytes, 'utf8')} bytes, `
    + `${patchDoc.length} top-level patch entries)`);

  // Every entry must be an `insert` with no `id` — that is what appends rather than targets.
  const emitted = new Map();
  for (const [i, entry] of patchDoc.entries()) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      failures.push(`patch entry ${i + 1} is not a mapping`);
      continue;
    }
    if (!Array.isArray(entry.insert)) {
      failures.push(`patch entry ${i + 1} has no insert list (keys: ${Object.keys(entry).join(',')})`);
      continue;
    }
    if (entry.id !== undefined) {
      failures.push(`patch entry ${i + 1} carries an id (${entry.id}); an id-targeted insert patches `
        + 'a group row instead of appending');
    }
    for (const row of entry.insert) {
      if (row.name !== '@deepseek-ai/dsh-agent-preset') {
        failures.push(`inserted row ${row.id} names ${row.name}, not @deepseek-ai/dsh-agent-preset`);
      }
      emitted.set(row.id, row);
    }
  }

  const selected = args.names
    ?? [...emitted.keys()].map((id) => id.replace(/^preset-/, '')).sort();

  // ── 1. round-trip: emitted `plugins` vs the source row list ────────────────────────────────
  console.log('');
  console.log('== 1. round-trip: emitted plugins  vs  source agent.cordis.yml ==');
  const sourceByName = new Map();
  for (const name of selected) {
    const rowId = `preset-${name}`;
    const row = emitted.get(rowId);
    if (!row) {
      failures.push(`${rowId} is absent from ${rel(patchFile)}`);
      continue;
    }
    const sourceFile = join(presetsDir, name, 'agent.cordis.yml');
    if (!existsSync(sourceFile)) {
      failures.push(`source preset is missing: ${sourceFile}`);
      continue;
    }
    let sourceRows;
    try {
      sourceRows = YAML.parse(readFileSync(sourceFile, 'utf8'), PARSE_OPTIONS);
    } catch (e) {
      failures.push(`cannot parse ${sourceFile}: ${e.message}`);
      continue;
    }
    sourceByName.set(name, sourceRows);

    const cfg = row.config ?? {};
    const emittedRows = cfg.plugins;
    if (!Array.isArray(emittedRows)) {
      failures.push(`${rowId}.config.plugins is not an array (got ${typeof emittedRows})`);
      continue;
    }
    const cmp = compare(sourceRows, emittedRows);
    const ok = cmp.countMatches && cmp.idsMatchInOrder && cmp.jsTextsMatch;
    if (!ok) failures.push(`${rowId}: round-trip mismatch`);
    console.log('');
    console.log(`  ${rowId}  name=${row.name}  config.id=${JSON.stringify(cfg.id)}  order=${JSON.stringify(cfg.order)}`);
    console.log(`    source rows=${cmp.sourceCount}   emitted rows=${cmp.emittedCount}   count matches=${cmp.countMatches}`);
    console.log(`    source  ids: ${cmp.sourceIds.join(', ')}`);
    console.log(`    emitted ids: ${cmp.emittedIds.join(', ')}`);
    console.log(`    ids identical and in the same order=${cmp.idsMatchInOrder}   differing ids: ${cmp.differingIds.length === 0 ? '(none)' : cmp.differingIds.join(', ')}`);
    console.log(`    !!js exprs source=${cmp.sourceJsCount} emitted=${cmp.emittedJsCount} identical=${cmp.jsTextsMatch}`
      + `${cmp.jsTextsThatDiffer.length ? ` differing=${cmp.jsTextsThatDiffer.map(JSON.stringify).join(', ')}` : ''}`);
    console.log(`    whole row list deep-equal (structure, keys and values, not just ids)=${cmp.deepEqual}`);
    console.log(`    VERDICT: ${ok ? 'MATCH' : 'MISMATCH'}`);
  }

  // ── 2. byte-for-byte `!!js` in the emitted bytes ───────────────────────────────────────────
  console.log('');
  console.log('== 2. `!!js` source text, byte-for-byte in the emitted file ==');
  const allSourceJs = [...sourceByName.values()].flatMap((rows) => collectJsTexts(rows));
  const missing = allSourceJs.filter((expr) => !patchBytes.includes(expr));
  const undefinedTags = (patchBytes.match(/!!js +undefined\b/g) ?? []).length;
  const jsLines = patchBytes.split('\n').filter((line) => /!!js/.test(line));
  console.log(`  source \`!!js\` expressions: ${allSourceJs.length}`);
  console.log(`  present verbatim in the emitted bytes: ${allSourceJs.length - missing.length}`);
  console.log(`  missing: ${missing.length === 0 ? '(none)' : missing.map(JSON.stringify).join(', ')}`);
  console.log(`  occurrences of \`!!js undefined\`: ${undefinedTags}`);
  console.log(`  emitted lines carrying \`!!js\`: ${jsLines.length}`);
  for (const line of jsLines.slice(0, 4)) console.log(`    ${line}`);
  if (missing.length > 0) failures.push(`${missing.length} \`!!js\` expression(s) are not verbatim in the emitted file`);
  if (undefinedTags > 0) failures.push(`${undefinedTags} \`!!js undefined\` tag(s) in the emitted file — an expression was lost`);

  // ── 3. the candidate engine composes it ────────────────────────────────────────────────────
  console.log('');
  console.log('== 3. the candidate engine composes the patched profile ==');
  let treeFile = args.tree ? abs(args.tree) : null;
  if (!treeFile) {
    if (!args.bin) {
      failures.push('no --tree and no --bin: the engine cannot be asked, so check 3 cannot be made. '
        + 'That is a failure, not a pass.');
    } else {
      const outDir = mkdtempSync(join(tmpdir(), 'preset-rows-'));
      treeFile = join(outDir, 'verify.json');
      const argv = [COMPOSE, '--profile', args.profile, '--bin', abs(args.bin),
        '--patch', patchFile, '--out', treeFile, '--log-dir', join(outDir, 'logs')];
      console.log(`  running: node ${argv.map((a) => (a.includes(' ') ? `"${a}"` : a)).join(' ')}`);
      const run = spawnSync(process.execPath, argv, { stdio: 'inherit' });
      console.log(`  compose exit=${run.status}`);
      if (run.status !== 0) failures.push(`compose.mjs exited ${run.status}`);
    }
  } else {
    console.log(`  reusing ${rel(treeFile)}`);
  }

  if (treeFile && existsSync(treeFile)) {
    const tree = JSON.parse(readFileSync(treeFile, 'utf8'));
    if (tree.failure) failures.push(`the composed tree carries a failure: ${tree.failure}`);
    console.log(`  engine=${tree.enginePath}`);
    console.log(`  engineVersion=${tree.engineVersion}  exitCode=${tree.exitCode}  rows=${tree.rows?.length}  `
      + `durationMs=${tree.durationMs}`);
    const byId = new Map((tree.rows ?? []).map((r) => [r.id, r]));
    for (const name of selected) {
      const rowId = `preset-${name}`;
      const composed = byId.get(rowId);
      if (!composed) {
        failures.push(`${rowId} is NOT in the composed tree`);
        console.log(`  ${rowId}: ABSENT from the composed tree`);
        continue;
      }
      const plugins = composed.config?.plugins;
      const sourceRows = sourceByName.get(name) ?? [];
      const cmp = Array.isArray(plugins) ? compare(sourceRows, plugins) : null;
      const ok = Boolean(cmp) && cmp.countMatches && cmp.idsMatchInOrder && cmp.jsTextsMatch;
      if (!ok) failures.push(`${rowId}: the composed row does not match the source preset`);
      console.log(`  ${rowId}  name=${composed.name}  config.id=${JSON.stringify(composed.config?.id)}  `
        + `order=${JSON.stringify(composed.config?.order)}  plugins=${Array.isArray(plugins) ? plugins.length : 'NO_ARRAY'}`);
      if (cmp) {
        console.log(`    vs source: rows ${cmp.emittedCount}==${cmp.sourceCount} ids-in-order=${cmp.idsMatchInOrder} `
          + `js-texts-identical=${cmp.jsTextsMatch} deep-equal=${cmp.deepEqual}`);
      }
      const firstIds = Array.isArray(plugins) ? plugins.slice(0, 6).map((p) => p.id).join(', ') : '';
      console.log(`    first plugin ids: ${firstIds}${Array.isArray(plugins) && plugins.length > 6 ? ', ...' : ''}`);
    }
  }

  console.log('');
  if (failures.length > 0) {
    console.log(`RESULT: FAIL — ${failures.length} problem(s)`);
    for (const f of failures) console.log(`  - ${f}`);
    return 1;
  }
  console.log('RESULT: PASS — every checked claim held');
  return 0;
}

const invokedDirectly = Boolean(process.argv[1])
  && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) process.exit(main());
