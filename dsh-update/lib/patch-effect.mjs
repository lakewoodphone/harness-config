#!/usr/bin/env node
/**
 * patch-effect.mjs — does every patch WE own still have its intended EFFECT
 * on a candidate install?
 *
 * WHY THIS EXISTS, AND WHY IT IS NOT PART OF diff.mjs
 *
 * The first end-to-end run of this pipeline (2026-09-23) reported `BREAKS=2` for the candidate
 * `0.1.5-rc.3`, naming `~/.dsh/profiles/web/cordis.patch.yml:248` and claiming our override "is
 * applied to nothing". That claim was FALSE, verified by hand: the row is `disabled: true` in both
 * the baseline and the candidate tree, and no rows were added or removed.
 *
 * The cause is a property of the engine's dump, not a bug in the candidate: the `# == <layer>,
 * patched by <path>` comment is emitted only for SOME patch shapes. A patch entry that sets only
 * `disabled: true` applies perfectly and produces NO annotation. Asserting on the annotation turns
 * "this patch shape prints nothing" into "our customization was lost" -- a confident, authoritative
 * false crisis. That is the single most expensive failure mode this system has ever had.
 *
 * So patch effect is checked here on its own, against the one clean comparison arm that exists:
 * `--dump-default-config`, the profile tree composed WITHOUT our layer. Combine that with the
 * composed tree and the patch file's own text and every claim below is checkable:
 *
 *   composed row + patch intent  -> the patch's values are what the engine actually runs with
 *   composed vs default          -> the patch demonstrably changed something (or did not)
 *   default(candidate) vs default(baseline) -> what upstream ADDED that our restated config
 *                                             would now silently swallow
 *
 * Every assertion in this module rests on AUTHORITATIVE evidence: our own patch file, the engine's
 * own composed tree, and the engine's own default tree. Nothing here reads a comment to decide a
 * verdict, and nothing infers a fault from an ABSENCE of evidence -- a comparison that cannot be
 * made is reported as `unverified`, never as a break.
 *
 * SAFETY: read-only. This module invokes nothing; it reads JSON artifacts and patch files.
 *
 * USAGE
 *   node lib/patch-effect.mjs \
 *     --profile web \
 *     --layer <path-to-cordis.patch.yml> [--layer ...] \
 *     --baseline-composed <tree.json> --candidate-composed <tree.json> \
 *     [--baseline-default <tree.json>] [--candidate-default <tree.json>] \
 *     [--out <report.json>]
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve, basename } from 'node:path';
import { createHash } from 'node:crypto';
import { loadYaml, PARSE_OPTIONS } from './yaml.mjs';

const SCHEMA_VERSION = 1;

const USAGE = 'usage: node lib/patch-effect.mjs --profile <p> --layer <patch.yml> [--layer ...] '
  + '--baseline-composed <tree.json> --candidate-composed <tree.json> '
  + '[--baseline-default <tree.json>] [--candidate-default <tree.json>] [--out <report.json>]';

// ── value normalisation ─────────────────────────────────────────────────────
//
// The engine prints `!!js` expressions verbatim and *unevaluated*, and it normalises the whitespace
// of a folded scalar (`!!js >-`) to single spaces. Our patch file may spell the same expression
// across several lines. Comparing the raw text would therefore invent a difference that the engine
// does not have, so expressions are compared with whitespace collapsed -- and that relaxation is
// recorded on the finding rather than hidden.

function normExpr(s) {
  return String(s).replace(/\s+/g, ' ').trim();
}

/** deepest-path map: dotted leaf path -> a comparable value. */
function leaves(value, prefix = '', out = {}) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const keys = Object.keys(value);
    if (keys.length === 0) { out[prefix] = {}; return out; }
    for (const k of keys) leaves(value[k], prefix ? `${prefix}.${k}` : k, out);
    return out;
  }
  out[prefix] = value;
  return out;
}

/** Is this node one of the engine's unevaluated `!!js` expressions? */
function isJs(v) {
  return Boolean(v) && typeof v === 'object' && !Array.isArray(v)
    && typeof v.__js === 'string' && Object.keys(v).length === 1;
}

function describeValue(v) {
  if (isJs(v)) return `!!js ${normExpr(v.__js)}`;
  if (v === undefined) return 'undefined';
  if (typeof v === 'string') return JSON.stringify(v);
  return JSON.stringify(v);
}

