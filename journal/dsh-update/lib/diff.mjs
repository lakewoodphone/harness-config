#!/usr/bin/env node
/**
 * dsh-update / lib/diff.mjs — baseline vs candidate analysis (breakage classes B1..B10).
 *
 *   node lib/diff.mjs --baseline-contract <a.json> --candidate-contract <b.json> --consumed <c.json>
 *                     [--baseline-tree <t1.json>] [--candidate-tree <t2.json>] [--out <path>]
 *
 * Operates on ALREADY-PRODUCED JSON artifacts only: it imports no sibling module, so it runs even
 * when contract.mjs / compose.mjs / consumed.mjs / store.mjs / yaml.mjs do not exist yet.
 *
 * Frozen contract: dsh-update/SPEC.md. Implemented exactly, with these three deliberate readings
 * (each is stated again where it is implemented):
 *
 *  1. B1 vs B5 overlap. SPEC's B1 says "we name a package ... (preset row, profile bundle, or
 *     plugin import)" and B5 says "a name in dsh.profile.bundles no longer resolves" — the same
 *     test on the same data. Reporting a missing bundle twice (once as B1, once as B5) would
 *     double-count a single breakage in `counts`. So the B5 pass runs first and owns every
 *     profileBundles name; the B1 pass then covers consumed.packageRefs plus any bundle name the
 *     B5 pass did not handle (e.g. when profileBundles is empty and only packageRefs exist).
 *  2. B7's RISKY trigger is a SURFACE change (exportSubpaths or dsh), not a version change: SPEC
 *     bullet B7 lists version alongside exports/dsh, but the same bullet's sibling sentence in the
 *     task contract requires "INFO for packages whose version changed but whose surface did not" —
 *     a version bump is the normal case of every upgrade and cannot be RISKY for all of them.
 *     Version is still reported: it appears in the RISKY evidence and in the INFO finding.
 *  3. Determinism. Every field is a pure function of the inputs except `generatedAt`. Pinning it
 *     with --generated-at or SOURCE_DATE_EPOCH makes the whole artifact byte-identical across runs
 *     (that is what tests/run.mjs asserts); an unpinned run differs only in that one field.
 *
 * A BREAKS finding may only rest on AUTHORITATIVE evidence (manifest data, engine exit codes,
 * verbatim engine output). That rule is enforced in addFinding(), not by discipline: an ADVISORY
 * finding offered as BREAKS is downgraded to RISKY and says so in its evidence.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import process from 'node:process';

const SEVERITY_ORDER = { BREAKS: 0, RISKY: 1, CAPABILITY: 2, INFO: 3 };
const AUTHORITATIVE = 'AUTHORITATIVE';
const ADVISORY = 'ADVISORY';

class UsageError extends Error {}
class InputError extends Error {}

/* ------------------------------------------------------------------ arguments */

const USAGE = `usage: node lib/diff.mjs --baseline-contract <contract.json> --candidate-contract <contract.json>
                      --consumed <consumed.json> [--baseline-tree <tree.json>]
                      [--candidate-tree <tree.json>] [--out <diff.json>] [--generated-at <ISO-8601>]

Compares the contract of an installed DSH engine against the contract of a candidate engine,
cross-referenced with what this deployment depends on (consumed.json), and reports findings in
breakage classes B1..B10. Exit 0 on success; non-zero with a diagnostic on stderr on failure.`;

function parseArgs(argv) {
  const opts = { flags: {}, };
  const known = new Set([
    '--baseline-contract', '--candidate-contract', '--consumed',
    '--baseline-tree', '--candidate-tree', '--out', '--generated-at',
  ]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') { opts.help = true; continue; }
    const eq = a.indexOf('=');
    const key = eq > 0 ? a.slice(0, eq) : a;
    if (!known.has(key)) throw new UsageError(`unknown argument "${a}"`);
    let value = eq > 0 ? a.slice(eq + 1) : argv[++i];
    if (value === undefined) throw new UsageError(`missing value for ${key}`);
    opts.flags[key] = value;
  }
  if (opts.help) return opts;
  for (const req of ['--baseline-contract', '--candidate-contract', '--consumed']) {
    if (!opts.flags[req]) throw new UsageError(`missing required ${req}`);
  }
  return opts;
}

/* ------------------------------------------------------------------ input reading */

function readJson(file, label) {
  const abs = path.resolve(file);
  let raw;
  try {
    raw = fs.readFileSync(abs);
  } catch (err) {
    throw new InputError(`${label}: cannot read "${abs}" (${err.code ?? err.message})`);
  }
  try {
    return { value: JSON.parse(raw.toString('utf8')), raw, abs };
  } catch (err) {
    throw new InputError(`${label}: "${abs}" is not valid JSON: ${err.message}`);
  }
}

function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function generatedAtFrom(opts) {
  const pinned = opts.flags['--generated-at'] ?? process.env.SOURCE_DATE_EPOCH;
  if (pinned === undefined) return new Date().toISOString();
  const t = /^\d+$/.test(pinned) ? new Date(Number(pinned) * 1000) : new Date(pinned);
  if (Number.isNaN(t.getTime())) throw new UsageError(`--generated-at "${pinned}" is not a date`);
  return t.toISOString();
}

/* ------------------------------------------------------------------ small helpers */

const isUpstream = (name) => typeof name === 'string' && name.startsWith('@deepseek-ai/');
const isLocalPlugin = (name) => typeof name === 'string' && name.startsWith('dsh-plugin-');

function normSubpath(spec) {
  if (spec === undefined || spec === null) return '.';
  let t = String(spec).trim();
  if (t === '' || t === '.') return '.';
  if (t.startsWith('./')) t = t.slice(2);
  if (t.startsWith('/')) t = t.slice(1);
  return './' + t;
}

/** Split "pkg/sub" into [pkg, subpath], scope-aware on @scope/name. */
function splitSpecifier(name, subpath) {
  let n = String(name ?? '').trim();
  const sub = normSubpath(subpath);
  if (n.endsWith('/')) n = n.slice(0, -1);
  const start = n.startsWith('@') ? n.indexOf('/') + 1 : 0;
  const slash = start > 0 ? n.indexOf('/', start) : n.indexOf('/');
  if (slash > 0) {
    const head = n.slice(0, slash);
    const tail = n.slice(slash + 1);
    if (tail !== '') return [head, sub === '.' ? normSubpath(tail) : sub, true];
  }
  return [n, sub, false];
}

/** Resolve a consumed name (which may carry an inline subpath) against a contract packages map. */
function lookup(packages, name, subpath) {
  const direct = packages[String(name)];
  if (direct) return { entry: direct, pkg: String(name), subpath: normSubpath(subpath), split: false };
  const [pkg, sub, didSplit] = splitSpecifier(name, subpath);
  return { entry: packages[pkg] ?? null, pkg, subpath: sub, split: didSplit };
}

