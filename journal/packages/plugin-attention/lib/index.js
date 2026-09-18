/**
 * dsh-plugin-attention — `/attention`: what the company already knows, in the composer.
 *
 * WHY THIS EXISTS
 * Two sensing paths work and reached nobody. On 2026-09-14 the autosync recorded a refused
 * pull every fifteen minutes for seventy-five minutes —
 *   {"result":"attention","detail":"pull --ff-only refused: histories diverged (5 behind)"}
 * — and the kernel's `config_sync` check already escalates any `result != "clean"` to HIGH.
 * The phone probe has written a verdict the kernel reads since the same morning. Nothing was
 * missing from the sensing; nothing delivered it. The owner learned about the blocked deploy
 * because a person happened to try one.
 *
 * This is the smallest honest consumer: a command in the composer he already types in, which
 * prints what is being reported right now, with the source and the age of every reading.
 *
 * WHY A COMMAND AND NOT A BADGE (yet)
 * A badge needs the client half to ask the host half for data. In this deployment that
 * channel (`harness.handle` + `host.call`) belongs to the dynamic Cordis runner, which is
 * deliberately disabled in this preset; ordinary static plugins get `ctx.get('<service>')`
 * and host `commands`. A command needs no channel, no new service and no permission. The
 * badge is worth doing later, by whichever of those two routes is chosen deliberately.
 *
 * WHAT IT READS — read-only, and every line says where it came from and how old it is:
 *   $CEO_KERNEL_STATE/latest.json          the kernel's findings  (default ~/ceo-kernel-var)
 *   ~/.dsh-phone/probe.json                the phone path's verdict
 *   ~/.harness-config-autosync/status.json the harness-config sync
 *
 * A reading that is missing or too old is reported as exactly that, never as health.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const name = 'attention';

const KERNEL_STATE = process.env.CEO_KERNEL_STATE || path.join(os.homedir(), 'ceo-kernel-var');
const SOURCES = [
  { label: 'kernel findings', file: path.join(KERNEL_STATE, 'latest.json'), staleMinutes: 20 },
  { label: 'phone probe', file: path.join(os.homedir(), '.dsh-phone', 'probe.json'), staleMinutes: 20 },
  { label: 'config sync', file: path.join(os.homedir(), '.harness-config-autosync', 'status.json'), staleMinutes: 45 },
];

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    return undefined;
  }
}

/** Age in minutes of a stamp the source itself wrote, or undefined if it carries none. */
function ageMinutes(doc) {
  const stamp = doc && (doc.at || doc.iso || doc.ts);
  let millis;
  if (typeof stamp === 'number') millis = stamp > 1e12 ? stamp : stamp * 1000;
  else if (typeof stamp === 'string') millis = Date.parse(stamp);
  if (!Number.isFinite(millis)) return undefined;
  return Math.max(0, Math.round((Date.now() - millis) / 60000));
}

function human(minutes) {
  if (minutes === undefined) return 'age unknown';
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

/** Build the report. Pure enough to test: takes the three documents, returns text. */
export function attentionReport(docs) {
  const [kernel, probe, sync] = docs;
  const lines = [];

  // 1. the kernel's findings: the only place the company's own checks are summarised
  if (kernel === undefined) {
    lines.push(`kernel findings: NOT READABLE (${SOURCES[0].file}) — nothing below is proven current`);
  } else {
    const age = ageMinutes(kernel);
    const summary = kernel.summary || {};
    lines.push(`Company findings — kernel report written ${human(age)} on ${kernel.host || '?'} ` +
               `(${summary.total ?? '?'} checks: ${summary.ok ?? '?'} ok, ${summary.attention ?? '?'} needing attention)`);
    const findings = kernel.findings || [];
    const attention = findings.filter((f) => f.needs_attention || (f.ok === false && f.severity !== 'info'));
    if (attention.length === 0) {
      lines.push('  nothing needs attention');
    } else {
      lines.push('');
      for (const f of attention) {
        lines.push(`  ${String(f.severity || '?').toUpperCase().padEnd(6)} ${String(f.check)}: ${f.summary}`);
      }
    }
    const quiet = findings.filter((f) => !attention.includes(f)).map((f) => f.check);
    if (quiet.length) lines.push(`\n  quiet: ${quiet.join(', ')}`);
  }

  // 2. sensing that has stopped is itself a finding
  lines.push('');
  lines.push('Sensing:');
  if (probe !== undefined) {
    const age = ageMinutes(probe);
    const stale = age !== undefined && age > SOURCES[1].staleMinutes;
    lines.push(`  phone path    ${probe.passed}/${probe.total} checks, ${human(age)}` +
               (stale ? '  <- STALE, nothing is proving the phone works' : ''));
  } else {
    lines.push(`  phone path    no verdict at ${SOURCES[1].file}`);
  }
  if (sync !== undefined) {
    const age = ageMinutes(sync);
    const result = String(sync.result || 'unknown');
    const stale = age !== undefined && age > SOURCES[2].staleMinutes;
    lines.push(`  config sync   ${result} ${human(age)}${sync.detail ? `: ${sync.detail}` : ''}` +
               (stale ? '  <- STALE' : ''));
  } else {
    lines.push(`  config sync   no record at ${SOURCES[2].file}`);
  }
  lines.push('');
  lines.push('Read-only. Each reading carries the source and age above; a missing one is said out loud.');
  return lines.join('\n');
}

/** Hard dependency: the command registry is the whole surface. */
const inject = ['commands'];

function apply(ctx) {
  const dispose = ctx.commands.register({
    name: 'attention',
    description: 'What the company is reporting: kernel findings, the phone path, config sync',
    handler: () => {
      try {
        const docs = SOURCES.map((source) => readJson(source.file));
        return { kind: 'success', text: attentionReport(docs) };
      } catch (error) {
        return { kind: 'error', text: `Could not read the findings: ${error.message}` };
      }
    },
  });
  ctx.effect(() => dispose);
}

export { name, inject, apply };