function sameValue(a, b) {
  if (isJs(a) || isJs(b)) {
    return isJs(a) && isJs(b) && normExpr(a.__js) === normExpr(b.__js);
  }
  if (Array.isArray(a) || Array.isArray(b)) return JSON.stringify(a) === JSON.stringify(b);
  if (a && b && typeof a === 'object' && typeof b === 'object') return JSON.stringify(a) === JSON.stringify(b);
  return a === b;
}

// ── patch layer parsing ─────────────────────────────────────────────────────
//
// The layer is a YAML FLOW SEQUENCE of `{ id, config?, disabled? }` maps -- ids are written
// `    id: 'typert-gateway',` inside braces, NOT as a block-sequence `- id:`. Parsing it with the
// harness's own yaml implementation (with the `!!js` tag registered) keeps `config` values intact.

export function parseLayer(path) {
  const text = readFileSync(path, 'utf8');
  const YAML = loadYaml();
  let doc;
  try {
    doc = YAML.parse(text, PARSE_OPTIONS);
  } catch (e) {
    return { path, entries: [], error: `${e.name}: ${e.message.split('\n')[0]}` };
  }
  if (!Array.isArray(doc)) {
    return { path, entries: [], error: `layer did not parse to a sequence (got ${typeof doc})` };
  }
  const entries = [];
  doc.forEach((entry, i) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      entries.push({ index: i, malformed: `entry ${i} is not a mapping` });
      return;
    }
    const hasConfig = entry.config !== undefined;
    const hasDisabled = entry.disabled !== undefined;
    entries.push({
      index: i,
      id: typeof entry.id === 'string' ? entry.id : null,
      config: hasConfig ? entry.config : undefined,
      disabled: hasDisabled ? entry.disabled : undefined,
      hasConfig,
      hasDisabled,
      // An entry that neither sets config nor disabled does nothing we can verify. It is reported
      // rather than ignored, because a no-op entry in a patch layer is usually a mistake.
      inert: !hasConfig && !hasDisabled,
    });
  });
  return { path, entries, error: null, sha256: createHash('sha256').update(text).digest('hex') };
}

// ── tree loading ────────────────────────────────────────────────────────────

function loadTree(path, label) {
  if (!path) return { label, path: null, rows: null, present: false };
  if (!existsSync(path)) return { label, path, rows: null, present: false, error: 'file absent' };
  try {
    const t = JSON.parse(readFileSync(path, 'utf8'));
    const rows = Array.isArray(t.rows) ? t.rows : null;
    // A tree with zero rows and a `failure` is a REFUSAL, not an empty health. Never let it read as
    // "no differences".
    if (!rows || rows.length === 0) {
      return { label, path, rows: null, present: false, error: t.failure ? `tree run failed: ${t.failure}` : 'tree has no rows' };
    }
    return { label, path, rows, present: true, exitCode: t.exitCode, engineVersion: t.engineVersion };
  } catch (e) {
    return { label, path, rows: null, present: false, error: `${e.name}: ${e.message}` };
  }
}

function findRow(tree, id) {
  if (!tree || !tree.rows) return null;
  return tree.rows.find((r) => r && r.id === id) || null;
}

function rowDisabled(row) {
  // A row may carry a literal boolean, or a raw unevaluated expression. Both are reported; only the
  // literal can be compared to a patch's literal.
  if (!row) return { value: undefined, expr: null, comparable: false };
  if (typeof row.disabled === 'boolean') return { value: row.disabled, expr: row.disabledExpr ?? null, comparable: true };
  if (isJs(row.disabled)) return { value: undefined, expr: normExpr(row.disabled.__js), comparable: false };
  if (typeof row.disabledExpr === 'string') return { value: undefined, expr: normExpr(row.disabledExpr), comparable: false };
  return { value: undefined, expr: null, comparable: false };
}

// ── the check ───────────────────────────────────────────────────────────────