function hasSubpath(list, sub) {
  if (!Array.isArray(list)) return null; // unknown, not "absent"
  const target = normSubpath(sub);
  for (const raw of list) {
    const cand = normSubpath(raw);
    if (cand === target) return true;
    const star = cand.indexOf('*');
    if (star >= 0) {
      const pre = cand.slice(0, star);
      const post = cand.slice(star + 1);
      if (target.startsWith(pre) && target.endsWith(post) && target.length >= pre.length + post.length) return true;
    }
  }
  return false;
}

function sortedUnique(values) {
  return [...new Set(values)].sort();
}

function quoteList(values, cap = 40) {
  if (!Array.isArray(values)) return JSON.stringify(values ?? null);
  const shown = values.slice(0, cap).map((v) => JSON.stringify(v));
  const extra = values.length > cap ? ` (+${values.length - cap} more)` : '';
  return `[${shown.join(', ')}]${extra}`;
}

function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`).join(',')}}`;
}

function contractVersion(contract) {
  return contract?.dsh?.version ?? contract?.version ?? null;
}

/**
 * How certain is this field? The contract states its own provenance, and a finding must not claim
 * more than the data supports — so the declared tier wins over the class default. This is what makes
 * the "a BREAKS may only rest on AUTHORITATIVE evidence" rule real rather than decorative: a
 * contract that admits its exportSubpaths came from a regex gets RISKY, not BREAKS, for the same
 * comparison.
 */
function tierFor(entry, field, fallback) {
  const declared = entry?.provenance?.[field];
  if (declared === AUTHORITATIVE || declared === ADVISORY) return declared;
  return fallback;
}

function weakerTier(a, b) {
  const rank = { AUTHORITATIVE: 2, ADVISORY: 1 };
  return (rank[a] ?? 0) <= (rank[b] ?? 0) ? a : b;
}

/** File/line pairs, only ever taken from consumed.json — never invented. */
function consumersOf(entry) {
  const out = [];
  if (entry && typeof entry.file === 'string' && entry.file !== '') {
    out.push({ file: entry.file, line: typeof entry.line === 'number' ? entry.line : null });
  }
  return out;
}

function describeConsumers(entry) {
  const c = consumersOf(entry);
  if (c.length === 0) return 'consumed.json entry carries no file/line';
  return c.map((x) => (x.line === null ? x.file : `${x.file}:${x.line}`)).join(', ');
}

/* ------------------------------------------------------------------ findings collector */

function makeCollector() {
  const findings = [];
  const unverified = [];
  const notes = [];
  const index = new Map();
  let downgrades = 0;
  let merged = 0;

  /**
   * One breakage is one finding. The same subpath named in three preset files (which is how this
   * deployment actually names list-agents) is ONE finding with three consumers, not three findings
   * that triple-count in `counts`.
   */
  function add(finding) {
    const f = {
      class: finding.class,
      severity: finding.severity,
      subject: finding.subject,
      evidence: finding.evidence,
      evidenceTier: finding.evidenceTier,
      consumers: finding.consumers ?? [],
      why: finding.why,
      suggested: finding.suggested,
    };
    if (f.severity === 'BREAKS' && f.evidenceTier !== AUTHORITATIVE) {
      // The rule, in code: a BREAKS may only rest on AUTHORITATIVE evidence.
      f.severity = 'RISKY';
      f.downgradedFrom = 'BREAKS';
      f.evidence = `${f.evidence} | DOWNGRADED BREAKS->RISKY: this rests on ${f.evidenceTier} evidence and only AUTHORITATIVE ` +
        `evidence (manifest data, an exit code, verbatim engine output) may declare BREAKS.`;
      downgrades += 1;
    }
    const key = `${f.class}|${f.subject}|${f.severity}|${f.evidenceTier}`;
    const prev = index.get(key);
    if (prev !== undefined) {
      const p = findings[prev];
      for (const c of f.consumers) {
        if (!p.consumers.some((x) => x.file === c.file && x.line === c.line)) p.consumers.push(c);
      }
      if (p.evidence !== f.evidence) p.evidence = `${p.evidence} || also: ${f.evidence}`;
      merged += 1;
      return p;
    }
    findings.push(f);
    index.set(key, findings.length - 1);
    return f;
  }

  function gap(entry) {
    unverified.push({
      ref: entry.ref,
      kind: entry.kind,
      reason: entry.reason,
      file: entry.file ?? null,
      line: typeof entry.line === 'number' ? entry.line : null,
    });
  }

  function finish() {
    for (const f of findings) {
      f.consumers = f.consumers.slice().sort((a, b) => {
        const af = String(a.file ?? '');
        const bf = String(b.file ?? '');
        if (af !== bf) return af < bf ? -1 : 1;
        return (a.line ?? -1) - (b.line ?? -1);
      });
    }
    const rows = findings.slice().sort((a, b) => {
      const s = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
      if (s !== 0) return s;
      if (a.subject !== b.subject) return a.subject < b.subject ? -1 : 1;
      if (a.class !== b.class) return a.class < b.class ? -1 : 1;
      return a.evidence < b.evidence ? -1 : a.evidence > b.evidence ? 1 : 0;
    });
    rows.forEach((f, i) => { f.id = `F${String(i + 1).padStart(3, '0')}`; });
    // re-emit with `id` first, keeping a fixed key order for byte-stable output
    const ordered = rows.map((f) => {
      const o = { id: f.id, class: f.class, severity: f.severity, subject: f.subject, evidence: f.evidence, evidenceTier: f.evidenceTier };
      if (f.downgradedFrom) o.downgradedFrom = f.downgradedFrom;
      o.consumers = f.consumers;
      o.why = f.why;
      o.suggested = f.suggested;
      return o;
    });
    const gaps = unverified.slice().sort((a, b) => {
      if (a.ref !== b.ref) return a.ref < b.ref ? -1 : 1;
      if (a.reason !== b.reason) return a.reason < b.reason ? -1 : 1;
      return String(a.file) < String(b.file) ? -1 : String(a.file) > String(b.file) ? 1 : 0;
    });
    const counts = { BREAKS: 0, RISKY: 0, CAPABILITY: 0, INFO: 0 };
    for (const f of ordered) counts[f.severity] = (counts[f.severity] ?? 0) + 1;
    return { findings: ordered, unverified: gaps, counts, downgrades, merged, notes };
  }

  return { add, gap, note: (m) => notes.push(m), finish, get count() { return findings.length; } };
}

/* ------------------------------------------------------------------ tree handling */

