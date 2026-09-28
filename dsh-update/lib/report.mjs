#!/usr/bin/env node
/**
 * dsh-update / lib/report.mjs — diff.json -> report.md
 *
 *   node lib/report.mjs --diff <diff.json> [--out <report.md>]
 *
 * Markdown a busy person can read in under a minute. It renders the artifact and nothing else: no
 * marketing, no restating what the diff is, no section omitted. `## Not checked` is always printed,
 * because a SAFE verdict with a silent gap list is a lie.
 */

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const USAGE = `usage: node lib/report.mjs --diff <diff.json> [--out <report.md>]

Renders a diff.json produced by lib/diff.mjs as readable markdown on stdout (and to --out when
given). Exit 0 on success; non-zero with a diagnostic on stderr on failure.`;

class UsageError extends Error {}
class InputError extends Error {}

function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') return { help: true };
    const eq = a.indexOf('=');
    const key = eq > 0 ? a.slice(0, eq) : a;
    if (key !== '--diff' && key !== '--out') throw new UsageError(`unknown argument "${a}"`);
    const value = eq > 0 ? a.slice(eq + 1) : argv[++i];
    if (value === undefined) throw new UsageError(`missing value for ${key}`);
    flags[key] = value;
  }
  if (!flags['--diff']) throw new UsageError('missing required --diff <diff.json>');
  return { flags };
}

function readDiff(file) {
  const abs = path.resolve(file);
  let raw;
  try {
    raw = fs.readFileSync(abs);
  } catch (err) {
    throw new InputError(`cannot read "${abs}" (${err.code ?? err.message})`);
  }
  let diff;
  try {
    diff = JSON.parse(raw.toString('utf8'));
  } catch (err) {
    throw new InputError(`"${abs}" is not valid JSON: ${err.message}`);
  }
  if (!diff || typeof diff !== 'object' || !Array.isArray(diff.findings)) {
    throw new InputError(`"${abs}" has no findings array — was it produced by lib/diff.mjs?`);
  }
  return diff;
}

const SEVERITIES = ['BREAKS', 'RISKY', 'CAPABILITY', 'INFO'];
const VERDICT_MARK = { BREAKS: '⛔', RISKY: '⚠️', CAPABILITY: '➕', INFO: 'ℹ️' };