export function checkPatchEffect(options) {
  const {
    profile = 'web',
    layers = [],
    baselineComposed,
    candidateComposed,
    baselineDefault = null,
    candidateDefault = null,
    now = new Date(),
  } = options;

  const findings = [];
  const unverified = [];
  const targets = [];
  let n = 0;
  const add = (f) => { n += 1; findings.push({ id: `E${String(n).padStart(3, '0')}`, profile, ...f }); };

  const baseC = loadTree(baselineComposed, 'baseline-composed');
  const candC = loadTree(candidateComposed, 'candidate-composed');
  const baseD = loadTree(baselineDefault, 'baseline-default');
  const candD = loadTree(candidateDefault, 'candidate-default');

  const trees = { baseC, candC, baseD, candD };
  for (const t of Object.values(trees)) {
    if (t.path && !t.present) {
      // A missing or failed arm is a gap in the evidence, not a fault in the candidate.
      unverified.push({ ref: t.label, file: t.path, reason: t.error || 'arm not supplied' });
    }
  }

  if (!candC.present) {
    return finish({
      findings, unverified, targets, trees,
      fatal: `the candidate composed tree is unusable (${candC.error || 'not supplied'}) — `
        + 'no patch-effect claim can be made, and this is NOT a clean result',
      now, profile, layers,
    });
  }

  const parsedLayers = layers.map((p) => ({ ...parseLayer(p), declared: p }));

  for (const layer of parsedLayers) {
    if (layer.error) {
      unverified.push({ ref: basename(layer.path), file: layer.path, reason: `layer could not be parsed: ${layer.error}` });
      continue;
    }
    for (const entry of layer.entries) {
      if (entry.malformed) {
        unverified.push({ ref: `${basename(layer.path)}[${entry.index}]`, file: layer.path, reason: entry.malformed });
        continue;
      }
      if (!entry.id) {
        unverified.push({ ref: `${basename(layer.path)}[${entry.index}]`, file: layer.path, reason: 'entry has no string id; a patch with no target cannot be checked' });
        continue;
      }

      const consumers = [{ file: layer.path, line: null, index: entry.index }];
      const candRow = findRow(candC, entry.id);
      const baseRow = findRow(baseC, entry.id);

      const rec = {
        id: entry.id,
        layer: layer.path,
        setsConfig: entry.hasConfig,
        setsDisabled: entry.hasDisabled,
        inert: entry.inert,
        presentInCandidate: Boolean(candRow),
        presentInBaseline: Boolean(baseRow),
        verdict: 'OK',
        checks: [],
        consumers,
      };

      // 1. The row the patch targets must exist, or our entry is a silent no-op.
      if (!candRow) {
        rec.verdict = 'BREAKS';
        add({
          class: 'E1', severity: 'BREAKS', subject: entry.id,
          evidence: `our patch layer ${layer.path} entry ${entry.index} targets row id "${entry.id}"; `
            + `that row id is absent from the candidate composed tree (${candC.rows.length} rows)`,
          evidenceTier: 'AUTHORITATIVE',
          why: 'the engine composes a tree with no row by this id, so our entry configures nothing at all',
          suggested: 'find what upstream renamed this row to and re-target the patch entry; do not ship until it applies',
          consumers,
        });
        targets.push(rec);
        continue;
      }

      // 2. `disabled` intent.
      if (entry.hasDisabled) {
        const d = rowDisabled(candRow);
        if (!d.comparable) {
          rec.checks.push({ what: 'disabled', ok: null, detail: `candidate row disabled is not a literal (${d.expr ? `expression: ${d.expr}` : 'absent'}); cannot compare to patch literal ${JSON.stringify(entry.disabled)}` });
          unverified.push({ ref: `${entry.id}.disabled`, file: layer.path, reason: `candidate row disabled is not a literal (${d.expr || 'absent'})` });
        } else if (d.value !== entry.disabled) {
          rec.verdict = 'BREAKS';
          rec.checks.push({ what: 'disabled', ok: false, expected: entry.disabled, actual: d.value });
          add({
            class: 'E2', severity: 'BREAKS', subject: entry.id,
            evidence: `our patch layer ${layer.path} sets disabled: ${JSON.stringify(entry.disabled)} for row "${entry.id}"; `
              + `the candidate composed tree shows disabled: ${JSON.stringify(d.value)}`,
            evidenceTier: 'AUTHORITATIVE',
            why: 'the patch applies but a later layer overrides it, so the row is enabled (or disabled) against our intent',
            suggested: `inspect which layer now wins for row "${entry.id}" before shipping`,
            consumers,
          });
        } else {
          // The decisive case in this whole module: a disable-only patch has NO `patched by`
          // annotation, and this comparison is why we can still be sure it applies.
          rec.checks.push({ what: 'disabled', ok: true, actual: d.value, annotation: candRow.patchedBy ?? null });
        }
      }

      // 3. `config` intent, leaf by leaf.
      if (entry.hasConfig) {
        const want = leaves(entry.config);
        const got = leaves(candRow.config ?? {});
        const bad = [];
        const missing = [];
        for (const [path, v] of Object.entries(want)) {
          if (!(path in got)) { missing.push(path); continue; }
          if (!sameValue(v, got[path])) bad.push({ path, expected: v, actual: got[path] });
        }
        if (missing.length > 0 || bad.length > 0) {
          rec.verdict = 'BREAKS';
          rec.checks.push({ what: 'config', ok: false, missing, differing: bad.map((b) => b.path) });
          add({
            class: 'E3', severity: 'BREAKS', subject: entry.id,
            evidence: `our patch layer ${layer.path} sets ${Object.keys(want).length} config leaf/leaves on row "${entry.id}"; `
              + `the candidate composed row is missing ${JSON.stringify(missing)} `
              + `and differs on ${JSON.stringify(bad.map((b) => `${b.path}: expected ${describeValue(b.expected)}, got ${describeValue(b.actual)}`))}`,
            evidenceTier: 'AUTHORITATIVE',
            why: 'a config value we depend on is not what the engine will run with — it was dropped or overridden',
            suggested: `re-state the missing leaf in the patch entry for "${entry.id}" and re-run`,
            consumers,
          });
        } else {
          rec.checks.push({ what: 'config', ok: true, leaves: Object.keys(want).length });
        }
      }

      // 4. A patch that provably changes nothing is worth surfacing: either our entry is inert, or
      //    upstream already sets what we set. Not a fault, but never silently nothing.
      if (entry.inert) {
        rec.verdict = rec.verdict === 'OK' ? 'INERT' : rec.verdict;
        add({
          class: 'E4', severity: 'INFO', subject: entry.id,
          evidence: `patch layer ${layer.path} entry ${entry.index} sets neither config nor disabled`,
          evidenceTier: 'AUTHORITATIVE',
          why: 'the entry does nothing; it is dead weight and may be a leftover',
          suggested: 'delete it, or state what it was meant to do',
          consumers,
        });
      } else if (baseD.present && candD.present) {
        const b = findRow(baseD, entry.id);
        const c = findRow(candD, entry.id);
        if (b && c) {
          const bl = leaves(b.config ?? {});
          const cl = leaves(c.config ?? {});
          const want = entry.hasConfig ? leaves(entry.config) : {};
          // Keys upstream newly added to the row's UNPATCHED default, which our restated config
          // will now swallow. This is the P48 class, caught before it ships.
          const added = Object.keys(cl).filter((k) => !(k in bl) && !(k in want));
          if (added.length > 0) {
            rec.verdict = rec.verdict === 'OK' ? 'RISKY' : rec.verdict;
            add({
              class: 'E5', severity: 'RISKY', subject: entry.id,
              evidence: `upstream's UNPATCHED default for row "${entry.id}" gained ${JSON.stringify(added)} against the baseline, `
                + `and our patch entry restates this row's whole config without them`,
              evidenceTier: 'AUTHORITATIVE',
              why: 'a patch replaces the targeted row entire config, so these new upstream defaults revert to whatever the plugin hardcodes — silently, with no error (this is the trustedHosts incident, PAIN P48)',
              suggested: `add ${JSON.stringify(added)} to the patch entry for "${entry.id}" — restate the upstream value explicitly`,
              consumers,
            });
          }
        }
      }

      targets.push(rec);
    }
  }

  return finish({ findings, unverified, targets, trees, fatal: null, now, profile, layers });
}