/** A dump that failed, or that produced nothing, is a failure — never a clean result. */
function treeHealth(tree, label) {
  if (!tree) return { supplied: false };
  const problems = [];
  if (tree.failure) problems.push(`failure: ${typeof tree.failure === 'string' ? tree.failure : JSON.stringify(tree.failure)}`);
  if (typeof tree.exitCode === 'number' && tree.exitCode !== 0) problems.push(`exitCode ${tree.exitCode}`);
  const rows = Array.isArray(tree.rows) ? tree.rows : null;
  const ids = Array.isArray(tree.rowIds) ? tree.rowIds : [];
  const rowCount = rows ? rows.length : ids.length;
  if (rowCount === 0) problems.push(`0 rows (stdout ${tree.exitCode === 0 ? 'parsed' : 'unparsed'})`);
  return {
    supplied: true,
    problems,
    rowIds: rows ? rows.map((r) => r?.id).filter(Boolean) : ids,
    nameById: new Map((rows ?? []).filter((r) => r && r.id).map((r) => [r.id, r.name ?? null])),
    names: Array.isArray(tree.names) ? tree.names : (rows ?? []).map((r) => r?.name).filter(Boolean),
    patchedRowIds: Array.isArray(tree.patchedRowIds) ? tree.patchedRowIds : null,
    version: tree.engineVersion ?? null,
  };
}

/* ------------------------------------------------------------------ the analysis */

