// cli.mjs — the single dispatcher for the dsh-update pipeline.
//
// Verbs: status, check, snapshot, fetch <ver>, analyze <ver>, plan <ver>, verify <ver>,
//        promote <ver>, rollback, report <ver>.  No verb = status.  Every verb takes --json.
//
// Two rules shape this file:
//   * `lib/*.mjs` owned by other workstreams (contract, compose, diff, report, verify, consumed,
//     yaml) may not exist yet. They are therefore imported LAZILY — only inside the verb that needs
//     them — and a missing module produces an actionable message naming the owner, never a stack
//     trace. `status`, `check`, `snapshot`, `plan`, `fetch` and the two refusal paths must work with
//     nothing else present.
//   * Nothing here starts, stops or restarts an engine. The only engine invocation anywhere in this
//     pipeline is `node <bin.js> --version` (and, later, a verify gate run by verify.mjs), both
//     read-only. `promote` writes state and the launcher knob; the change takes effect at the NEXT
//     boot, because restarting the engine from inside a session kills that session.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import {
  PATHS, ROOT, REPO_ROOT, appendHistory, backupAndWrite, candidatePaths, ensureDir, fileInfo,
  hostName, readHistory, readJson, readJsonChecked, readPin, safeRelPath, sha256File, validatePin,
  vendorPrefixPath, windowsJsonPath, writeJsonAtomic, writePin, logInvocation,
} from './store.mjs';
import {
  ENGINE_REL, classify, detectInstalledEngine, fetchCandidate, newerThan, registryPicture,
} from './versions.mjs';

const VERSION = '1';
const ARGV = process.argv.slice(2);

const VERB_HELP = {
  status: 'print the pin, the real engine path and version, available versions, analysis state',
  check: 'query the registry and classify every published version against the pin',
  snapshot: 'describe the pinned engine -> state/baseline/{contract.json,tree.json}',
  fetch: 'fetch <ver>: npm install into vendor/prefix/<ver> (never the npx cache)',
  analyze: 'analyze <ver>: contract diff + consumed cross-reference -> diff.json, report.md',
  plan: 'plan <ver>: exactly what promote would change; writes nothing',
  verify: 'verify <ver>: the five gates -> verify.json',
  promote: 'promote <ver>: pin the candidate and set the launcher knob; never restarts the engine',
  rollback: 'rollback: restore the predecessor pin and the launcher knob; never restarts the engine',
  report: 'report <ver>: print the report path and the verdict summary',
  'patch-effect': 'patch-effect <ver> [--profile web] [--layer <yml>]: does every patch WE own still have its intended effect on the candidate?',
  'preset-gate': 'preset-gate <ver>: does every package and subpath our PRESETS name still resolve on the candidate?',
  preflight: 'preflight <ver>: run EVERY guard in order and print one GO/NO-GO — the triple-check command',
};

const VERB_OWNER = {
  'lib/yaml.mjs': 'another workstream (yaml resolution)',
  'lib/contract.mjs': 'another workstream (contract.mjs)',
  'lib/compose.mjs': 'another workstream (compose.mjs)',
  'lib/consumed.mjs': 'another workstream (consumed.mjs)',
  'lib/diff.mjs': 'another workstream (diff.mjs)',
  'lib/report.mjs': 'another workstream (report.mjs)',
  'lib/verify.mjs': 'another workstream (verify.mjs)',
};

class CliError extends Error {
  constructor(message, { exitCode = 1, detail = null } = {}) {
    super(message);
    this.exitCode = exitCode;
    this.detail = detail;
  }
}

// ── lazy modules owned by other workstreams ─────────────────────────────────

/**
 * Import a sibling module only when the running verb needs it. A missing file is a workstream that
 * has not landed yet: say which file and who owns it, and exit non-zero.
 */
async function needLib(name) {
  const file = path.join(PATHS.libDir, name);
  if (!fs.existsSync(file)) {
    throw new CliError(
      `lib/${name} is not present yet — it is owned by ${VERB_OWNER[name] || 'another workstream'}, not by this one.\n`
      + `  This verb cannot run until that file exists at ${safeRelPath(file)}.\n`
      + `  Verbs that work without it: status, check, snapshot (partly), fetch, plan, promote, rollback, report.`,
      { exitCode: 4 },
    );
  }
  try {
    return await import(pathToFileURL(file).href);
  } catch (err) {
    throw new CliError(`lib/${name} exists but failed to load: ${err.message}`, { exitCode: 4, detail: err.stack });
  }
}

/**
 * Resolve an entry point from a sibling module by name, trying each candidate in order. The modules
 * are other workstreams' contract with the SINGLE dispatcher, so the expected names are listed in
 * one place and a mismatch is reported with the exports that do exist rather than a stack trace.
 */
async function needExport(name, candidates) {
  const file = path.join(PATHS.libDir, name);
  const mod = await needLib(name);
  const found = candidates.filter((c) => typeof mod[c] === 'function');
  if (found.length === 0) {
    throw new CliError(
      `lib/${name} does not export any of: ${candidates.join(', ')}.\n`
      + `  It is present at ${safeRelPath(file)}, so this is an interface mismatch between the dispatcher and that workstream.\n`
      + `  Exports found: ${Object.keys(mod).join(', ') || '(none)'}`,
      { exitCode: 4 },
    );
  }
  const fn = mod[found[0]];
  fn.dshUpdateExport = found[0];
  return fn;
}

/**
 * Call a sibling module's entry point with the context object, trying the export names that
 * workstream may have used. The name it actually had is recorded, so an artifact can say which
 * function produced it. A module that is present but exports none of the names is an interface
 * mismatch, and says so with the exports it does have.
 */
async function callLib(name, ctx, candidates) {
  const fn = await needExport(name, candidates);
  const result = await fn(ctx);
  return { module: `lib/${name}`, export: fn.dshUpdateExport, result: result === undefined ? null : result };
}

/**
 * Run a sibling module as its own CLI process.
 *
 * The SPEC says each `lib/*.mjs` "also runs standalone as `node lib/<module>.mjs <args>`, printing
 * its JSON artifact to stdout". For modules that ship ONLY that interface there is nothing to
 * import: `lib/diff.mjs` (landed 2026-09-23) defines no exports at all and imports no sibling, so
 * spawning it with its documented flags IS the integration point. Its `--out` is used when it has
 * one, so the artifact is byte-identical to what `analyze` claims.
 *
 * This spawns `node` and the module. It never touches an engine.
 */
function runModuleCli(name, args, { timeoutMs = 600000 } = {}) {
  const file = path.join(PATHS.libDir, name);
  if (!fs.existsSync(file)) {
    throw new CliError(
      `lib/${name} is not present yet — it is owned by ${VERB_OWNER[name] || 'another workstream'}, not by this one.\n`
      + `  This verb cannot run until that file exists at ${safeRelPath(file)}.\n`
      + `  Verbs that work without it: status, check, fetch, plan, promote, rollback, report.`,
      { exitCode: 4 },
    );
  }
  const argv = [file, ...args];
  const res = spawnSync(process.execPath, argv, {
    cwd: ROOT, encoding: 'utf8', timeout: timeoutMs, windowsHide: true, maxBuffer: 64 * 1024 * 1024,
  });
  const stdout = res.stdout || '';
  const stderr = res.stderr || '';
  if (res.error) {
    throw new CliError(`could not run lib/${name}: ${res.error.message}\n  command: node ${safeRelPath(file)} ${args.join(' ')}`, { exitCode: 4 });
  }
  return { module: `lib/${name}`, command: `node ${safeRelPath(file)} ${args.join(' ')}`, argv, exitCode: res.status, stdout, stderr, ok: res.status === 0 };
}

/** Parse a module CLI's stdout as JSON, or explain precisely why it could not be used. */
function parseJsonStdout(run) {
  const text = run.stdout.trim();
  if (!text) {
    throw new CliError(
      `${run.module} exited ${run.exitCode} and printed nothing on stdout, so there is no artifact to read.\n`
      + `  command: ${run.command}\n  stderr: ${run.stderr.trim().slice(0, 1200) || '(empty)'}`,
      { exitCode: 4 },
    );
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new CliError(
      `${run.module} printed something on stdout that is not JSON (${err.message}).\n`
      + `  command: ${run.command}\n  first bytes: ${JSON.stringify(text.slice(0, 200))}`,
      { exitCode: 4 },
    );
  }
}

/** Read an artifact a module CLI wrote with --out, refusing to treat an absent file as success. */
function readArtifact(file, label, run) {
  const read = readJsonChecked(file, null);
  if (!read.value) {
    throw new CliError(
      `${label} was not produced: ${read.reason}\n  expected at ${safeRelPath(file)}`
      + (run ? `\n  ${run.module} exited ${run.exitCode}; stderr: ${run.stderr.trim().slice(0, 1200) || '(empty)'}` : ''),
      { exitCode: 4 },
    );
  }
  return read.value;
}

// ── presentation ────────────────────────────────────────────────────────────

let JSON_MODE = false;
function emit(payload, text) {
  if (JSON_MODE) {
    process.stdout.write(`${JSON.stringify({ ok: payload.ok !== false, verb: payload.verb, ...payload }, null, 2)}\n`);
  } else {
    process.stdout.write(text.endsWith('\n') ? text : `${text}\n`);
  }
}