function finish({ findings, unverified, targets, trees, fatal, now, profile, layers }) {
  const counts = { BREAKS: 0, RISKY: 0, INFO: 0 };
  for (const f of findings) counts[f.severity] = (counts[f.severity] ?? 0) + 1;
  const verdict = fatal ? 'UNVERIFIED' : counts.BREAKS > 0 ? 'BREAKS' : counts.RISKY > 0 ? 'RISKY' : 'SAFE';
  const order = { BREAKS: 0, RISKY: 1, INFO: 2 };
  findings.sort((a, b) => (order[a.severity] - order[b.severity]) || String(a.subject).localeCompare(String(b.subject)) || a.id.localeCompare(b.id));

  return {
    schemaVersion: SCHEMA_VERSION,
    generatedAt: now.toISOString(),
    host: process.env.COMPUTERNAME || null,
    profile,
    verdict,
    fatal,
    counts,
    layers: layers.map((p) => ({ path: p })),
    arms: Object.fromEntries(Object.entries(trees).map(([k, t]) => [k, {
      path: t.path, present: t.present, rows: t.rows ? t.rows.length : null,
      exitCode: t.exitCode ?? null, error: t.error ?? null,
    }])),
    targets,
    findings,
    unverified,
    notes: [
      'Every verdict here rests on our own patch file plus the engine\'s own composed and '
      + 'default-composed trees (AUTHORITATIVE). No verdict reads the `patched by` comment, because '
      + 'a disable-only patch applies with no annotation (measured 2026-09-23).',
      'A comparison that could not be made appears in `unverified`, never as a break.',
    ],
  };
}