function run(opts) {
  const baselineContractRead = readJson(opts.flags['--baseline-contract'], 'baseline contract');
  const candidateContractRead = readJson(opts.flags['--candidate-contract'], 'candidate contract');
  const consumedRead = readJson(opts.flags['--consumed'], 'consumed.json');

  const baselineContract = baselineContractRead.value;
  const candidateContract = candidateContractRead.value;
  const consumed = consumedRead.value;

  if (!candidateContract || typeof candidateContract !== 'object' || typeof candidateContract.packages !== 'object' || candidateContract.packages === null) {
    throw new InputError(`candidate contract "${candidateContractRead.abs}" has no "packages" object — cannot cross-reference; was it produced by lib/contract.mjs?`);
  }
  if (!consumed || typeof consumed !== 'object') {
    throw new InputError(`consumed.json "${consumedRead.abs}" is not an object`);
  }

  const baselinePackages = baselineContract?.packages ?? {};
  const candidatePackages = candidateContract.packages;
  const baselineVersion = contractVersion(baselineContract);
  const candidateVersion = contractVersion(candidateContract);

  const baselineTreeRead = opts.flags['--baseline-tree'] ? readJson(opts.flags['--baseline-tree'], 'baseline tree') : null;
  const candidateTreeRead = opts.flags['--candidate-tree'] ? readJson(opts.flags['--candidate-tree'], 'candidate tree') : null;
  const baselineTree = treeHealth(baselineTreeRead?.value, 'baseline');
  const candidateTree = treeHealth(candidateTreeRead?.value, 'candidate');

  const c = makeCollector();
  const vLabel = `${candidateVersion ?? 'candidate'}`;
  const bLabel = `${baselineVersion ?? 'baseline'}`;

  /* ---- tree health first: a failed read must never look like health ---- */
  const treeSources = [
    { tree: baselineTree, label: 'baseline', read: baselineTreeRead },
    { tree: candidateTree, label: 'candidate', read: candidateTreeRead },
  ];
  for (const { tree, label, read } of treeSources) {
    if (!tree.supplied || tree.problems.length === 0) continue;
    const fleet = tree.problems.some((p) => p.startsWith('failure') || p.startsWith('exitCode'));
    c.add({
      class: 'TREE',
      severity: fleet ? 'BREAKS' : 'RISKY',
      subject: `tree.json (${label})`,
      evidence: `${label} tree read from ${read.abs}: ${tree.problems.join('; ')} (engineVersion ${tree.version ?? 'unknown'}, ${tree.rowIds.length} row ids, patchedRowIds ${quoteList(tree.patchedRowIds)})`,
      evidenceTier: AUTHORITATIVE,
      consumers: [],
      why: fleet
        ? 'the engine failed to compose this profile, so every tree-derived check (patch targets, row ids, capabilities) is blind, and an upgrade verified against a broken tree proves nothing'
        : 'the dump parsed but produced no rows, which is a refusal, not an empty success — every tree-derived check is blind',
      suggested: 'read state/logs/ for the verbatim stdout/stderr of that --dump-config run and fix the compose before trusting any other tree-based finding',
    });
  }

  /* ---- consumed inventory ---- */
  const packageRefs = Array.isArray(consumed.packageRefs) ? consumed.packageRefs : [];
  const profileBundles = Array.isArray(consumed.profileBundles) ? consumed.profileBundles : [];
  const patchRowTargets = Array.isArray(consumed.patchRowTargets) ? consumed.patchRowTargets : [];
  const settingsKeys = Array.isArray(consumed.settingsKeys) ? consumed.settingsKeys : [];
  const cliInvocations = Array.isArray(consumed.cliInvocations) ? consumed.cliInvocations : [];
  const pluginImports = Array.isArray(consumed.pluginImports) ? consumed.pluginImports : [];
  const consumeNotes = Array.isArray(consumed.notes) ? consumed.notes : [];

  const packagesChecked = new Set();
  const surfaceChanged = []; // {pkg, fields:[], summary:[]} — used by B9

  /* ---- B5 bundle missing (runs before B1; see header note 1) ---- */
  const bundlesHandledByB5 = new Set();
  for (const b of profileBundles) {
    const name = String(b?.name ?? '');
    if (name === '') continue;
    const entry = candidatePackages[name];
    if (entry && entry.present !== false && entry.version !== null) continue; // resolves
    bundlesHandledByB5.add(name);
    if (isUpstream(name)) {
      packagesChecked.add(name);
      c.add({
        class: 'B5',
        severity: 'BREAKS',
        subject: name,
        evidence: `dsh.profile.bundles in ${describeConsumers(b)} names "${name}"; candidate ${vLabel} packages["${name}"] = ` +
          `${entry ? JSON.stringify({ present: entry.present, version: entry.version }) : 'absent'}; baseline ${bLabel} = ` +
          `${baselinePackages[name] ? JSON.stringify({ present: baselinePackages[name].present, version: baselinePackages[name].version }) : 'absent'}`,
        evidenceTier: tierFor(entry, 'manifest', AUTHORITATIVE),
        consumers: consumersOf(b),
        why: 'the profile compose loads every bundle before it loads the profile patch layer; a bundle that does not resolve means the whole profile fails to boot, so this is not a lost customization but a dead engine',
        suggested: `re-check whether ${vLabel} renamed or split "${name}", then either pin the profile to a bundle that exists in ${vLabel} or replace the bundle entry and re-run analyze`,
      });
    } else {
      c.add({
        class: 'B5',
        severity: 'INFO',
        subject: name,
        evidence: `dsh.profile.bundles in ${describeConsumers(b)} names the LOCAL package "${name}"; it is resolved from the profile's own node_modules, not from the upstream install, and candidate ${vLabel} packages[] covers @deepseek-ai/* only`,
        evidenceTier: AUTHORITATIVE,
        consumers: consumersOf(b),
        why: 'a local bundle is not something upstream can remove; this finding records that the check could not be made from a contract at all rather than silently passing it',
        suggested: 'nothing to do here — the real check that our bundles resolve is verify gate G3, which looks for the row name in the composed tree',
      });
      c.gap({
        ref: name, kind: 'profile-bundle', file: b?.file, line: b?.line,
        reason: 'local package: an upstream contract cannot describe it; resolution is checked by verify gate G3 (row name present in the composed tree)',
      });
    }
  }

  /* ---- B1 package missing ---- */
  const b1Sources = [
    ...packageRefs.map((r) => ({ entry: r, kind: r?.kind ?? 'packageRef', name: String(r?.name ?? ''), subpath: r?.subpath })),
    // bundle names the B5 pass did not already report
    ...profileBundles.filter((b) => !bundlesHandledByB5.has(String(b?.name ?? ''))).map((b) => ({ entry: b, kind: 'profile-bundle', name: String(b?.name ?? ''), subpath: '.' })),
  ];
  for (const src of b1Sources) {
    if (src.name === '') continue;
    const { entry, pkg, subpath } = lookup(candidatePackages, src.name, src.subpath);
    const present = Boolean(entry && entry.present !== false && entry.version !== null);
    if (isUpstream(pkg)) packagesChecked.add(pkg);
    if (present) continue;
    if (isUpstream(pkg)) {
      c.add({
        class: 'B1',
        severity: 'BREAKS',
        subject: pkg,
        evidence: `consumed[${src.kind}] in ${describeConsumers(src.entry)} names "${src.name}"; candidate ${vLabel} packages["${pkg}"] = ` +
          `${entry ? JSON.stringify({ present: entry.present, version: entry.version }) : 'ABSENT'}; baseline ${bLabel} = ` +
          `${baselinePackages[pkg] ? JSON.stringify({ present: baselinePackages[pkg].present, version: baselinePackages[pkg].version }) : 'absent'}`,
        evidenceTier: tierFor(entry, 'manifest', AUTHORITATIVE),
        consumers: consumersOf(src.entry),
        why: 'a row that names a plugin package which is not installed fails to resolve at mount; in a preset that breaks session creation, and in the host composition it can take the boot down',
        suggested: `check whether ${vLabel} renamed or removed "${pkg}"; if it moved, update ${describeConsumers(src.entry) || 'the reference'}, and if the capability is gone, keep the row disabled rather than deleting it so the intent survives`,
      });
    } else {
      c.add({
        class: 'B1',
        severity: 'INFO',
        subject: pkg,
        evidence: `consumed[${src.kind}] in ${describeConsumers(src.entry)} names "${src.name}"; candidate ${vLabel} packages[] = ` +
          `${entry ? JSON.stringify({ present: entry.present, version: entry.version }) : 'absent'} — this is OUR local package, not upstream`,
        evidenceTier: tierFor(entry, 'manifest', AUTHORITATIVE),
        consumers: consumersOf(src.entry),
        why: 'an upstream contract covers @deepseek-ai/* only, so absence here is expected and says nothing about whether the package installs; reporting it as a breakage would be a false alarm',
        suggested: 'nothing to do here — verify gate G3 checks that this name appears as a composed row name',
      });
      c.gap({
        ref: src.name, kind: src.kind, file: src.entry?.file, line: src.entry?.line,
        reason: 'local package: upstream manifest data does not describe it; resolution is checked by verify gate G3',
      });
    }
  }

  /* ---- B2 subpath missing ---- */
  for (const src of b1Sources) {
    if (src.name === '') continue;
    const { entry, pkg, subpath } = lookup(candidatePackages, src.name, src.subpath);
    if (subpath === '.') continue;
    const present = Boolean(entry && entry.present !== false && entry.version !== null);
    if (!present) continue; // B1 already reported the package itself
    const subpaths = Array.isArray(entry.exportSubpaths) ? entry.exportSubpaths : null;
    if (subpaths === null) {
      c.gap({
        ref: `${pkg}${subpath.slice(1)}`, kind: 'export-subpath', file: src.entry?.file, line: src.entry?.line,
        reason: `candidate ${vLabel} contract has no exportSubpaths array for "${pkg}" (field absent) — the subpath cannot be checked from this artifact`,
      });
      continue;
    }
    if (hasSubpath(subpaths, subpath)) continue;
    c.add({
      class: 'B2',
      severity: 'BREAKS',
      subject: `${pkg}${subpath.slice(1)}`,
      evidence: `${pkg} in ${vLabel}: exportSubpaths = ${quoteList(subpaths)}; "${subpath}" is not among them. ` +
        `Consumed at ${describeConsumers(src.entry)} (consumed[${src.kind}]). Baseline ${bLabel} exportSubpaths = ${quoteList(baselinePackages[pkg]?.exportSubpaths)}`,
      evidenceTier: tierFor(entry, 'exportSubpaths', AUTHORITATIVE),
      consumers: consumersOf(src.entry),
      why: 'a subpath export that no longer exists resolves to nothing: the row fails to mount (host plane) or the preset breaks session creation, and the failure appears at run time rather than at upgrade time',
      suggested: `stop naming "${pkg}${subpath.slice(1)}" — either point ${describeConsumers(src.entry) || 'the reference'} at a subpath ${vLabel} still exports (${quoteList(subpaths)}), or move the capability into a plugin we own`,
    });
  }

  /* ---- B3 patch target gone / B4 patch target moved ---- */
  const haveCandidatePatched = Array.isArray(candidateTree.patchedRowIds);
  const candidateRowIds = new Set(candidateTree.supplied ? candidateTree.rowIds : []);
  const baselineRowIds = new Set(baselineTree.supplied ? baselineTree.rowIds : []);
  // A tree produced by consume.mjs/compose.mjs may attribute a patch only to the row immediately
  // after the `# == ..., patched by ...` comment, so a target that the deployment's own dump DOES
  // attribute to our layer can be absent from `patchedRowIds` in BOTH trees. When the baseline and
  // the candidate agree that the target is unpatched, that is an extractor limitation, not a
  // regression caused by this upgrade — reported as INFO plus a gap, never as a false BREAKS.
  const baselinePatched = baselineTree.supplied && baselineTree.problems.length === 0 && Array.isArray(baselineTree.patchedRowIds)
    ? new Set(baselineTree.patchedRowIds)
    : null;
  for (const t of patchRowTargets) {
    const id = String(t?.id ?? '');
    if (id === '') continue;
    if (!candidateTree.supplied) {
      c.gap({ ref: id, kind: 'patch-row-target', file: t?.file, line: t?.line, reason: 'no candidate tree supplied; the patch-applied check is verify gate G2 (which re-composes and reads patchedRowIds)' });
      continue;
    }
    if (candidateTree.problems.length > 0) {
      c.gap({ ref: id, kind: 'patch-row-target', file: t?.file, line: t?.line, reason: `candidate tree did not compose cleanly (${candidateTree.problems.join('; ')}); this target is not checkable` });
      continue;
    }
    if (!haveCandidatePatched) {
      c.gap({ ref: id, kind: 'patch-row-target', file: t?.file, line: t?.line, reason: 'candidate tree has no patchedRowIds array; the patch-applied check could not be made' });
      continue;
    }
    if (candidateTree.patchedRowIds.includes(id)) {
      // still applying — B4 checks whether it now applies to something else
      if (baselineTree.supplied && baselineTree.problems.length === 0) {
        const before = baselineTree.nameById.get(id) ?? null;
        const after = candidateTree.nameById.get(id) ?? null;
        if (before !== null && after !== null && before !== after) {
          c.add({
            class: 'B4',
            severity: 'RISKY',
            subject: id,
            evidence: `row "${id}": name in ${bLabel} = "${before}", name in ${vLabel} = "${after}"; our patch (${describeConsumers(t)}) still applies to the id`,
            evidenceTier: AUTHORITATIVE,
            consumers: consumersOf(t),
            why: 'the patch keys off the row id, and the row now carries a different plugin — so our config is being applied to a plugin the comments do not describe, which either validates nothing or validates the wrong thing',
            suggested: `confirm the field(s) ${describeConsumers(t) || 'the patch'} sets are still meaningful for "${after}"; if they are not, re-target the patch or keep the setting in a plugin we own`,
          });
        }
      } else if (baselineTree.supplied === true && baselineTree.problems.length > 0) {
        c.gap({ ref: id, kind: 'patch-row-target', file: t?.file, line: t?.line, reason: `baseline tree did not compose cleanly (${baselineTree.problems.join('; ')}); whether this patch target moved cannot be decided` });
      } else if (!baselineTree.supplied) {
        c.gap({ ref: id, kind: 'patch-row-target', file: t?.file, line: t?.line, reason: 'no baseline tree supplied (state/baseline/tree.json); whether this patch target moved could not be decided' });
      }
      continue;
    }
    const idInRowIds = candidateRowIds.has(id);
    const unchangedAcrossTrees = baselinePatched !== null && !baselinePatched.has(id);
    if (unchangedAcrossTrees) {
      // not a change: the same extractor omitted it before the upgrade too
      c.add({
        class: 'B3',
        severity: 'INFO',
        subject: id,
        evidence: `our patch (${describeConsumers(t)}) targets row id "${id}"; it is absent from patchedRowIds in BOTH the baseline tree (${quoteList([...baselinePatched], 60)}) and the candidate tree — so this is NOT evidence that the upgrade broke it. The deployment's own ${bLabel} dump attributes ${idInRowIds ? `row "${id}"` : `no row with id "${id}"`} to our patch layer, so treat this as an attribution limitation of the tree artifact.`,
        evidenceTier: AUTHORITATIVE,
        consumers: consumersOf(t),
        why: 'a tree artifact that marks only the first row after a patch comment will always look like it lost a patch target; acting on that would block a healthy upgrade',
        suggested: `confirm with a fresh \`--dump-config\` (verify gate G2 does exactly that) whether "${id}" carries our patch attribution after the upgrade; if the two agree, the artifact extractor is the thing to fix`,
      });
      c.gap({
        ref: id, kind: 'patch-row-target', file: t?.file, line: t?.line,
        reason: `absent from patchedRowIds in the baseline tree as well as the candidate tree, so the diff cannot tell whether our patch still applies; verify gate G2 decides it from the engine's own dump`,
      });
      continue;
    }
    c.add({
      class: 'B3',
      severity: 'BREAKS',
      subject: id,
      evidence: `our patch (${describeConsumers(t)}) targets row id "${id}"; candidate ${vLabel} patchedRowIds = ${quoteList(candidateTree.patchedRowIds)} — "${id}" is missing. ` +
        (idInRowIds
          ? `Row "${id}" DOES still exist in the candidate tree (name: "${candidateTree.nameById.get(id) ?? '?'}"), but carries no patch attribution: our patch silently stopped applying.`
          : `Row id "${id}" is absent from the candidate tree entirely (${candidateTree.rowIds.length} rows): upstream removed the row our patch was written against.`),
      evidenceTier: AUTHORITATIVE,
      consumers: consumersOf(t),
      why: idInRowIds
        ? 'the row exists and the engine starts, so nothing errors — but our override is applied to nothing, and the setting we depend on silently reverts to upstream default'
        : 'the row our patch was written against no longer exists, so the override is a silent no-op; whatever behaviour it enforced is simply gone, with no error at boot',
      suggested: idInRowIds
        ? `read the candidate's row attribution for "${id}" (which layer patches it now) and re-target ${describeConsumers(t) || 'the patch'}; then re-run analyze to confirm patchedRowIds contains "${id}"`
        : `find the candidate's replacement row (grep the candidate tree names for the plugin this row mounted) and re-point the patch at its id, or move the setting into a plugin we own so it cannot be dropped by an upstream row rename`,
    });
  }

  /* ---- B6 settings key rejected — placeholder only with evidence, else a boot is required ----
   *
   * A settings key is named after its reader's ROW NAME (`llm-deepseek.streamIdleTimeoutMs`,
   * `spend-guard.ceilingUsd`), not after a package, so the owner of a key has to be resolved:
   * exactly the package name, else the package a tree row of that id mounts, else the single package
   * whose name ends in `-<owner>`. Everything else stays unverified rather than guessed.
   */
  const rowNameToPackage = new Map();
  for (const row of ((candidateTreeRead?.value?.rows) ?? [])) {
    if (row && row.id && row.name) rowNameToPackage.set(String(row.id), String(row.name));
  }
  function resolveSettingsOwner(owner) {
    if (candidatePackages[owner]) return { name: owner, how: 'package name' };
    const viaRow = rowNameToPackage.get(owner);
    if (viaRow && candidatePackages[viaRow]) return { name: viaRow, how: `tree row "${owner}" mounts ${viaRow}` };
    const suffix = Object.keys(candidatePackages).filter((n) => n.endsWith(`-${owner}`) || n.endsWith(`/${owner}`));
    if (suffix.length === 1) return { name: suffix[0], how: `package name suffix -${owner}` };
    return { name: null, how: null };
  }
  for (const k of settingsKeys) {
    const key = String(k?.key ?? '');
    if (key === '') continue;
    const dot = key.indexOf('.');
    const owner = dot > 0 ? key.slice(0, dot) : key;
    const rest = dot > 0 ? key.slice(dot + 1) : key;
    const resolved = resolveSettingsOwner(owner);
    const candEntry = resolved.name ? candidatePackages[resolved.name] : null;
    const baseEntry = resolved.name ? baselinePackages[resolved.name] : null;
    const candKeys = Array.isArray(candEntry?.settingsKeys) ? candEntry.settingsKeys : null;
    const baseKeys = Array.isArray(baseEntry?.settingsKeys) ? baseEntry.settingsKeys : null;
    const advertises = (arr) => Array.isArray(arr) && (arr.includes(rest) || arr.includes(key));
    if (resolved.name && candKeys && candKeys.length > 0 && baseKeys && baseKeys.length > 0) {
      if (!advertises(candKeys) && advertises(baseKeys)) {
        c.add({
          class: 'B6',
          severity: 'RISKY',
          subject: key,
          evidence: `owner "${owner}" resolved to package "${resolved.name}" (by ${resolved.how}). ` +
            `baseline ${bLabel} packages["${resolved.name}"].settingsKeys (regex-derived) includes "${rest}": ${quoteList(baseKeys)}; ` +
            `candidate ${vLabel} does not: ${quoteList(candKeys)}`,
          evidenceTier: tierFor(candEntry, 'settingsKeys', ADVISORY),
          consumers: consumersOf(k),
          why: 'if the candidate no longer accepts this settings key it will either warn or refuse to start; --dump-config cannot see this because it never reads the settings document, so this is a placeholder, not a verdict',
          suggested: `verify gate G4 settles this: boot the candidate headless with the isolated home and read the engine's own diagnostics; if the key is gone, migrate "${key}" (see scripts/merge-settings.mjs)`,
        });
        c.gap({
          ref: key, kind: 'settings-key', file: k?.file, line: k?.line,
          reason: 'flagged RISKY from ADVISORY (regex-derived settingsKeys) data only — acceptance is decided by a boot; see verify gate G4',
        });
        continue;
      }
      if (advertises(candKeys)) {
        c.gap({
          ref: key, kind: 'settings-key', file: k?.file, line: k?.line,
          reason: 'the candidate advertises this key, but settingsKeys is regex-derived; acceptance is only proven by a boot; see verify gate G4',
        });
        continue;
      }
    }
    c.gap({
      ref: key, kind: 'settings-key', file: k?.file, line: k?.line,
      reason: resolved.name
        ? `owner "${owner}" resolved to "${resolved.name}" (by ${resolved.how}) but neither contract carries settingsKeys for it — requires a boot; see verify gate G4`
        : `owner "${owner}" of this settings key could not be resolved to a package in the contract — requires a boot; see verify gate G4`,
    });
  }

  /* ---- B7 package surface changed ---- */
  const consumedNames = sortedUnique([
    ...packageRefs.map((r) => lookup(candidatePackages, r?.name, r?.subpath).pkg),
    ...profileBundles.map((b) => String(b?.name ?? '')),
    ...pluginImports.map((p) => String(p?.module ?? '')),
  ].filter(Boolean));
  for (const name of consumedNames) {
    const b = baselinePackages[name];
    const a = candidatePackages[name];
    if (!b || !a) continue;
    if (b.present === false || a.present === false) continue;
    packagesChecked.add(name);
    const fields = [];
    if (b.version !== a.version) fields.push(`version: ${b.version} -> ${a.version}`);
    if (Array.isArray(b.exportSubpaths) && Array.isArray(a.exportSubpaths)) {
      const bs = sortedUnique(b.exportSubpaths.map(normSubpath));
      const as = sortedUnique(a.exportSubpaths.map(normSubpath));
      if (stableStringify(bs) !== stableStringify(as)) {
        const removed = bs.filter((x) => !as.includes(x));
        const added = as.filter((x) => !bs.includes(x));
        fields.push(`exportSubpaths: removed ${quoteList(removed)}; added ${quoteList(added)} (was ${quoteList(bs)}, now ${quoteList(as)})`);
      }
    } else if (b.exportSubpaths !== a.exportSubpaths) {
      c.gap({ ref: name, kind: 'package-surface', reason: `exportSubpaths absent on one side (baseline: ${b.exportSubpaths === undefined ? 'absent' : 'present'}, candidate: ${a.exportSubpaths === undefined ? 'absent' : 'present'}); the surface comparison for this package is incomplete` });
    }
    if (b.dsh && a.dsh && typeof b.dsh === 'object' && typeof a.dsh === 'object') {
      if (stableStringify(b.dsh) !== stableStringify(a.dsh)) {
        fields.push(`dsh: ${stableStringify(b.dsh)} -> ${stableStringify(a.dsh)}`);
      }
    } else if (Boolean(b.dsh) !== Boolean(a.dsh)) {
      c.gap({ ref: name, kind: 'package-surface', reason: `dsh config block present on only one side (baseline: ${Boolean(b.dsh)}, candidate: ${Boolean(a.dsh)}); the dsh comparison for this package was skipped` });
    }
    const surface = fields.filter((f) => !f.startsWith('version: '));
    if (surface.length > 0) {
      surfaceChanged.push({ pkg: name, fields: surface });
      c.add({
        class: 'B7',
        severity: 'RISKY',
        subject: name,
        evidence: `field-by-field ${bLabel} -> ${vLabel}: ${fields.join('; ')}`,
        evidenceTier: surface.some((x) => x.startsWith('exportSubpaths'))
          ? weakerTier(tierFor(b, 'exportSubpaths', AUTHORITATIVE), tierFor(a, 'exportSubpaths', AUTHORITATIVE))
          : AUTHORITATIVE,
        consumers: consumersOf(packageRefs.find((r) => lookup(candidatePackages, r?.name, r?.subpath).pkg === name) ?? profileBundles.find((x) => String(x?.name) === name) ?? {}),
        why: 'the package kept its name but changed what it offers, and we name it by exact string — a renamed export or a changed dsh config block is what turns a working row into a row that mounts something else',
        suggested: `diff the two release surfaces for "${name}" against the fields we actually use, then re-run analyze after adjusting; nothing here blocks an upgrade by itself`,
      });
    } else if (fields.length > 0) {
      c.add({
        class: 'B7',
        severity: 'INFO',
        subject: name,
        evidence: `version changed ${bLabel} -> ${vLabel} (${b.version} -> ${a.version}); exportSubpaths and dsh unchanged`,
        evidenceTier: AUTHORITATIVE,
        consumers: consumersOf(packageRefs.find((r) => lookup(candidatePackages, r?.name, r?.subpath).pkg === name) ?? profileBundles.find((x) => String(x?.name) === name) ?? {}),
        why: 'the version moved but nothing we name moved with it, so there is nothing here to act on',
        suggested: 'no action',
      });
    }
  }

  /* ---- B8 plugin API drift ---- */
  for (const pi of pluginImports) {
    const module = String(pi?.module ?? '');
    if (!isUpstream(module)) {
      if (module !== '') {
        c.gap({
          ref: `${pi?.package ?? '?'} <- ${module}`, kind: 'plugin-import', file: pi?.file, line: pi?.line,
          reason: 'the imported module is not an upstream @deepseek-ai/* package, so an upstream contract cannot describe its symbols',
        });
      }
      continue;
    }
    packagesChecked.add(module);
    const e = candidatePackages[module];
    if (!e || e.present === false) {
      c.add({
        class: 'B8',
        severity: 'BREAKS',
        subject: module,
        evidence: `packages/plugin "${pi?.package ?? '?'}" imports module "${module}"; candidate ${vLabel} packages["${module}"] = ` +
          `${e ? JSON.stringify({ present: e.present, version: e.version }) : 'ABSENT'}; baseline ${bLabel} = ${baselinePackages[module] ? 'present' : 'absent'}`,
        evidenceTier: tierFor(e, 'manifest', AUTHORITATIVE),
        consumers: consumersOf(pi),
        why: 'the plugin imports something the engine no longer ships, so the plugin fails to load — and on the host plane that is a boot failure, not a degraded feature',
        suggested: `check the ${describeConsumers(pi) || 'import'} in packages/${pi?.package ?? '<plugin>'}: either import from a module ${vLabel} still ships, or vendor the symbol we need`,
      });
      continue;
    }
    const symbols = Array.isArray(e.symbols) ? e.symbols : null;
    const wanted = Array.isArray(pi?.symbols) ? pi.symbols.map(String) : [];
    if (symbols === null || symbols.length === 0) {
      c.gap({
        ref: `${pi?.package ?? '?'} <- ${module}`, kind: 'plugin-import', file: pi?.file, line: pi?.line,
        reason: `the candidate contract carries no symbols for "${module}", so the symbol comparison could not be made`,
      });
      continue;
    }
    const missing = wanted.filter((s) => !symbols.includes(s));
    if (missing.length > 0) {
      c.add({
        class: 'B8',
        severity: 'RISKY',
        subject: `${module} (${missing.join(', ')})`,
        evidence: `packages/plugin "${pi?.package ?? '?'}" imports ${quoteList(wanted)} from "${module}"; candidate ${vLabel} packages["${module}"].symbols = ${quoteList(symbols)}; not listed: ${quoteList(missing)}. ` +
          `LIMITATION: the "symbols" field is extracted by regex from built JavaScript (evidenceTier ADVISORY), so a symbol that is genuinely exported can be absent from this list — absence here is a prompt to check, not proof of removal.`,
        evidenceTier: tierFor(e, 'symbols', ADVISORY),
        consumers: consumersOf(pi),
        why: 'a symbol our plugin imports that no longer exists fails at import time, which on the host plane means the plugin does not mount and the boot can fail; the reason this is not BREAKS is that the symbol list is heuristic',
        suggested: `confirm by reading the candidate's own built JavaScript for "${module}" (or by running verify gate G5, which mounts our plugins): if the symbol really is gone, fix ${describeConsumers(pi) || 'the import'} in packages/${pi?.package ?? '<plugin>'}`,
      });
    }
    c.gap({
      ref: `${pi?.package ?? '?'} <- ${module}`, kind: 'plugin-import', file: pi?.file, line: pi?.line,
      reason: 'symbol extraction is ADVISORY; whether our plugin actually loads is decided by a boot; verify gates G3/G5 mount the plugins and are the real check',
    });
  }

  /* ---- B9 CLI drift ---- */
  const binChanged = stableStringify(baselineContract?.dsh?.bin ?? null) !== stableStringify(candidateContract?.dsh?.bin ?? null);
  for (const inv of cliInvocations) {
    const argv = Array.isArray(inv?.argv) ? inv.argv.map(String) : [];
    const subject = `dsh ${argv.join(' ')}`.trim();
    c.add({
      class: 'B9',
      severity: 'INFO',
      subject,
      evidence: `consumed invocation at ${describeConsumers(inv)}: argv = ${quoteList(argv)}. Acceptance is NOT verified here — a contract cannot show whether ${vLabel} still accepts it`,
      evidenceTier: AUTHORITATIVE,
      consumers: consumersOf(inv),
      why: 'an upstream CLI change makes this invocation exit non-zero or silently do something else, and the script that runs it treats that as a normal failure',
      suggested: `re-check by hand against ${vLabel} (node <candidate bin.js> ${argv.join(' ')} --help) before promoting, then update ${describeConsumers(inv) || 'the script'} if the flags moved`,
    });
    c.gap({
      ref: `dsh ${argv.join(' ')}`, kind: 'cli-invocation', file: inv?.file, line: inv?.line,
      reason: 'CLI acceptance cannot be decided from a contract; it needs a real invocation of the candidate binary',
    });
  }
  if (binChanged || surfaceChanged.length > 0) {
    const reasons = [];
    if (binChanged) reasons.push(`dsh bin map changed: ${stableStringify(baselineContract?.dsh?.bin ?? null)} -> ${stableStringify(candidateContract?.dsh?.bin ?? null)}`);
    if (surfaceChanged.length > 0) reasons.push(`consumed package surface changed: ${quoteList(surfaceChanged.map((s) => s.pkg), 12)}`);
    if (cliInvocations.length > 0) {
      c.add({
        class: 'B9',
        severity: 'RISKY',
        subject: 'dsh CLI surface',
        evidence: reasons.join('; '),
        evidenceTier: AUTHORITATIVE,
        consumers: consumersOf(cliInvocations[0] ?? {}),
        why: 'the CLI entry or a package its boot composes changed shape, so a subcommand or flag our scripts call may now be rejected or ignored; every invocation listed in consumed.json is a candidate for re-testing',
        suggested: `run every argv in consumed.cliInvocations against ${vLabel} before promoting (at minimum --help for each subcommand), and treat any non-zero exit as a blocking finding of its own`,
      });
    }
  }

  /* ---- B10 capability gain ---- */
  if (baselineContract === null || baselineContract === undefined || typeof baselinePackages !== 'object') {
    c.gap({ ref: '(all)', kind: 'capability-gain', reason: 'no baseline contract supplied; capability gains cannot be computed (nothing is compared against nothing)' });
  } else {
    const baselineNames = Object.keys(baselinePackages);
    const candidateNames = Object.keys(candidatePackages);
    for (const name of sortedUnique(candidateNames.filter((n) => !baselineNames.includes(n)))) {
      const a = candidatePackages[name];
      if (!a || a.present === false) continue;
      c.add({
        class: 'B10',
        severity: 'CAPABILITY',
        subject: name,
        evidence: `present in ${vLabel} (version ${a.version ?? '?'}, exportSubpaths ${quoteList(a.exportSubpaths)}) and absent from ${bLabel}`,
        evidenceTier: AUTHORITATIVE,
        consumers: [],
        why: 'a package the newer engine ships that the pinned one does not: nothing to fix, but it may remove the need for one of our own plugins',
        suggested: `if this replaces something we patch or vendor, prefer it over our workaround when we next touch that area`,
      });
    }
    for (const name of sortedUnique(candidateNames.filter((n) => baselineNames.includes(n)))) {
      const b = baselinePackages[name];
      const a = candidatePackages[name];
      if (!b || !a || b.present === false || a.present === false) continue;
      if (!Array.isArray(b.exportSubpaths) || !Array.isArray(a.exportSubpaths)) continue;
      const bs = sortedUnique(b.exportSubpaths.map(normSubpath));
      const added = sortedUnique(a.exportSubpaths.map(normSubpath).filter((x) => !bs.includes(x)));
      if (added.length > 0) {
        c.add({
          class: 'B10',
          severity: 'CAPABILITY',
          subject: name,
          evidence: `new exportSubpaths in ${vLabel}: ${quoteList(added)} (was ${quoteList(bs)})`,
          evidenceTier: AUTHORITATIVE,
          consumers: [],
          why: 'a new entry point on a package we already consume',
          suggested: 'no action; available if we need it',
        });
      }
      if (b.dsh && a.dsh && typeof b.dsh === 'object' && typeof a.dsh === 'object') {
        const bKeys = Object.keys(b.dsh);
        const newKeys = Object.keys(a.dsh).filter((k) => !bKeys.includes(k));
        if (newKeys.length > 0) {
          c.add({
            class: 'B10',
            severity: 'CAPABILITY',
            subject: `${name} (dsh)`,
            evidence: `new dsh config keys in ${vLabel}: ${quoteList(newKeys)}`,
            evidenceTier: AUTHORITATIVE,
            consumers: [],
            why: 'a new configuration surface on a package we consume',
            suggested: 'no action; available if we need it',
          });
        }
      }
    }
    if (baselineTree.supplied && candidateTree.supplied && baselineTree.problems.length === 0 && candidateTree.problems.length === 0) {
      const baseIds = new Set(baselineTree.rowIds);
      const addedRows = candidateTree.rowIds.filter((id) => !baseIds.has(id));
      if (addedRows.length > 0) {
        c.add({
          class: 'B10',
          severity: 'CAPABILITY',
          subject: 'tree.rowIds',
          evidence: `${addedRows.length} new row id(s) in ${vLabel}: ${quoteList(addedRows, 20)}`,
          evidenceTier: AUTHORITATIVE,
          consumers: [],
          why: 'rows the newer engine mounts that the pinned one did not',
          suggested: 'no action; check whether any of them duplicates a row we patch today',
        });
      }
    } else if (baselineTree.supplied && candidateTree.supplied) {
      c.gap({ ref: 'tree.rowIds', kind: 'capability-gain', reason: 'one of the two trees did not compose cleanly, so the row-id capability gain could not be computed' });
    } else {
      c.gap({ ref: 'tree.rowIds', kind: 'capability-gain', reason: 'both a baseline tree and a candidate tree are required to compute added row ids' });
    }
  }

  /* ---- finish ---- */
  const { findings, unverified, counts, downgrades, merged, notes } = c.finish();
  const verdict = counts.BREAKS > 0 ? 'BREAKS' : counts.RISKY > 0 ? 'RISKY' : 'SAFE';

  notes.push(`packagesChecked=${packagesChecked.size}; findings=${findings.length}; unverified=${unverified.length}`);
  if (merged > 0) notes.push(`${merged} additional reference(s) were folded into an existing finding as extra consumers (the same breakage named in several files is one finding)`);
  if (downgrades > 0) notes.push(`${downgrades} finding(s) were offered as BREAKS on non-authoritative evidence and were downgraded to RISKY`);
  if (unverified.length > 0) notes.push(`unverified is not empty: ${unverified.length} consumed reference(s) could not be decided by this analysis — a SAFE verdict here means "nothing found", not "nothing left to check"`);
  for (const n of consumeNotes) notes.push(`consumed.json note: ${n}`);

  const out = {
    schemaVersion: 1,
    generatedAt: generatedAtFrom(opts),
    baseline: {
      version: baselineVersion,
      contractSha256: sha256(baselineContractRead.raw),
      treeSha256: baselineTreeRead ? sha256(baselineTreeRead.raw) : null,
    },
    candidate: {
      version: candidateVersion,
      contractSha256: sha256(candidateContractRead.raw),
      treeSha256: candidateTreeRead ? sha256(candidateTreeRead.raw) : null,
    },
    verdict,
    counts,
    findings,
    consumed: {
      packagesChecked: packagesChecked.size,
      unverified,
    },
    notes,
  };
  return out;
}