function line(label, value) { return `  ${label.padEnd(22)} ${value}`; }
function rel(p) { return safeRelPath(p); }
function ago(iso) {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return `unparseable timestamp ${iso}`;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

// ── candidate artifacts ─────────────────────────────────────────────────────

function candidateState(version) {
  const p = candidatePaths(version);
  const verify = readJsonChecked(p.verify, null);
  const diff = readJsonChecked(p.diff, null);
  const contract = fileInfo(p.contract);
  return {
    version,
    dir: p.dir,
    dirExists: fs.existsSync(p.dir),
    contract: { path: p.contract, exists: contract.exists, sha256: contract.sha256, bytes: contract.bytes },
    diff: diff.value ? {
      path: p.diff, verdict: diff.value.verdict ?? null, generatedAt: diff.value.generatedAt ?? null,
      counts: diff.value.counts ?? null,
    } : null,
    diffProblem: diff.value ? null : diff.reason,
    verify: verify.value ? {
      path: p.verify, pass: verify.value.pass === true, generatedAt: verify.value.generatedAt ?? null,
      contractSha256: verify.value.contractSha256 ?? null,
      gates: Array.isArray(verify.value.gates)
        ? verify.value.gates.map((g) => ({ id: g.id, ok: g.ok === true, ran: g.ran === true, detail: g.detail ?? '' }))
        : [],
    } : null,
    verifyProblem: verify.value ? null : verify.reason,
    report: fileInfo(p.report).exists,
    prefix: fileInfo(path.join(vendorPrefixPath(version), ENGINE_REL)).exists,
  };
}

function allCandidates() {
  const out = [];
  let entries = [];
  try { entries = fs.readdirSync(PATHS.candidatesDir, { withFileTypes: true }); } catch { entries = []; }
  for (const e of entries) {
    if (e.isDirectory()) out.push(candidateState(e.name));
  }
  return out.sort((a, b) => a.version.localeCompare(b.version));
}

function pinnedState() {
  const read = readJsonChecked(PATHS.pin, null);
  if (!read.value) {
    return { present: false, path: PATHS.pin, problem: read.reason, pin: null };
  }
  const v = validatePin(read.value);
  const pin = read.value;
  const contractOnDisk = fileInfo(PATHS.baselineContract);
  const treeOnDisk = fileInfo(PATHS.baselineTree);
  const cmp = (expected, actual) => (expected ? (actual ? (expected === actual ? 'match' : 'MISMATCH') : 'file-absent') : 'not-recorded');
  return {
    present: true,
    path: PATHS.pin,
    schemaOk: v.ok,
    schemaProblems: v.problems,
    pin,
    pinsMatchDisk: {
      contract: { expected: pin.contractSha256 ?? null, actual: contractOnDisk.sha256, verdict: cmp(pin.contractSha256, contractOnDisk.sha256), path: PATHS.baselineContract },
      tree: { expected: pin.treeSha256 ?? null, actual: treeOnDisk.sha256, verdict: cmp(pin.treeSha256, treeOnDisk.sha256), path: PATHS.baselineTree },
    },
  };
}

// ── verbs ───────────────────────────────────────────────────────────────────

function readConfigForPlan() {
  const file = windowsJsonPath();
  const read = readJsonChecked(file, {});
  if (!read.exists) {
    throw new CliError(`the launcher config is not readable: ${read.reason}\n  expected at ${safeRelPath(file)}`, { exitCode: 5 });
  }
  if (!read.ok) {
    throw new CliError(`the launcher config does not parse, so it cannot be edited safely: ${read.reason}\n  file: ${safeRelPath(file)}`, { exitCode: 5 });
  }
  const cfg = read.value && typeof read.value === 'object' ? read.value : {};
  const indentMatch = /\n([ \t]+)"/.exec(fs.readFileSync(file, 'utf8'));
  const indent = indentMatch ? indentMatch[1].length : 2;
  return { file, cfg, indent, current: typeof cfg.dshInstall === 'string' ? cfg.dshInstall : null };
}

async function verbStatus() {
  const pinned = pinnedState();
  const registry = registryPicture();
  const candidates = allCandidates();
  const detected = detectInstalledEngine();

  const versions = registry.versions.ok ? registry.versions.list : [];
  const pinVersion = pinned.pin ? pinned.pin.version : null;
  const current = pinVersion || detected.version || null;
  const newer = current && versions.length ? newerThan(current, versions).map((v) => {
    const state = candidates.find((c) => c.version === v) || null;
    return {
      version: v,
      classification: classify(current, v, versions).classification,
      analyzed: state ? Boolean(state.diff) : false,
      diffVerdict: state && state.diff ? state.diff.verdict : null,
      verified: state ? Boolean(state.verify) : false,
      verifyPass: state && state.verify ? state.verify.pass : null,
      fetched: state ? Boolean(state.prefix) : false,
    };
  }) : [];

  const lines = [];
  lines.push(`dsh-update status  (host ${hostName()}, node ${process.version})`);
  lines.push('');
  if (!pinned.present) {
    lines.push('PIN  none — state/pin.json is absent.');
    lines.push(line('reason', pinned.problem));
    lines.push(line('so the pin is the detected engine', 'run `snapshot` to record a baseline, then declare the pin'));
  } else {
    lines.push(`PIN  ${pinned.pin.version}${pinned.schemaOk ? '' : '  <-- does NOT match the SPEC schema'}`);
    if (!pinned.schemaOk) lines.push(line('schema problems', pinned.schemaProblems.join('; ')));
    lines.push(line('engine path', pinned.pin.enginePath));
    lines.push(line('install root', pinned.pin.installRoot));
    lines.push(line('managed', String(pinned.pin.managed)));
    lines.push(line('pinned at', `${pinned.pin.pinnedAt || '?'} (${ago(pinned.pin.pinnedAt)}) by ${pinned.pin.by || '?'}`));
    lines.push(line('contract sha256', `${pinned.pinsMatchDisk.contract.verdict}  ${pinned.pinsMatchDisk.contract.expected || '(not recorded)'}`));
    lines.push(line('tree sha256', `${pinned.pinsMatchDisk.tree.verdict}  ${pinned.pinsMatchDisk.tree.expected || '(not recorded)'}`));
    lines.push(line('baseline files', `contract.json ${fileInfo(PATHS.baselineContract).exists ? 'present' : 'ABSENT'}, tree.json ${fileInfo(PATHS.baselineTree).exists ? 'present' : 'ABSENT'}`));
    lines.push(line('predecessor', pinned.pin.predecessor ? `${pinned.pin.predecessor.version} (${pinned.pin.predecessor.managed ? 'managed' : 'npx'})` : 'none (rollback would refuse)'));
    if (!pinned.pin.managed) lines.push(line('note', 'managed:false — this pin records whatever npx last resolved, which we do not control'));
  }
  lines.push('');
  lines.push('ENGINE (measured now, not from the pin)');
  lines.push(line('engine path', detected.enginePath || 'none found'));
  lines.push(line('version', detected.versionOk ? detected.version : `UNKNOWN (${detected.versionError})`));
  lines.push(line('version read by', detected.versionCommand || '(not read)'));
  lines.push(line('located via', detected.source || 'nothing found'));
  lines.push(line('npx installs', detected.npxInstalls.length ? detected.npxInstalls.map(rel).join(', ') : 'none'));
  for (const n of detected.notes) lines.push(line('note', n));
  if (detected.ambiguous) lines.push(line('AMBIGUOUS', detected.ambiguous));
  lines.push('');
  lines.push(`REGISTRY  npm view @deepseek-ai/dsh`);
  if (!registry.versions.ok || !registry.distTags.ok) {
    lines.push(line('versions', registry.versions.ok ? `${registry.versions.count} published (in ${registry.versions.durationMs} ms)` : `READ FAILED: ${registry.versions.error}`));
    lines.push(line('dist-tags', registry.distTags.ok ? JSON.stringify(registry.distTags.tags) : `READ FAILED: ${registry.distTags.error}`));
  } else {
    lines.push(line('dist-tags', Object.entries(registry.distTags.tags).map(([k, v]) => `${k}=${v}`).join('  ')));
    lines.push(line('published', `${registry.versions.count} versions (read in ${registry.versions.durationMs} ms)`));
  }
  lines.push('');
  lines.push(`UPGRADE  ${newer.length ? `YES — ${newer.length} published version(s) newer than ${current}` : (versions.length ? `no — ${current} is the newest published version` : 'UNKNOWN — the registry could not be read, so this is not a "no"')}`);
  for (const n of newer) {
    lines.push(line(n.version, `${n.classification}  analyzed=${n.analyzed}${n.diffVerdict ? ` verdict=${n.diffVerdict}` : ''} verified=${n.verified}${n.verifyPass === null ? '' : ` pass=${n.verifyPass}`} fetched=${n.fetched}`));
  }
  if (candidates.length) {
    lines.push('');
    lines.push('CANDIDATE STATE  state/candidates/');
    for (const c of candidates) {
      lines.push(line(c.version, `contract=${c.contract.exists ? 'yes' : 'no'} diff=${c.diff ? c.diff.verdict || 'present' : 'no'} verify=${c.verify ? (c.verify.pass ? 'pass' : 'FAIL') : 'no'} report=${c.report ? 'yes' : 'no'} prefix=${c.prefix ? 'yes' : 'no'}`));
    }
  }
  const badPinSchema = pinned.present && !pinned.schemaOk;
  const registryDead = !registry.versions.ok;
  return {
    ok: !badPinSchema,
    exitCode: badPinSchema ? 2 : (registryDead ? 3 : 0),
    verb: 'status',
    host: hostName(),
    pin: pinned,
    engine: { enginePath: detected.enginePath, version: detected.version, versionOk: detected.versionOk, source: detected.source, command: detected.versionCommand, ambiguous: detected.ambiguous, notes: detected.notes, candidates: detected.candidates, npxInstalls: detected.npxInstalls },
    registry: { distTags: registry.distTags, versions: { ok: registry.versions.ok, count: registry.versions.count || 0, list: registry.versions.list || [], error: registry.versions.error || null, durationMs: registry.versions.durationMs } },
    upgradeAvailable: newer.length > 0,
    newer,
    candidates,
    text: lines.join('\n'),
  };
}

async function verbCheck() {
  const pinned = pinnedState();
  if (!pinned.present) {
    throw new CliError('state/pin.json does not exist, so there is nothing to classify against.\n  Run `snapshot` to record a baseline pin first.', { exitCode: 2 });
  }
  const registry = registryPicture();
  if (!registry.versions.ok) {
    throw new CliError(`the registry could not be read, so no version can be classified: ${registry.versions.error}\n  source: ${registry.versions.source}`, { exitCode: 3 });
  }
  const versions = registry.versions.list;
  const current = pinned.pin.version;
  const candidates = allCandidates();
  const rows = versions.map((v) => {
    const c = classify(current, v, versions);
    const state = candidates.find((x) => x.version === v);
    return {
      version: v,
      isPin: v === current,
      classification: c.classification,
      newerThanPin: c.newerThanPin,
      distance: c.distance,
      analyzed: state ? Boolean(state.diff) : false,
      diffVerdict: state && state.diff ? state.diff.verdict : null,
      verified: state ? Boolean(state.verify) : false,
      verifyPass: state && state.verify ? state.verify.pass : null,
      fetched: state ? Boolean(state.prefix) : false,
    };
  });
  const newer = rows.filter((r) => r.newerThanPin);
  const lines = [];
  lines.push(`dsh-update check  (pin ${current}, ${versions.length} published versions, ${hostName()})`);
  lines.push(`source: ${registry.versions.source}  (read in ${registry.versions.durationMs} ms)`);
  lines.push(`dist-tags: ${Object.entries(registry.distTags.tags || {}).map(([k, v]) => `${k}=${v}`).join('  ')}`);
  lines.push('');
  for (const r of rows) {
    const mark = r.isPin ? 'PINS ' : (r.newerThanPin ? 'NEW  ' : '     ');
    const state = r.fetched ? 'fetched' : '-';
    const analysis = r.diffVerdict ? `analyzed:${r.diffVerdict}` : (r.analyzed ? 'analyzed' : 'not analyzed');
    const verification = r.verifyPass === true ? 'verify:pass' : (r.verified ? 'verify:FAIL' : 'not verified');
    lines.push(`  ${mark}${r.version.padEnd(16)} ${r.classification.padEnd(16)} distance=${String(r.distance).padEnd(3)} ${state.padEnd(8)} ${analysis.padEnd(22)} ${verification}`);
  }
  lines.push('');
  lines.push(`NEWER THAN THE PIN: ${newer.length} of ${versions.length}  ->  ${newer.map((r) => `${r.version} (${r.classification})`).join(', ') || 'none'}`);
  return {
    ok: true,
    exitCode: 0,
    verb: 'check',
    pin: current,
    registry: { source: registry.versions.source, durationMs: registry.versions.durationMs, count: versions.length, distTags: registry.distTags.tags },
    details: rows,
    newerThanPin: newer.map((r) => r.version),
    newer,
    text: lines.join('\n'),
  };
}

async function verbSnapshot(argv) {
  const pinned = pinnedState();
  const target = pinned.present
    ? { version: pinned.pin.version, enginePath: pinned.pin.enginePath, mode: 'pinned' }
    : (() => {
      const d = detectInstalledEngine();
      if (!d.enginePath) throw new CliError('no engine found on this machine, so there is nothing to snapshot', { exitCode: 2 });
      return { version: d.version, enginePath: d.enginePath, mode: 'detected' };
    })();

  if (!fs.existsSync(target.enginePath)) {
    throw new CliError(`the engine binary to snapshot does not exist: ${target.enginePath}`, { exitCode: 2 });
  }
  ensureDir(PATHS.baselineDir);
  const installRoot = pinned.present
    ? pinned.pin.installRoot
    : path.resolve(path.dirname(target.enginePath), '..', '..', '..', '..');

  // These two modules are owned by other workstreams and their entry points are already visible in
  // the tree: contract.mjs exports buildContract(installRoot), compose.mjs exports
  // buildTree({profile, bin, home, out, logDir}). We bind to those names explicitly rather than
  // guessing a generic run() signature, and an interface mismatch says exactly what is missing.
  const buildContract = await needExport('contract.mjs', ['buildContract']);
  const buildTree = await needExport('compose.mjs', ['buildTree']);

  const contractArtifact = await buildContract(installRoot);
  if (!contractArtifact || typeof contractArtifact !== 'object') {
    throw new CliError('lib/contract.mjs returned nothing usable: expected a contract object', { exitCode: 4 });
  }
  writeJsonAtomic(PATHS.baselineContract, contractArtifact);

  const treeResult = await buildTree({
    profile: 'web', bin: target.enginePath, home: PATHS.dshHome,
    out: PATHS.baselineTree, logDir: PATHS.logsDir,
  });
  const treeArtifact = treeResult && typeof treeResult === 'object' && 'artifact' in treeResult ? treeResult.artifact : treeResult;
  if (!treeArtifact || typeof treeArtifact !== 'object') {
    throw new CliError('lib/compose.mjs returned nothing usable: expected an artifact (or {artifact})', { exitCode: 4 });
  }
  writeJsonAtomic(PATHS.baselineTree, treeArtifact);
  const fatal = Boolean(treeResult && treeResult.fatal);
  if (treeArtifact.failure) {
    // An empty rows array is a refusal, not health (SPEC §tree.json) — say so and exit non-zero.
    throw new CliError(
      `the composed tree is a FAILURE, not an empty profile: ${treeArtifact.failure}\n`
      + `  tree.json was still written to ${rel(PATHS.baselineTree)} with rows=[]. exitCode=${treeArtifact.exitCode}`,
      { exitCode: 7 },
    );
  }

  // The pin's hashes are what `status` compares against disk, so a snapshot refreshes them. It does
  // NOT rewrite version/managed/predecessor: snapshot describes the pinned engine, it does not pin a
  // new one (that is promote's job).
  let pinRefreshed = null;
  if (pinned.present) {
    pinRefreshed = {
      ...pinned.pin,
      contractSha256: fileInfo(PATHS.baselineContract).sha256,
      treeSha256: fileInfo(PATHS.baselineTree).sha256,
    };
    writePin(pinRefreshed);
  }

  return {
    ok: true, exitCode: 0, verb: 'snapshot', target, fatal,
    contract: { path: PATHS.baselineContract, exists: fileInfo(PATHS.baselineContract).exists, sha256: fileInfo(PATHS.baselineContract).sha256, packageCount: contractArtifact.packageCount ?? null, packagesWithManifest: contractArtifact.packagesWithManifest ?? null, notes: contractArtifact.notes ?? null },
    tree: { path: PATHS.baselineTree, exists: fileInfo(PATHS.baselineTree).exists, sha256: fileInfo(PATHS.baselineTree).sha256, rows: Array.isArray(treeArtifact.rows) ? treeArtifact.rows.length : null, exitCode: treeArtifact.exitCode ?? null, patchedRowIds: treeArtifact.patchedRowIds ?? null, logDir: treeResult?.logDirAbs ? safeRelPath(treeResult.logDirAbs) : null },
    pinRefreshed: pinRefreshed ? { contractSha256: pinRefreshed.contractSha256, treeSha256: pinRefreshed.treeSha256 } : 'no pin present: snapshot described the detected engine only',
    text: [
      `dsh-update snapshot  (${target.mode} engine ${target.version})`,
      line('engine', target.enginePath),
      line('install root', installRoot),
      line('contract.json', `${rel(PATHS.baselineContract)} sha256=${fileInfo(PATHS.baselineContract).sha256 || 'NOT WRITTEN'}`),
      line('  packages', contractArtifact.packageCount ?? 'unknown'),
      line('tree.json', `${rel(PATHS.baselineTree)} sha256=${fileInfo(PATHS.baselineTree).sha256 || 'NOT WRITTEN'}`),
      line('  rows / exit', `${Array.isArray(treeArtifact.rows) ? treeArtifact.rows.length : 'unknown'} / ${treeArtifact.exitCode}`),
      line('pin', pinRefreshed ? `contractSha256 and treeSha256 refreshed from the files just written` : 'no pin present; run promote/declare a pin to record one'),
      line('engine started', 'no — this only ran `node <bin.js> --profile web --dump-config`, which is read-only'),
    ].join('\n'),
  };
}

async function verbFetch(argv) {
  const version = requireVersionArg('fetch', argv);
  if (fs.existsSync(path.join(vendorPrefixPath(version), ENGINE_REL))) {
    const existing = candidateState(version);
    throw new CliError(
      `vendor/prefix/${version} already contains an engine (${rel(path.join(vendorPrefixPath(version), ENGINE_REL))}).\n`
      + `  Nothing here deletes anything, so this fetch refuses to overwrite it.\n`
      + `  To re-fetch, a human must move that directory aside. It is not touched automatically.`,
      { exitCode: 5 },
    );
  }
  const res = await fetchCandidate(version);
  appendHistory({
    verb: 'fetch', version, fromVersion: readPin()?.version ?? null,
    result: res.ok ? 'ok' : 'fail', detail: res.ok ? `${res.command} (${res.durationMs} ms)` : res.error,
  });
  if (!res.ok) {
    throw new CliError(
      `fetch of ${version} FAILED: ${res.error}\n  command: ${res.command}\n  stdout: ${res.stdout.slice(-800) || '(none)'}\n  stderr: ${res.stderr.slice(-800) || '(none)'}`,
      { exitCode: 6 },
    );
  }
  return {
    ok: true, exitCode: 0, verb: 'fetch',
    result: { version, prefix: res.prefix, enginePath: res.enginePath, exitCode: res.exitCode, durationMs: res.durationMs, engineExists: res.engineExists, printedVersion: res.printedVersion, versionMatches: res.versionMatches, command: res.command },
    text: [
      `dsh-update fetch ${version}`,
      line('command', res.command),
      line('prefix', rel(res.prefix)),
      line('engine', `${rel(res.enginePath)} ${res.engineExists ? 'exists' : 'MISSING'}`),
      line('reports version', `${res.printedVersion} (${res.versionMatches ? 'matches the request' : 'DOES NOT MATCH'})`),
      line('exit / elapsed', `${res.exitCode} / ${res.durationMs} ms`),
      line('live install', 'untouched — this is the only npm install in the pipeline and it used --prefix'),
    ].join('\n'),
  };
}

async function verbAnalyze(argv) {
  const version = requireVersionArg('analyze', argv);
  const pinned = pinnedState();
  if (!pinned.present) throw new CliError('state/pin.json does not exist: analyze needs a baseline pin. Run `snapshot` first.', { exitCode: 2 });
  const cp = candidatePaths(version);
  ensureDir(cp.dir);
  const enginePath = path.join(vendorPrefixPath(version), ENGINE_REL);

  // Everything analyze needs, produced here so the verb is runnable end to end: our own consumption
  // (consumed.mjs), the baseline artifacts, the candidate's contract and composed tree, then the
  // diff. Each producer is invoked through the interface it actually ships.
  const consumedPath = path.join(cp.dir, 'consumed.json');
  // `DSH_HOME` is honoured here on purpose. A version-coupled config change CANNOT be judged against
  // the live config -- the live config is by definition not migrated yet, so every guard correctly
  // reports BREAKS and there is no way to tell "the fix is incomplete" from "the fix is not applied".
  // Pointing `DSH_HOME` at a staged home that carries the MIGRATED copies separates those two, and
  // that staged run is what `preflight` must judge. Defaults to the live home when unset.
  const consumedRun = runModuleCli('consumed.mjs', ['--root', REPO_ROOT, '--dsh-home', (process.env.DSH_HOME || PATHS.dshHome), '--out', consumedPath]);
  if (!consumedRun.ok) {
    throw new CliError(
      `lib/consumed.mjs failed (exit ${consumedRun.exitCode}), so there is nothing to cross-reference.\n`
      + `  command: ${consumedRun.command}\n  stderr: ${consumedRun.stderr.trim().slice(0, 1200) || '(empty)'}`,
      { exitCode: 4 },
    );
  }
  readArtifact(consumedPath, 'consumed.json', consumedRun);

  if (!fs.existsSync(PATHS.baselineContract)) {
    throw new CliError(`the baseline contract is absent (${rel(PATHS.baselineContract)}).\n  Run \`snapshot\` first: analyze compares the pinned engine against the candidate.`, { exitCode: 2 });
  }

  // The candidate's own artifacts. A candidate that has not been fetched cannot be described; say so.
  if (!fs.existsSync(enginePath)) {
    throw new CliError(
      `the candidate engine is not installed: ${rel(enginePath)} is absent.\n  Run \`fetch ${version}\` first.`,
      { exitCode: 2 },
    );
  }
  const buildContract = await needExport('contract.mjs', ['buildContract']);
  const buildTree = await needExport('compose.mjs', ['buildTree']);
  const candidateInstallRoot = vendorPrefixPath(version);
  writeJsonAtomic(cp.contract, await buildContract(candidateInstallRoot));
  const treeResult = await buildTree({
    profile: 'web', bin: enginePath, home: PATHS.dshHome, out: cp.tree, logDir: PATHS.logsDir,
  });
  const treeArtifact = treeResult && typeof treeResult === 'object' && 'artifact' in treeResult ? treeResult.artifact : treeResult;
  if (!treeArtifact || typeof treeArtifact !== 'object') {
    throw new CliError('lib/compose.mjs returned nothing usable for the candidate: expected an artifact (or {artifact})', { exitCode: 4 });
  }
  writeJsonAtomic(cp.tree, treeArtifact);
  if (treeArtifact.failure) {
    throw new CliError(
      `the candidate's composed tree is a FAILURE, not an empty profile: ${treeArtifact.failure}\n`
      + `  tree.json was written to ${rel(cp.tree)} with exitCode=${treeArtifact.exitCode}; the diff cannot be trusted.`,
      { exitCode: 7 },
    );
  }

  const diffRun = runModuleCli('diff.mjs', [
    '--baseline-contract', PATHS.baselineContract,
    '--candidate-contract', cp.contract,
    '--consumed', consumedPath,
    '--baseline-tree', PATHS.baselineTree,
    '--candidate-tree', cp.tree,
    '--out', cp.diff,
  ]);
  if (!diffRun.ok) {
    throw new CliError(
      `lib/diff.mjs failed (exit ${diffRun.exitCode}); no diff.json was produced.\n`
      + `  command: ${diffRun.command}\n  stderr: ${diffRun.stderr.trim().slice(0, 1500) || '(empty)'}`,
      { exitCode: 4 },
    );
  }
  const diffArtifact = readArtifact(cp.diff, 'diff.json', diffRun);

  // The human-readable report. report.mjs is another workstream and may not exist yet; a missing
  // report is reported as a gap, never as a silent success, and never blocks diff.json.
  let reportCall = null;
  let reportProblem = null;
  const reportFile = path.join(PATHS.libDir, 'report.mjs');
  if (fs.existsSync(reportFile)) {
    const reportRun = runModuleCli('report.mjs', ['--diff', cp.diff, '--out', cp.report]);
    reportCall = { command: reportRun.command, exitCode: reportRun.exitCode };
    if (!reportRun.ok || !fs.existsSync(cp.report)) {
      reportProblem = `lib/report.mjs exited ${reportRun.exitCode} and ${fs.existsSync(cp.report) ? 'did write' : 'did NOT write'} ${rel(cp.report)}: ${reportRun.stderr.trim().slice(0, 800) || '(no stderr)'}`;
    }
  } else {
    reportProblem = 'lib/report.mjs is not present yet — it is owned by another workstream, so report.md was not produced';
  }

  appendHistory({
    verb: 'analyze', version, fromVersion: pinned.pin.version, result: diffArtifact.verdict === 'BREAKS' ? 'breaks' : 'ok',
    detail: `verdict ${diffArtifact.verdict}; counts ${JSON.stringify(diffArtifact.counts || {})}; diff ${rel(cp.diff)}`,
  });

  return {
    ok: true, exitCode: 0, verb: 'analyze', version,
    consumed: { path: consumedPath, command: consumedRun.command },
    contract: { path: cp.contract, sha256: fileInfo(cp.contract).sha256, packageCount: readJson(cp.contract, {}).packageCount ?? null },
    tree: { path: cp.tree, rows: Array.isArray(treeArtifact.rows) ? treeArtifact.rows.length : null, exitCode: treeArtifact.exitCode ?? null },
    diff: { path: cp.diff, verdict: diffArtifact.verdict ?? null, counts: diffArtifact.counts ?? null, findings: diffArtifact.findings?.length ?? null, command: diffRun.command, call: null },
    report: { path: cp.report, exists: fs.existsSync(cp.report), problem: reportProblem, call: reportCall },
    text: [
      `dsh-update analyze ${version}`,
      line('consumed.json', `${rel(consumedPath)}  (${consumedRun.command})`),
      line('candidate contract', `${rel(cp.contract)}  ${readJson(cp.contract, {}).packageCount ?? '?'} packages, sha256=${fileInfo(cp.contract).sha256}`),
      line('candidate tree', `${rel(cp.tree)}  ${Array.isArray(treeArtifact.rows) ? treeArtifact.rows.length : '?'} rows, dump exit ${treeArtifact.exitCode}`),
      line('diff.json', `${rel(cp.diff)}  VERDICT ${diffArtifact.verdict ?? 'unknown'}  counts ${JSON.stringify(diffArtifact.counts || {})}`),
      line('findings', `${diffArtifact.findings?.length ?? 0} (${(diffArtifact.consumed?.unverified?.length ?? 0)} consumed references could not be resolved)`),
      line('report.md', reportProblem ? `NOT PRODUCED — ${reportProblem}` : rel(cp.report)),
    ].join('\n'),
  };
}

async function verbVerify(argv) {
  const version = requireVersionArg('verify', argv);
  const full = argv.includes('--full');
  const pinned = pinnedState();
  const cp = candidatePaths(version);
  const enginePath = path.join(vendorPrefixPath(version), ENGINE_REL);
  if (!fs.existsSync(enginePath)) {
    throw new CliError(
      `the candidate engine is not installed: ${rel(enginePath)} is absent.\n  Run \`fetch ${version}\` first; nothing was verified.`,
      { exitCode: 2 },
    );
  }
  // verify.mjs is another workstream. It ships as a CLI (every lib module runs standalone per the
  // SPEC) and may also export an entry point; a missing module is an actionable gap, not a crash.
  const args = [
    '--version', version,
    '--engine', enginePath,
    '--contract', cp.contract,
    '--tree', cp.tree,
    '--diff', cp.diff,
    '--out', cp.verify,
    '--logs-dir', PATHS.logsDir,
    // Same staging rule as `analyze`: honour `DSH_HOME` so verify can be run against an isolated,
    // MIGRATED home before anything is applied to the live one. Note verify builds its OWN isolated
    // copy from this source home, so this names the config under test, not the engine's runtime home.
    '--dsh-home', (process.env.DSH_HOME || PATHS.dshHome),
  ];
  if (full) args.push('--full');
  const file = path.join(PATHS.libDir, 'verify.mjs');
  let call = null;
  if (!fs.existsSync(file)) {
    throw new CliError(
      `lib/verify.mjs is not present yet — it is owned by ${VERB_OWNER['lib/verify.mjs']}, not by this one.\n`
      + `  This verb cannot run until that file exists at ${safeRelPath(file)}.\n`
      + `  Nothing was verified and nothing was written.`,
      { exitCode: 4 },
    );
  }
  const run = runModuleCli('verify.mjs', args, { timeoutMs: full ? 1800000 : 900000 });
  call = { command: run.command, exitCode: run.exitCode };
  const verifyRead = readJsonChecked(cp.verify, null);
  const verify = verifyRead.value;
  const gates = Array.isArray(verify?.gates) ? verify.gates : null;
  const failed = gates ? gates.filter((g) => g.ran && g.ok === false) : [];
  const notRun = gates ? gates.filter((g) => g.ran === false) : [];
  const text = [
    `dsh-update verify ${version}${full ? ' --full' : ''}`,
    line('command', run.command),
    line('exit', String(run.exitCode)),
    verify
      ? line('verify.json', `${rel(cp.verify)}  pass=${verify.pass}  ${gates ? `${gates.filter((g) => g.ran && g.ok).length}/${gates.length} gates ok` : 'no gates array'}`)
      : line('verify.json', `NOT WRITTEN — ${verifyRead.reason}`),
  ];
  if (failed.length) text.push(line('failed gates', failed.map((g) => `${g.id} ${g.name}: ${g.detail}`).join(' | ')));
  if (notRun.length) text.push(line('did not run', notRun.map((g) => `${g.id} ${g.name}: ${g.detail}`).join(' | ')));
  if (run.stderr.trim()) text.push(line('stderr', run.stderr.trim().split('\n').slice(-12).join('\n                        ')));
  return {
    ok: true, exitCode: verify && verify.pass === true ? 0 : 7, verb: 'verify', version, full,
    verify: {
      path: cp.verify, exists: fileInfo(cp.verify).exists, pass: verify ? verify.pass === true : null,
      gates, failedGates: failed.length, gatesNotRun: notRun.length, call,
    },
    text: text.join('\n'),
  };
}

/** Compute — never write — the exact effect of promoting `version`. Used by plan and by promote. */
function promotionEffect(version) {
  const cfg = readConfigForPlan();
  const pinned = pinnedState();
  if (!pinned.present) throw new CliError('state/pin.json does not exist, so promote has nothing to succeed. Run `snapshot` first.', { exitCode: 2 });
  const newRoot = vendorPrefixPath(version);
  const newEngine = path.join(newRoot, ENGINE_REL);
  const state = candidateState(version);
  return {
    version,
    windowsJson: {
      path: cfg.file,
      exists: fs.existsSync(cfg.file),
      key: 'dshInstall',
      oldValue: cfg.current,
      newValue: newRoot,
      oldPresent: cfg.current !== null,
    },
    pin: {
      path: PATHS.pin,
      exists: fs.existsSync(PATHS.pin),
      oldValue: pinned.pin.version,
      newValue: version,
      managedOld: pinned.pin.managed,
      managedNew: true,
      enginePathOld: pinned.pin.enginePath,
      enginePathNew: newEngine,
      installRootNew: newRoot,
      contractSha256Old: pinned.pin.contractSha256 ?? null,
      contractSha256New: state.contract.sha256,
      predecessorNew: 'the entire current pin object is copied into predecessor',
    },
    enginePresent: state.prefix,
    enginePath: newEngine,
    candidate: state,
    pinned,
    cfg,
  };
}

async function verbPlan(argv) {
  const version = requireVersionArg('plan', argv);
  const eff = promotionEffect(version);
  const gate = promoteGate(version, eff);
  const lines = [];
  lines.push(`dsh-update plan ${version} — this is what \`promote ${version}\` would change. Nothing was written.`);
  lines.push('');
  lines.push('GATES (all must pass before promote will act)');
  for (const g of gate.conditions) {
    lines.push(`  ${g.ok ? 'PASS' : 'FAIL'}  ${g.name}`);
    lines.push(`        ${g.detail}`);
  }
    lines.push(`  => promote would ${gate.ok ? 'PROCEED' : 'REFUSE'}`);
  lines.push('');
  lines.push('FILES THAT WOULD BE WRITTEN');
  lines.push(`  1. ${rel(eff.windowsJson.path)}  (currently ${eff.windowsJson.exists ? 'exists' : 'ABSENT'})`);
  lines.push(`       ${eff.windowsJson.key}:`);
  lines.push(`         old: ${eff.windowsJson.oldPresent ? eff.windowsJson.oldValue : '(key absent)'}`);
  lines.push(`         new: ${eff.windowsJson.newValue}`);
  lines.push(`       backed up first to ${rel(eff.windowsJson.path)}.bak-dsh-update-<UTC> then replaced atomically`);
  lines.push(`  2. ${rel(eff.pin.path)}  (currently ${eff.pin.exists ? 'exists' : 'ABSENT'})`);
  lines.push(`       version:        ${eff.pin.oldValue}  ->  ${eff.pin.newValue}`);
  lines.push(`       managed:        ${eff.pin.managedOld}  ->  true`);
  lines.push(`       enginePath:     ${eff.pin.enginePathOld}  ->  ${eff.pin.enginePathNew}`);
  lines.push(`       installRoot:    ->  ${eff.pin.installRootNew}`);
  lines.push(`       contractSha256: ${eff.pin.contractSha256Old ?? '(none)'}  ->  ${eff.pin.contractSha256New ?? '(candidate contract.json is absent)'}`);
  lines.push(`       predecessor:    ${eff.pin.predecessorNew}`);
  lines.push(`  3. ${rel(PATHS.historyFile)}  (append one row only)`);
  lines.push(`  4. ${rel(PATHS.logsDir)}  (one invocation record)`);
  lines.push('');
  lines.push('FILES THAT WOULD NOT BE TOUCHED');
  lines.push(`  ${rel(path.join(vendorPrefixPath(version), ENGINE_REL))}  ${eff.enginePresent ? '(candidate engine, present)' : '(candidate engine — ABSENT, run `fetch ' + version + '`)'}`);
  lines.push('  the running engine process — promote never starts, stops or restarts anything');
  lines.push('');
  lines.push('EFFECT TIMING: the change takes effect at the NEXT engine boot. This command and promote do not restart it.');
  if (gate.ok && !eff.enginePresent) lines.push('WARNING: the gates pass but the candidate engine binary is missing; check that verify ran against this prefix.');
  return {
    ok: true, exitCode: 0, verb: 'plan', version,
    wouldPromote: gate.ok,
    gates: gate.conditions,
    effect: {
      windowsJson: eff.windowsJson, pin: eff.pin,
      history: PATHS.historyFile, logs: PATHS.logsDir,
      enginePath: eff.enginePath, enginePresent: eff.enginePresent,
    },
    text: lines.join('\n'),
  };
}

/** The three SPEC conditions for promote, evaluated and reported one by one. */
function promoteGate(version, eff, opts = {}) {
  const cp = candidatePaths(version);
  const verify = readJson(cp.verify, null);
  const verifyRead = readJsonChecked(cp.verify, null);
  const contractSha = fileInfo(cp.contract).sha256;
  const diff = readJson(cp.diff, null);
  const diffRead = readJsonChecked(cp.diff, null);
  const pinVersion = eff.pinned.pin.version;
  const cmp = classify(pinVersion, version, []);
  const strictlyNewer = cmp.newerThanPin === true;

  const c1detail = !verify
    ? `state/candidates/${version}/verify.json is absent (${verifyRead.reason}) — run \`verify ${version}\` first`
    : verify.pass !== true
      ? `verify.json exists but pass=${JSON.stringify(verify.pass)}`
      : !contractSha
        ? `verify.json has contractSha256=${verify.contractSha256} but state/candidates/${version}/contract.json is absent, so the hashes cannot be compared`
        : verify.contractSha256 !== contractSha
          ? `verify.json was produced for contractSha256=${verify.contractSha256} but the candidate contract on disk is ${contractSha} — the contract changed after verification, so that verify is stale`
          : `verify.json pass=true and contractSha256=${contractSha} matches the candidate contract on disk`;

  const c2detail = !diff
    ? `state/candidates/${version}/diff.json is absent (${diffRead.reason}) — run \`analyze ${version}\` first`
    : diff.verdict === 'BREAKS'
      ? `diff.json verdict is BREAKS`
      : `diff.json verdict is ${diff.verdict ?? '(missing verdict field)'}`;

  const c3detail = `pin is ${pinVersion}, candidate is ${version} (${cmp.classification})`;

  // ── condition 4: the session-format one-way door ─────────────────────────────────────────────
  //
  // WHY THIS IS A GATE AND NOT A WARNING. The first boot on a candidate that writes a NEWER session
  // format makes every log it writes unreadable to the engine being replaced, so `rollback` stops
  // being a complete undo. Measured 2026-09-28: the live home holds 1,253 session files, all
  // `session.v3.jsonl.zstd`; `0.1.7-rc.1`/`0.1.7-rc.2`/`0.2.0-rc.1` declare `currentVersion: 4` and
  // ship only a v3->v4 codec, which CONSUMES the old logs into the new format -- the same loss seen
  // from the other end. `0.1.5-rc.3` still writes v3.
  //
  // It is deliberately possible to proceed anyway, because the owner may WANT the newer engine, and a
  // gate that cannot be passed is a gate that gets deleted. But it must be a RECORDED decision:
  // `--accept-session-format-upgrade` writes an acknowledgment into the pin and the history, so the
  // audit trail says who accepted an irreversible step and when. That is not the same thing as a
  // bypass: nothing here skips a check, it records a human's answer to the check.
  const g8 = Array.isArray(verify?.gates) ? verify.gates.find((g) => g && g.id === 'G8') : null;
  const accepted = opts.acceptSessionFormat === true;
  let c4ok;
  let c4detail;
  if (!verify) {
    c4ok = false;
    c4detail = 'no verify.json, so the session-format gate (G8) could not be read — run `verify` first';
  } else if (!g8) {
    c4ok = false;
    c4detail = `verify.json carries no G8 gate (it has ${(verify.gates || []).length} gate(s): ${(verify.gates || []).map((g) => g.id).join(', ') || 'none'}) — re-run \`verify ${version}\` with the current lib/verify.mjs`;
  } else if (g8.ran !== true) {
    c4ok = false;
    c4detail = `G8 did not run (${g8.detail || 'no detail'}) — an unrun gate is not a pass`;
  } else if (g8.ok === true) {
    c4ok = true;
    c4detail = `G8 ok: ${g8.detail}`;
  } else if (accepted) {
    c4ok = true;
    c4detail = `ACCEPTED DELIBERATELY (--accept-session-format-upgrade): ${g8.detail}`;
  } else {
    c4ok = false;
    c4detail = `G8 FAILED and no acknowledgment was given: ${g8.detail}  `
      + 'If you intend to take the format upgrade anyway, re-run with --accept-session-format-upgrade; '
      + 'that records the decision in the pin and the history rather than skipping the check.';
  }

  const conditions = [
    { id: 1, name: 'a passing verify exists for this exact contract', ok: Boolean(verify && verify.pass === true && contractSha && verify.contractSha256 === contractSha), detail: c1detail },
    { id: 2, name: 'the diff verdict is not BREAKS', ok: Boolean(diff && diff.verdict !== 'BREAKS'), detail: c2detail },
    { id: 3, name: 'the candidate is strictly newer than the pin', ok: strictlyNewer, detail: c3detail },
    { id: 4, name: 'the session-format upgrade is either absent or explicitly accepted', ok: c4ok, detail: c4detail },
  ];
  return { ok: conditions.every((c) => c.ok), conditions, verify, diff, sessionFormat: g8 ?? null, sessionFormatAccepted: accepted && g8 != null && g8.ok !== true };
}

async function verbPromote(argv) {
  const version = requireVersionArg('promote', argv);
  const acceptSessionFormat = argv.includes('--accept-session-format-upgrade');
  const eff = promotionEffect(version);
  const gate = promoteGate(version, eff, { acceptSessionFormat });
  if (!gate.ok) {
    const failed = gate.conditions.filter((c) => !c.ok);
    appendHistory({
      verb: 'promote', version, fromVersion: eff.pinned.pin.version, result: 'refused',
      detail: failed.map((c) => `condition ${c.id} (${c.name}) failed: ${c.detail}`).join(' | '),
    });
    const text = [
      `dsh-update promote ${version} — REFUSED. Nothing was written.`,
      ...gate.conditions.map((c) => `  ${c.ok ? 'PASS' : 'FAIL'}  condition ${c.id}: ${c.name}\n        ${c.detail}`),
      '',
      'Condition 1 — a passing verify for this exact contract — has NO bypass flag. Skipping it is a',
      'code change, not a flag. Condition 4 DOES have one, `--accept-session-format-upgrade`, and that',
      'is not a bypass: it records a deliberate decision in the pin and the history rather than skipping',
      'the check, because the session-format upgrade is the one step a rollback cannot undo.',
    ].join('\n');
    return { ok: false, exitCode: 8, verb: 'promote', version, refused: true, failedConditions: failed.map((c) => c.id), gates: gate.conditions, text };
  }

  // ── the write. Outside dsh-update/ exactly twice: the knob and nothing else. ──
  const kv = typeof gate.diff?.verdict === 'string' ? gate.diff.verdict : null;
  const cfg = eff.cfg;
  cfg.cfg.dshInstall = eff.windowsJson.newValue;
  const cfgWrite = backupAndWrite(eff.windowsJson.path, cfg.cfg, { indent: cfg.indent });

  const previousPin = eff.pinned.pin;
  const newPin = {
    version,
    installRoot: vendorPrefixPath(version),
    enginePath: eff.enginePath,
    managed: true,
    pinnedAt: new Date().toISOString(),
    by: hostName(),
    contractSha256: gate.verify.contractSha256 ?? eff.candidate.contract.sha256 ?? null,
    treeSha256: gate.verify.treeSha256 ?? fileInfo(candidatePaths(version).tree).sha256 ?? null,
    predecessor: previousPin,
    // Recorded ONLY when the operator deliberately accepted an irreversible session-format upgrade
    // (gate 4, `--accept-session-format-upgrade`). null means the candidate writes the same format as
    // the logs already on disk, or no format gate applied. This exists so the audit trail answers
    // "who accepted the one-way door, and when" without a human having to read a log line.
    sessionFormatUpgrade: gate.sessionFormatAccepted
      ? {
        accepted: true,
        at: new Date().toISOString(),
        by: hostName(),
        gate: 'G8',
        detail: gate.sessionFormat?.detail ?? null,
      }
      : null,
  };
  writePin(newPin);

  appendHistory({
    verb: 'promote', version, fromVersion: previousPin.version, result: 'ok',
    detail: `dshInstall ${eff.windowsJson.oldPresent ? eff.windowsJson.oldValue : '(absent)'} -> ${eff.windowsJson.newValue}; pin ${previousPin.version} -> ${version}; diff verdict ${kv ?? 'unknown'}; verify contractSha256 ${gate.verify.contractSha256}; backup ${cfgWrite.backup ? rel(cfgWrite.backup) : 'none needed'}; engine NOT restarted${gate.sessionFormatAccepted ? '; SESSION-FORMAT UPGRADE ACCEPTED DELIBERATELY (gate G8) — rolling back past this point cannot recover sessions written by the new engine' : ''}`,
  });

  const text = [
    `dsh-update promote ${version} — DONE.`,
    line('gate 1', gate.conditions[0].detail),
    line('gate 2', gate.conditions[1].detail),
    line('gate 3', gate.conditions[2].detail),
    `  diff verdict: ${kv ?? 'unknown'}${kv === 'RISKY' ? '  <-- RISKY: the analysis found non-blocking risk, read the report' : ''}`,
    '',
    line('windows.json', `${rel(eff.windowsJson.path)}  dshInstall ${eff.windowsJson.oldPresent ? eff.windowsJson.oldValue : '(absent)'} -> ${eff.windowsJson.newValue}`),
    line('backup', cfgWrite.backup ? rel(cfgWrite.backup) : `no backup needed (${cfgWrite.note})`),
    line('pin.json', `${rel(PATHS.pin)}  ${previousPin.version} -> ${version}, managed=true, predecessor recorded`),
    line('history', `${rel(PATHS.historyFile)}  one row appended`),
    '',
    '  >>> THE CHANGE TAKES EFFECT AT THE NEXT ENGINE BOOT.',
    '  >>> This command did NOT restart the engine and will not. A running engine serves the session',
    '  >>> that ran this promote; restarting it from here would kill that session. The watchdog will',
    '  >>> start the pinned version the next time an engine is (re)started by a human or by a reboot.',
    '',
    `  To undo: \`bin/dsh-update.ps1 rollback\` (restores ${previousPin.version} and the previous dshInstall).`,
  ].join('\n');
  return { ok: true, exitCode: 0, verb: 'promote', version, pin: newPin, windowsJson: { path: eff.windowsJson.path, oldValue: eff.windowsJson.oldValue, newValue: eff.windowsJson.newValue, backup: cfgWrite.backup, existed: cfgWrite.existed }, gates: gate.conditions, text };
}

async function verbRollback() {
  const pinned = pinnedState();
  if (!pinned.present) throw new CliError('state/pin.json does not exist, so there is nothing to roll back.', { exitCode: 2 });
  const predecessor = pinned.pin.predecessor;
  if (!predecessor || typeof predecessor !== 'object' || !predecessor.version) {
    throw new CliError(
      `there is no predecessor to roll back to: ${rel(PATHS.pin)} has predecessor=${JSON.stringify(pinned.pin.predecessor)}.\n`
      + `  A pin records a predecessor only when it was written by \`promote\`. Nothing was changed.`,
      { exitCode: 8 },
    );
  }
  const v = validatePin(predecessor);
  if (!v.ok) {
    throw new CliError(
      `the recorded predecessor does not match the pin schema and will not be restored: ${v.problems.join('; ')}\n`
      + `  Refusing rather than writing a pin the rest of the pipeline cannot read. Nothing was changed.`,
      { exitCode: 2 },
    );
  }
  const cfg = readConfigForPlan();
  const restoreRoot = predecessor.managed ? predecessor.installRoot : null;
  const oldValue = cfg.current;
  if (restoreRoot) {
    cfg.cfg.dshInstall = restoreRoot;
  } else {
    // The predecessor was unmanaged (npx): the knob must go back to "not configured", which is what
    // the launcher's Get-ConfigValue treats as absent.
    if ('dshInstall' in cfg.cfg) delete cfg.cfg.dshInstall;
  }
  const cfgWrite = backupAndWrite(cfg.file, cfg.cfg, { indent: cfg.indent });
  const restoredEngine = predecessor.enginePath;
  // A missing restored engine is not fatal — rollback restores the RECORD, and refusing here would
  // strand the pin on a bad candidate — but it is reported loudly below.
  const restoredEngineExists = Boolean(restoredEngine) && fs.existsSync(restoredEngine);
  writePin({
    ...predecessor,
    pinnedAt: new Date().toISOString(),
    by: hostName(),
    predecessor: null,
  });
  appendHistory({
    verb: 'rollback', version: predecessor.version, fromVersion: pinned.pin.version, result: 'ok',
    detail: `dshInstall ${oldValue ?? '(absent)'} -> ${restoreRoot ?? '(key removed; unmanaged predecessor)'}; pin ${pinned.pin.version} -> ${predecessor.version}; engine NOT restarted`,
  });
  const text = [
    'dsh-update rollback — DONE.',
    line('pin.json', `${rel(PATHS.pin)}  ${pinned.pin.version} -> ${predecessor.version}`),
    line('windows.json', `${rel(cfg.file)}  dshInstall ${oldValue ?? '(absent)'} -> ${restoreRoot ?? '(key removed)'}`),
    line('backup', cfgWrite.backup ? rel(cfgWrite.backup) : `no backup needed (${cfgWrite.note})`),
    line('restored engine', `${restoredEngine} ${restoredEngineExists ? 'exists' : 'MISSING ON DISK — the pin is restored but that install is gone'}`),
    line('history', `${rel(PATHS.historyFile)}  one row appended`),
    '',
    '  >>> THE CHANGE TAKES EFFECT AT THE NEXT ENGINE BOOT.',
    '  >>> Nothing was restarted. This session is still running.',
  ].join('\n');
  return {
    ok: true, exitCode: 0, verb: 'rollback',
    restored: { version: predecessor.version, installRoot: predecessor.installRoot, enginePath: restoredEngine, engineExists: restoredEngineExists, managed: predecessor.managed },
    windowsJson: { path: cfg.file, oldValue, newValue: restoreRoot, backup: cfgWrite.backup },
    text,
  };
}

async function verbReport(argv) {
  const version = requireVersionArg('report', argv);
  const cp = candidatePaths(version);
  const state = candidateState(version);
  const diff = readJson(cp.diff, null);
  const verify = readJson(cp.verify, null);
  const lines = [];
  lines.push(`dsh-update report ${version}`);
  lines.push(line('report.md', state.report ? `${rel(cp.report)} (${fileInfo(cp.report).bytes} bytes, ${ago(fileInfo(cp.report).mtime)})` : (state.diff ? `ABSENT — the analysis ran but no report was written (lib/report.mjs is another workstream; see \`analyze ${version}\`)` : `ABSENT — run \`analyze ${version}\` (${state.diffProblem || 'diff.json is absent'})`)));
  lines.push(line('diff verdict', state.diff ? `${state.diff.verdict} (${state.diff.generatedAt || 'undated'})` : `ABSENT — ${state.diffProblem || 'not analyzed'}`));
  if (state.diff && state.diff.counts) lines.push(line('counts', Object.entries(state.diff.counts).map(([k, v]) => `${k}=${v}`).join('  ')));
  lines.push(line('verify', state.verify ? `${state.verify.pass ? 'PASS' : 'FAIL'} (${state.verify.generatedAt || 'undated'})` : `ABSENT — ${state.verifyProblem || 'not verified'}`));
  if (state.verify && state.verify.gates) {
    for (const g of state.verify.gates) lines.push(line(`  gate ${g.id}`, `${g.ran ? (g.ok ? 'ok' : 'FAILED') : 'did not run'} — ${g.detail}`));
  }
  lines.push(line('candidate contract', state.contract.exists ? `sha256=${state.contract.sha256}` : 'ABSENT'));
  if (verify && state.contract.exists && verify.contractSha256 !== state.contract.sha256) {
    lines.push(line('STALE', `verify.json was produced for contract ${verify.contractSha256}, which is not the contract on disk (${state.contract.sha256}) — that verify does not cover this candidate`));
  }
  return {
    ok: true, exitCode: 0, verb: 'report', version,
    reportPath: cp.report, reportExists: state.report,
    verdict: diff?.verdict ?? null, counts: diff?.counts ?? null,
    verifyPass: verify ? verify.pass === true : null,
    gates: verify?.gates ?? null,
    text: lines.join('\n'),
  };
}

// ── patch-effect ────────────────────────────────────────────────────────────
//
// WHY THIS IS A SEPARATE VERB AND NOT PART OF `analyze`
//
// The first real run of `analyze` (2026-09-23) reported BREAKS=2 for a candidate that breaks
// nothing, claiming our override "is applied to nothing" on `cordis.patch.yml:248`. The patch did
// apply. The detector had asserted on the engine's `patched by` comment, which is emitted only for
// SOME patch shapes: an entry that sets only `disabled: true` applies perfectly and carries no
// annotation at all.
//
// So this verb answers the patch question on evidence that cannot produce that error: our own patch
// file plus the engine's own composed tree AND the engine's own `--dump-default-config` tree (the
// same tree with our layer removed). It asserts an EFFECT, never a comment. It also catches the
// class that once cost a live incident (PAIN P48): a patch restates a row's whole `config`, so a key
// upstream newly adds to that row's default is silently swallowed.
//
// The unpatched arms are generated here if they are missing, because an arm that is absent would
// quietly weaken the check. When an arm genuinely cannot be produced, that is reported as
// `unverified` — never as a pass.
async function verbPatchEffect(argv) {
  const version = requireVersionArg('patch-effect', argv);
  const cp = candidatePaths(version);
  const pin = readPin();
  const flagValue = (name) => {
    const i = argv.indexOf(name);
    return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : null;
  };
  const profile = flagValue('--profile') || 'web';
  const explicitLayer = flagValue('--layer');

  const lines = [];
  lines.push(`dsh-update patch-effect ${version} (profile ${profile})`);

  const baselineComposed = PATHS.baselineTree;
  const candidateComposed = cp.tree;
  for (const [label, p] of [['baseline composed', baselineComposed], ['candidate composed', candidateComposed]]) {
    if (!fs.existsSync(p)) {
      throw new CliError(
        `the ${label} tree is absent (${safeRelPath(p)}).\n`
        + `  Run \`snapshot\` and then \`analyze ${version}\` first — patch effect is compared against those trees.`,
        { exitCode: 2 },
      );
    }
  }

  const baselineDefault = path.join(PATHS.baselineDir, 'tree-default.json');
  const candidateDefault = path.join(path.dirname(cp.tree), 'tree-default.json');

  let layers = explicitLayer ? [explicitLayer] : null;
  if (!layers) {
    const home = process.env.DSH_HOME || path.join(process.env.USERPROFILE || '', '.dsh');
    const discovered = path.join(home, 'profiles', profile, 'cordis.patch.yml');
    if (!fs.existsSync(discovered)) {
      throw new CliError(
        `no patch layer found for profile ${profile} at ${safeRelPath(discovered)}.\n`
        + '  Pass --layer <path> to name the layer explicitly. With no layer there is nothing to check, '
        + 'and an empty result would look like health.',
        { exitCode: 2 },
      );
    }
    layers = [discovered];
  }

  // The unpatched arm is the whole point of the comparison. Generate it when missing.
  const compose = path.join(PATHS.libDir, 'compose.mjs');
  const arms = [
    { p: baselineDefault, bin: pin.enginePath, label: 'baseline DEFAULT (unpatched)' },
    { p: candidateDefault, bin: path.join(vendorPrefixPath(version), ENGINE_REL), label: 'candidate DEFAULT (unpatched)' },
  ];
  for (const a of arms) {
    if (fs.existsSync(a.p)) { lines.push(line(a.label, `present — ${safeRelPath(a.p)}`)); continue; }
    if (!fs.existsSync(a.bin)) {
      lines.push(line(a.label, `NOT GENERATED — no engine at ${safeRelPath(a.bin)}; the new-upstream-default check will report unverified`));
      continue;
    }
    const r = spawnSync(process.execPath, [
      compose, '--profile', profile, '--default-config',
      '--bin', a.bin, '--out', a.p, '--log-dir', PATHS.logsDir,
    ], { encoding: 'utf8', timeout: 180000 });
    if (r.status !== 0) {
      lines.push(line(a.label, `FAILED to generate (exit ${r.status}): ${(r.stderr || '').trim().split('\n')[0] || 'no diagnostic'}`));
    } else {
      lines.push(line(a.label, `generated — ${safeRelPath(a.p)}`));
    }
  }

  const out = path.join(path.dirname(cp.tree), 'patch-effect.json');
  const args = [
    path.join(PATHS.libDir, 'patch-effect.mjs'),
    '--profile', profile,
    '--baseline-composed', baselineComposed,
    '--candidate-composed', candidateComposed,
    '--baseline-default', baselineDefault,
    '--candidate-default', candidateDefault,
    '--out', out,
  ];
  for (const l of layers) args.push('--layer', l);
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', timeout: 180000 });
  const report = readJson(out, null);
  if (!report) {
    throw new CliError(
      `patch-effect did not produce an artifact (exit ${r.status}).\n  ${(r.stderr || r.stdout || '').trim().split('\n').slice(0, 4).join('\n  ')}`,
      { exitCode: 2 },
    );
  }

  lines.push(line('verdict', `${report.verdict}   BREAKS=${report.counts.BREAKS}  RISKY=${report.counts.RISKY}  INFO=${report.counts.INFO}`));
  lines.push(line('layer(s)', layers.map((l) => safeRelPath(l)).join(', ')));
  for (const t of report.targets) {
    const marks = t.checks.map((c) => `${c.what}:${c.ok === true ? 'ok' : c.ok === null ? 'n/a' : 'FAIL'}`).join(' ');
    const note = t.checks.some((c) => c.what === 'disabled' && c.ok === true && c.annotation === null)
      ? '  (no `patched by` annotation — asserted on the composed value, not a comment)'
      : '';
    lines.push(line(`  ${t.verdict} ${t.id}`, `${marks}${note}`));
  }
  for (const f of report.findings) {
    lines.push(line(`  [${f.severity}] ${f.class} ${f.subject}`, f.evidence));
    lines.push(line('    why', f.why));
    lines.push(line('    do', f.suggested));
  }
  lines.push(line('unverified', report.unverified.length === 0
    ? 'nothing — every comparison in this run was actually made'
    : `${report.unverified.length} comparison(s) NOT made (this is not a pass): ${report.unverified.map((u) => u.ref).slice(0, 6).join(', ')}${report.unverified.length > 6 ? ', …' : ''}`));
  lines.push(line('artifact', safeRelPath(out)));

  appendHistory({
    verb: 'patch-effect', version, fromVersion: pin?.version ?? null, result: report.verdict,
    detail: `BREAKS=${report.counts.BREAKS} RISKY=${report.counts.RISKY} INFO=${report.counts.INFO}; profile ${profile}; layer(s) ${layers.join(', ')}`,
  });

  return {
    ok: report.counts.BREAKS === 0,
    // Non-zero only on a real BREAKS. RISKY is a thing to read, not a stop signal.
    exitCode: report.counts.BREAKS > 0 ? 1 : 0,
    verb: 'patch-effect', version, profile,
    verdict: report.verdict, counts: report.counts,
    targets: report.targets, findings: report.findings, unverified: report.unverified,
    artifact: out,
    text: lines.join('\n'),
  };
}

// ── preset-gate ─────────────────────────────────────────────────────────────
//
// WHY THIS GATE IS NOT OPTIONAL, all measured 2026-09-28:
//   * agent presets contribute ZERO rows to `--dump-config`, so the composed-tree diff (G1/G2/G3)
//     cannot see them at all;
//   * a HEADLESS run does not load a preset either. Three staged DSH_HOMEs against a candidate
//     engine, one of which had a preset row naming `@deepseek-ai/dsh-package-that-does-not-exist-xyz`,
//     ALL exited 0 with empty stderr. The `headless` profile's own composition has no preset-service
//     row in it (95 rows), so presets are never resolved there — which means gate G5, the pipeline's
//     strongest end-to-end check, is blind to preset breakage;
//   * on the 0.1.7 line local preset DIRECTORIES stop being read anywhere in the install, so the
//     mechanism itself changes.
//
// So STATIC resolution of every `name:` in every preset file is the only detector for preset
// breakage, and it is what stands between an upgrade and a silently missing persona.
//
// A note for whoever maintains this: the row count that matters is NOT the root count. A group row
// (`group: true`) carries its member rows as the elements of its `config:` sequence, and the row that
// breaks on the 0.1.7 line is nested inside `delegation`. A gate that reads only root rows reports a
// clean result and misses the very breakage it exists for.
async function verbPresetGate(argv) {
  const version = requireVersionArg('preset-gate', argv);
  const cp = candidatePaths(version);
  const lines = [];
  lines.push(`dsh-update preset-gate ${version}`);
  if (!fs.existsSync(cp.contract)) {
    throw new CliError(
      `the candidate contract is absent (${safeRelPath(cp.contract)}).\n  Run \`analyze ${version}\` first — preset names are resolved against that contract.`,
      { exitCode: 2 },
    );
  }
  const home = process.env.DSH_HOME || path.join(process.env.USERPROFILE || '', '.dsh');
  const out = path.join(path.dirname(cp.contract), 'preset-gate.json');
  const args = [
    path.join(PATHS.libDir, 'preset-gate.mjs'),
    '--candidate-contract', cp.contract,
    '--root', REPO_ROOT,
    '--dsh-home', home,
    '--out', out,
  ];
  if (fs.existsSync(PATHS.baselineContract)) args.push('--baseline-contract', PATHS.baselineContract);
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', timeout: 180000 });
  const report = readJson(out, null);
  if (!report) {
    throw new CliError(
      `preset-gate did not produce an artifact (exit ${r.status}).\n  ${(r.stderr || r.stdout || '').trim().split('\n').slice(0, 4).join('\n  ')}`,
      { exitCode: 2 },
    );
  }
  const counts = report.counts || {};
  lines.push(line('verdict', `${report.verdict}   ${Object.entries(counts).map(([k, v]) => `${k}=${v}`).join('  ')}`));
  lines.push(line('preset files', `${Array.isArray(report.presets) ? report.presets.length : 'unknown'}`));
  for (const f of (report.findings || [])) {
    lines.push(line(`  [${f.severity}] ${f.class} ${f.subject}`, f.evidence));
    if (f.suggested) lines.push(line('    do', f.suggested));
  }
  const unverified = report.unverified || [];
  lines.push(line('unverified', unverified.length === 0
    ? 'nothing — every name in every preset file was resolved'
    : `${unverified.length} name(s) NOT resolved, which is not a pass: ${unverified.slice(0, 6).map((u) => u.ref || u.name || '?').join(', ')}${unverified.length > 6 ? ', …' : ''}`));
  lines.push(line('artifact', safeRelPath(out)));
  appendHistory({
    verb: 'preset-gate', version, fromVersion: readPin()?.version ?? null, result: report.verdict,
    detail: Object.entries(counts).map(([k, v]) => `${k}=${v}`).join(' ') || 'no counts',
  });
  return {
    ok: report.verdict !== 'BREAKS',
    // Non-zero only on a real BREAKS; RISKY is for a human to read, not a stop signal.
    exitCode: report.verdict === 'BREAKS' ? 1 : 0,
    verb: 'preset-gate', version,
    verdict: report.verdict, counts: report.counts,
    findings: report.findings || [], unverified: report.unverified || [],
    artifact: out,
    text: lines.join('\n'),
  };
}

// ── preflight ───────────────────────────────────────────────────────────────
//
// ONE COMMAND, EVERY GUARD, ONE VERDICT. The owner's condition for this upgrade was that it must be
// "non breaking and must be double and triple guarded by checks". Seven separate verbs with seven
// answers is not that — it is a person holding seven booleans in their head. This runs the whole set
// and refuses to say GO unless every BLOCKING guard is green, naming each one and its evidence.
//
// Each guard is a real reading, produced by the module that owns it, not a re-implementation:
// the verb spawns this same dispatcher for each step so there is exactly one code path per check.
//
// BLOCKING (any failure -> NO-GO): baseline freshness, analyze, patch-effect, preset-gate, verify.
// REPORTED (never blocks, but never hidden): RISKY counts and the unverified/gap counts, because a
// clean verdict with a silent gap list is a lie.
async function verbPreflight(argv) {
  const version = requireVersionArg('preflight', argv);
  const cp = candidatePaths(version);
  const cdir = path.dirname(cp.contract);
  const lines = [];
  const guards = [];
  const add = (name, ok, blocking, detail) => { guards.push({ name, ok, blocking, detail }); };

  lines.push(`dsh-update preflight ${version}   (host ${hostName()})`);
  lines.push('');

  // ── guard 1: is the baseline still describing the engine we actually run? ─────────────────────
  // A stale baseline makes every downstream comparison meaningless, and it fails quietly: analyze
  // would compare the candidate against a contract that no longer matches the pin.
  const pin = readPin();
  const pinProblems = pin ? (validatePin(pin).problems || []) : ['pin.json is absent'];
  const cSha = fileInfo(PATHS.baselineContract).sha256;
  const tSha = fileInfo(PATHS.baselineTree).sha256;
  const baselineOk = pinProblems.length === 0
    && Boolean(cSha) && Boolean(tSha)
    && pin.contractSha256 === cSha && pin.treeSha256 === tSha;
  add('baseline fresh', baselineOk, true, baselineOk
    ? `pin ${pin.version} matches state/baseline (contract ${String(cSha).slice(0, 12)}…, tree ${String(tSha).slice(0, 12)}…)`
    : `pin and state/baseline disagree or are absent (${pinProblems.join('; ') || `pin.contractSha256=${pin?.contractSha256} on disk=${cSha}`}) — run \`snapshot\` first`);

  // ── the engine-backed guards, run through this same dispatcher ────────────────────────────────
  const run = (verb) => {
    const r = spawnSync(process.execPath, [path.join(PATHS.libDir, 'cli.mjs'), verb, version], {
      encoding: 'utf8', timeout: 900000,
    });
    return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
  };

  // analyze -> diff.json
  run('analyze');
  const diff = readJson(cp.diff, null);
  const diffVerdict = diff?.verdict ?? null;
  add('analyze (contract diff)', diffVerdict !== null && diffVerdict !== 'BREAKS', true,
    diffVerdict === null ? 'diff.json was not produced — analyze failed' : `verdict ${diffVerdict}${diff?.counts ? ` (${Object.entries(diff.counts).map(([k, v]) => `${k}=${v}`).join(' ')})` : ''}`);

  // patch-effect -> the layer we own still has its intended EFFECT
  run('patch-effect');
  const pe = readJson(path.join(cdir, 'patch-effect.json'), null);
  add('patch-effect (our layers)', pe?.verdict === 'SAFE' || pe?.verdict === 'RISKY', true,
    pe ? `verdict ${pe.verdict} (${Object.entries(pe.counts || {}).map(([k, v]) => `${k}=${v}`).join(' ') || 'no counts'})`
      : 'patch-effect.json was not produced');

  // preset-gate -> every package/subpath our PRESETS name still resolves
  run('preset-gate');
  const pg = readJson(path.join(cdir, 'preset-gate.json'), null);
  add('preset-gate (the only preset detector)', pg?.verdict === 'SAFE' || pg?.verdict === 'RISKY', true,
    pg ? `verdict ${pg.verdict} (${Object.entries(pg.counts || {}).map(([k, v]) => `${k}=${v}`).join(' ') || 'no counts'}), ${(pg.unverified || []).length} name(s) unverified`
      : 'preset-gate.json was not produced');

  // verify -> all gates, including G8 the session-format door
  run('verify');
  const v = readJson(cp.verify, null);
  const g8 = Array.isArray(v?.gates) ? v.gates.find((g) => g && g.id === 'G8') : null;
  add('verify (gates G1-G8)', v?.pass === true && v?.complete === true, true,
    v ? `pass=${v.pass} complete=${v.complete}; ${(v.gates || []).filter((g) => g.ran).length} ran, ${(v.gates || []).filter((g) => g.ran && g.ok === false).map((g) => g.id).join(',') || 'none failing'}`
      : 'verify.json was not produced');
  add('G8 session-format door', g8 ? g8.ok === true : false, true,
    g8 ? (g8.ok === true ? `ok — ${String(g8.detail).slice(0, 180)}` : `BLOCKING ONE-WAY DOOR — ${String(g8.detail).slice(0, 300)}  Promote deliberately with --accept-session-format-upgrade once that is the decision.`)
      : 'no G8 gate in verify.json');

  // ── reported, never blocking ──────────────────────────────────────────────────────────────────
  const gaps = (diff?.consumed?.unverified || []).length
    + (pe?.unverified || []).length
    + (pg?.unverified || []).length;
  add('gaps (not checked)', gaps === 0, false,
    gaps === 0 ? 'nothing — every reference these guards could check was checked'
      : `${gaps} reference(s) could NOT be checked. This is not a pass and not a failure; it is the honest size of the blind spot.`);

  // ── verdict ──────────────────────────────────────────────────────────────────────────────────
  const blocking = guards.filter((g) => g.blocking);
  const failed = blocking.filter((g) => !g.ok);
  const go = failed.length === 0;

  for (const g of guards) {
    lines.push(`  ${g.ok ? 'PASS' : (g.blocking ? 'FAIL' : 'GAP ')}  ${g.name}${g.blocking ? '' : '  (non-blocking)'}`);
    lines.push(`          ${g.detail}`);
  }
  lines.push('');
  lines.push(go
    ? `  VERDICT: GO — ${blocking.length} blocking guard(s) all green.`
    : `  VERDICT: NO-GO — ${failed.length} of ${blocking.length} blocking guard(s) failed: ${failed.map((g) => g.name).join(', ')}`);
  if (go) {
    lines.push('');
    lines.push('  Remaining out-of-band steps before the engine may change, in order:');
    lines.push('    1. take and verify a backup:  node dsh-update/tools/backup-state.mjs');
    lines.push('    2. apply the coupled config and the engine IN ONE STEP (the new package names do');
    lines.push('       not exist on 0.1.5 and the old ones do not exist on 0.1.7), then');
    lines.push('    3. verify the first boot on the new engine and confirm rollback is still possible.');
  }

  appendHistory({
    verb: 'preflight', version, fromVersion: pin?.version ?? null, result: go ? 'GO' : 'NO-GO',
    detail: guards.map((g) => `${g.name}=${g.ok ? 'pass' : (g.blocking ? 'FAIL' : 'gap')}`).join(' '),
  });

  return {
    ok: go, exitCode: go ? 0 : 8, verb: 'preflight', version, go, guards,
    blocking: blocking.length, failed: failed.map((g) => g.name),
    text: lines.join('\n'),
  };
}

async function verbHelp() {
  const lines = [];
  lines.push(`dsh-update ${VERSION} — safe DSH harness upgrades (${safeRelPath(ROOT)})`);
  lines.push('');
  lines.push('usage: bin/dsh-update.ps1 <verb> [version] [--json]');
  lines.push('');
  lines.push('  verb        writes');
  for (const [verb, desc] of Object.entries(VERB_HELP)) {
    lines.push(`  ${verb.padEnd(10)}  ${desc}`);
  }
  lines.push('');
  lines.push('  No verb = status. --json on every verb prints one JSON object on stdout.');
  lines.push('');
  lines.push('operator order: check -> snapshot -> fetch <ver> -> analyze <ver> -> verify <ver> -> plan <ver> -> promote <ver>');
  lines.push('safety: nothing is deleted; only promote/rollback write outside dsh-update/, each after a');
  lines.push('        timestamped backup; no verb starts, stops or restarts an engine. Promotion takes');
  lines.push('        effect at the NEXT engine boot.');
  return { ok: true, exitCode: 0, verb: 'help', verbs: VERB_HELP, text: lines.join('\n') };
}

function requireVersionArg(verb, argv) {
  const positional = argv.filter((a) => !a.startsWith('-'));
  const version = positional[0];
  if (!version) {
    throw new CliError(`\`${verb}\` needs a version: bin/dsh-update.ps1 ${verb} <version>\n  e.g. bin/dsh-update.ps1 ${verb} 0.1.5-rc.3\n  Run \`check\` to see the published versions.`, { exitCode: 1 });
  }
  return version;
}

// ── main ────────────────────────────────────────────────────────────────────

const VERBS = {
  status: verbStatus, check: verbCheck, snapshot: verbSnapshot, fetch: verbFetch,
  analyze: verbAnalyze, plan: verbPlan, verify: verbVerify, promote: verbPromote,
  rollback: verbRollback, report: verbReport, help: verbHelp,
  'patch-effect': verbPatchEffect,
  'preset-gate': verbPresetGate,
  preflight: verbPreflight,
};

async function main() {
  const started = Date.now();
  const flags = ARGV.filter((a) => a.startsWith('-'));
  JSON_MODE = flags.includes('--json');
  if (flags.includes('--help') || flags.includes('-h')) {
    const help = await verbHelp();
    emit(help, help.text);
    return 0;
  }
  const verb = ARGV.find((a) => !a.startsWith('-')) || 'status';
  const fn = VERBS[verb];
  if (!fn) {
    const e = new CliError(`unknown verb \`${verb}\`.\n  Verbs: ${Object.keys(VERB_HELP).join(', ')}.\n  Run with --help for the full table.`, { exitCode: 1 });
    emit({ ok: false, verb, error: e.message, exitCode: e.exitCode }, `dsh-update: ${e.message}`);
    return e.exitCode;
  }
  const rest = ARGV.filter((a) => a !== verb);
  try {
    const result = await fn(rest);
    emit(result, result.text || '');
    return result.exitCode ?? 0;
  } catch (err) {
    const known = err instanceof CliError;
    const exitCode = known ? err.exitCode : 1;
    const message = known ? err.message : `${err.message}\n  (unexpected error — this is a bug in dsh-update, not in your input; the stack is below)\n${err.stack}`;
    try {
      logInvocation(`${verb}-error`, { argv: ARGV, stdout: '', stderr: message, exitCode, durationMs: Date.now() - started });
    } catch { /* a failed diagnostic write must not mask the error */ }
    emit({ ok: false, verb, error: message, exitCode }, `dsh-update ${verb}: ${message}`);
    return exitCode;
  }
}

main().then((code) => {
  process.exitCode = code;
}).catch((err) => {
  process.stderr.write(`dsh-update: fatal ${err.stack || err.message}\n`);
  process.exitCode = 1;
});