// ── CLI ─────────────────────────────────────────────────────────────────────

export function parseArgs(argv) {
  const args = {
    profile: 'web', layers: [], baselineComposed: null, candidateComposed: null,
    baselineDefault: null, candidateDefault: null, out: null,
  };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--profile') args.profile = need('--profile');
    else if (a === '--layer') args.layers.push(need('--layer'));
    else if (a === '--baseline-composed') args.baselineComposed = need('--baseline-composed');
    else if (a === '--candidate-composed') args.candidateComposed = need('--candidate-composed');
    else if (a === '--baseline-default') args.baselineDefault = need('--baseline-default');
    else if (a === '--candidate-default') args.candidateDefault = need('--candidate-default');
    else if (a === '--out') args.out = need('--out');
    else if (a === '-h' || a === '--help') args.help = true;
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

export function renderText(report) {
  const L = [];
  L.push(`patch-effect: profile ${report.profile}  verdict ${report.verdict}`
    + `  BREAKS=${report.counts.BREAKS} RISKY=${report.counts.RISKY} INFO=${report.counts.INFO}`);
  for (const [k, a] of Object.entries(report.arms)) {
    L.push(`  arm ${k.padEnd(18)} ${a.present ? `${a.rows} rows` : `UNUSABLE (${a.error})`}`);
  }
  if (report.fatal) L.push(`  FATAL: ${report.fatal}`);
  for (const t of report.targets) {
    const marks = t.checks.map((c) => `${c.what}:${c.ok === true ? 'ok' : c.ok === null ? 'n/a' : 'FAIL'}`).join(' ');
    L.push(`  ${t.verdict.padEnd(7)} ${t.id.padEnd(24)} ${marks}`);
  }
  for (const f of report.findings) {
    L.push(`  [${f.severity}] ${f.id} ${f.class} ${f.subject}`);
    L.push(`      ${f.evidence}`);
  }
  if (report.unverified.length > 0) {
    L.push(`  UNVERIFIED (${report.unverified.length}) — not checked, not a pass:`);
    for (const u of report.unverified) L.push(`      ${u.ref}: ${u.reason}`);
  }
  return L.join('\n');
}

const invokedDirectly = Boolean(process.argv[1]) && resolve(process.argv[1]).endsWith('patch-effect.mjs');
if (invokedDirectly) {
  try {
    const args = parseArgs(process.argv.slice(2));
    if (args.help) { console.log(USAGE); process.exit(0); }
    if (!args.candidateComposed) { console.error(USAGE); process.exit(2); }
    if (args.layers.length === 0) { console.error(`${USAGE}\n--layer is required: with no patch layers there is nothing to check, and an empty result would look like health`); process.exit(2); }
    const report = checkPatchEffect(args);
    if (args.out) {
      mkdirSync(dirname(resolve(args.out)), { recursive: true });
      writeFileSync(resolve(args.out), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
      console.log(`patch-effect.mjs: wrote ${resolve(args.out)} (verdict ${report.verdict})`);
      console.log(renderText(report));
    } else {
      console.log(JSON.stringify(report, null, 2));
    }
    // Exit non-zero only on a real BREAKS. RISKY/INFO are for a human to read, not a stop signal.
    process.exit(report.counts.BREAKS > 0 ? 1 : 0);
  } catch (e) {
    console.error(`patch-effect.mjs: ${e.message}`);
    process.exit(2);
  }
}