/* ------------------------------------------------------------------ entry point */

function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`diff: ${err.message}\n\n${USAGE}\n`);
    return 2;
  }
  if (opts.help) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }
  let result;
  try {
    result = run(opts);
  } catch (err) {
    if (err instanceof UsageError || err instanceof InputError) {
      process.stderr.write(`diff: ${err.message}\n`);
      return 2;
    }
    process.stderr.write(`diff: unexpected failure: ${err?.stack ?? err}\n`);
    return 1;
  }
  const text = JSON.stringify(result, null, 2) + '\n';
  if (opts.flags['--out']) {
    const target = path.resolve(opts.flags['--out']);
    try {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      const tmp = `${target}.tmp-${process.pid}`;
      fs.writeFileSync(tmp, text);
      fs.renameSync(tmp, target);
    } catch (err) {
      process.stderr.write(`diff: cannot write "${target}": ${err.message}\n`);
      return 2;
    }
  }
  process.stdout.write(text);
  return 0;
}

process.exitCode = main();

/**
 * Dispatcher-friendly entry point, for a caller that would rather import than spawn:
 *
 *   buildDiff({ baselineContract, candidateContract, consumed, baselineTree, candidateTree,
 *               generatedAt })
 *
 * The standalone CLI stays primary (SPEC: every lib module runs standalone, and lib/cli.mjs spawns
 * this file with its documented flags); this maps one options object onto the same code path.
 */
function buildDiff(options = {}) {
  const flags = {};
  const map = {
    baselineContract: '--baseline-contract', candidateContract: '--candidate-contract',
    consumed: '--consumed', baselineTree: '--baseline-tree', candidateTree: '--candidate-tree',
    generatedAt: '--generated-at',
  };
  for (const [key, flag] of Object.entries(map)) {
    if (options[key] !== undefined && options[key] !== null && options[key] !== '') flags[flag] = String(options[key]);
  }
  for (const req of ['--baseline-contract', '--candidate-contract', '--consumed']) {
    if (!flags[req]) throw new UsageError(`missing required ${req}`);
  }
  return run({ flags });
}

export { buildDiff, run as diff, run, main };