function where(finding) {
  const rows = Array.isArray(finding.consumers) ? finding.consumers : [];
  const parts = rows
    .map((c) => (c && c.file ? (c.line === null || c.line === undefined ? c.file : `${c.file}:${c.line}`) : null))
    .filter(Boolean);
  return parts.length === 0 ? 'consumed.json carries no file/line for this reference' : parts.join(', ');
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function render(diff) {
  const findings = diff.findings;
  const counts = diff.counts ?? {};
  const unverified = Array.isArray(diff.consumed?.unverified) ? diff.consumed.unverified : [];
  const by = (sev) => findings.filter((f) => f.severity === sev);
  const from = diff.baseline?.version ?? 'unknown';
  const to = diff.candidate?.version ?? 'unknown';
  const out = [];

  const breaks = by('BREAKS');
  const risky = by('RISKY');
  const caps = by('CAPABILITY');
  const infos = by('INFO');
  const n = (sev) => (typeof counts[sev] === 'number' ? counts[sev] : by(sev).length);

  /* 1. verdict, one line */
  out.push(`# dsh-update: ${from} → ${to} — ${diff.verdict}`);
  out.push('');
  const tally = ['BREAKS', 'RISKY', 'CAPABILITY', 'INFO'].map((s) => `${n(s)} ${s.toLowerCase()}`).join(', ');
  const gapNote = unverified.length === 0
    ? 'every consumed reference was checked'
    : `${plural(unverified.length, 'consumed reference', 'consumed references')} could NOT be checked from a contract (see Not checked)`;
  out.push(`**${diff.verdict}** for ${from} → ${to}: ${tally}; ${n('INFO') === 0 ? '' : ''}${plural(diff.consumed?.packagesChecked ?? 0, 'package', 'packages')} cross-referenced, ${gapNote}.`);
  out.push('');

  /* 2. counts table */
  out.push('| severity | count |');
  out.push('| --- | --- |');
  for (const s of SEVERITIES) out.push(`| ${SEVERITIES.indexOf(s) === 0 ? '**BREAKS**' : s} | ${n(s)} |`);
  out.push('');

  /* 3. BREAKS in full */
  out.push(`## BREAKS (${breaks.length})`);
  out.push('');
  if (breaks.length === 0) {
    out.push('none.');
    out.push('');
  }
  for (const f of breaks) {
    out.push(`### ${f.id} · ${f.class} · ${f.subject}`);
    out.push('');
    out.push(`- **What breaks:** ${f.why}`);
    out.push(`- **Where we depend on it:** ${where(f)}`);
    out.push(`- **What we saw:** ${f.evidence}`);
    out.push(`- **Do this:** ${f.suggested}`);
    out.push(`- **Evidence tier:** ${f.evidenceTier}${f.downgradedFrom ? ` (offered as ${f.downgradedFrom}, downgraded — only AUTHORITATIVE evidence may declare BREAKS)` : ''}`);
    out.push('');
  }

  /* 4. RISKY condensed */
  out.push(`## RISKY (${risky.length})`);
  out.push('');
  if (risky.length === 0) {
    out.push('none.');
    out.push('');
  }
  for (const f of risky) {
    out.push(`- **${f.id} · ${f.class} · ${f.subject}** — ${f.why}`);
    out.push(`  - evidence (${f.evidenceTier}): ${f.evidence}`);
    out.push(`  - depends on it: ${where(f)}`);
    out.push(`  - do this: ${f.suggested}`);
  }
  if (risky.length > 0) out.push('');

  /* 5. capability gains */
  out.push(`## CAPABILITY gains (${caps.length})`);
  out.push('');
  if (caps.length === 0) {
    out.push('nothing new.');
    out.push('');
  }
  for (const f of caps) {
    out.push(`- **${f.subject}** — ${f.evidence}`);
  }
  if (caps.length > 0) out.push('');

  /* 5b. INFO, one line each (kept because B9's argv list is only useful if it is visible) */
  out.push(`## INFO (${infos.length})`);
  out.push('');
  if (infos.length === 0) {
    out.push('none.');
    out.push('');
  }
  for (const f of infos) {
    out.push(`- **${f.subject}** — ${f.evidence}`);
  }
  if (infos.length > 0) out.push('');

  /* 6. Not checked — never omitted */
  out.push('## Not checked');
  out.push('');
  if (unverified.length === 0) {
    out.push('nothing.');
  } else {
    out.push(`${plural(unverified.length, 'consumed reference', 'consumed references')} this contract analysis could not decide. Identical references are grouped; the ungrouped list is in the diff.json beside this report.`);
    out.push('');
    const groups = new Map();
    for (const u of unverified) {
      const key = `${u.kind}\u0000${u.ref}\u0000${u.reason}`;
      if (!groups.has(key)) groups.set(key, { kind: u.kind, ref: u.ref, reason: u.reason, where: [] });
      const g = groups.get(key);
      const loc = u.file ? (u.line === null || u.line === undefined ? u.file : `${u.file}:${u.line}`) : 'no file recorded';
      if (!g.where.includes(loc)) g.where.push(loc);
    }
    for (const g of groups.values()) {
      const shown = g.where.slice(0, 3).join(', ');
      const more = g.where.length > 3 ? ` (+${g.where.length - 3} more)` : '';
      out.push(`- \`${g.ref}\` (${g.kind}, ${g.where.length} location${g.where.length === 1 ? '' : 's'}: ${shown}${more}) — ${g.reason}`);
    }
  }
  out.push('');
  return out.join('\n');
}

function main() {
  let parsed;
  try {
    parsed = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`report: ${err.message}\n\n${USAGE}\n`);
    return 2;
  }
  if (parsed.help) { process.stdout.write(`${USAGE}\n`); return 0; }
  let diff;
  try {
    diff = readDiff(parsed.flags['--diff']);
  } catch (err) {
    process.stderr.write(`report: ${err.message}\n`);
    return 2;
  }
  const text = render(diff);
  if (parsed.flags['--out']) {
    const target = path.resolve(parsed.flags['--out']);
    try {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      const tmp = `${target}.tmp-${process.pid}`;
      fs.writeFileSync(tmp, text);
      fs.renameSync(tmp, target);
    } catch (err) {
      process.stderr.write(`report: cannot write "${target}": ${err.message}\n`);
      return 2;
    }
  }
  process.stdout.write(text);
  return 0;
}

process.exitCode = main();
