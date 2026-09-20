#!/usr/bin/env node
/**
 * `gov` — the admission governor from a shell.
 *
 * One implementation, two entry points: this CLI for scripts and humans, and the
 * `admission_governor` tool registered by dsh-plugin-health for agents. Both call
 * the same protocol module, so a hand-run `gov acquire` and an agent's request go
 * through identical logic — there is no second copy of the rules to drift.
 *
 * USAGE
 *   node packages/plugin-health/bin/governor.mjs status [--json]
 *   node packages/plugin-health/bin/governor.mjs acquire [--kind <k>] [--note <n>]
 *                                            [--ttl-ms N] [--wait-ms N] [--json]
 *   node packages/plugin-health/bin/governor.mjs renew  --id <id> [--ttl-ms N]
 *   node packages/plugin-health/bin/governor.mjs release --id <id>
 *   node packages/plugin-health/bin/governor.mjs reap
 *
 * EXIT CODES — a script branches on these, so they are the contract:
 *   0  granted / renewed / released / status printed
 *   10 queued (no slot free right now; the position is printed)
 *   1  usage or operational error
 *
 * WHAT IT NEVER DOES
 * It never refuses. A caller that cannot be granted a slot is told its queue
 * position and exits 10. The only hard failures are a bad argument or a
 * filesystem error, and both are reported with the reason.
 *
 * The lease directory defaults to `$DSH_HOME/governor` (or `~/.dsh/governor`),
 * overridable with `--root` so a test can use a scratch directory.
 */

import os from 'node:os';
import path from 'node:path';

import {
  acquire,
  acquireWaiting,
  deriveBudget,
  governorRoot,
  release,
  renew,
  reap,
  status,
  PER_SLOT_BYTES_DEFAULT,
  MAX_SLOTS_DEFAULT,
  MIN_SLOTS_DEFAULT,
  TTL_MS_DEFAULT,
} from '../lib/governor.js';

function parseArgs(argv) {
  const out = { command: argv[0], flags: {} };
  for (let index = 1; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (next === undefined || next.startsWith('--')) {
      out.flags[key] = true;
    } else {
      out.flags[key] = next;
      index += 1;
    }
  }
  return out;
}

const number = (value, fallback) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

function usage() {
  return [
    'gov — admission governor for heavy work (never refuses; queues instead)',
    '',
    '  status  [--json]',
    '  acquire [--kind <k>] [--note <n>] [--ttl-ms N] [--wait-ms N] [--json]',
    '  renew   --id <id> [--ttl-ms N]',
    '  release --id <id>',
    '  reap',
    '',
    '  --root <dir>      lease directory (default $DSH_HOME/governor)',
    '  --per-slot-bytes  measured cost of one heavy slot',
    '  --max-slots       ceiling',
    '  --min-slots       floor (the budget never falls below this)',
    '',
    'exit 0 granted/printed, 10 queued, 1 error',
  ].join('\n');
}

async function main() {
  const { command, flags } = parseArgs(process.argv.slice(2));
  if (command === undefined || flags.help === true) {
    process.stdout.write(`${usage()}\n`);
    return 0;
  }
  const dshHome = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
  const root = typeof flags.root === 'string' ? flags.root : governorRoot(dshHome);
  const budgetOptions = {
    perSlotBytes: number(flags['per-slot-bytes'], PER_SLOT_BYTES_DEFAULT),
    maxSlots: number(flags['max-slots'], MAX_SLOTS_DEFAULT),
    minSlots: number(flags['min-slots'], MIN_SLOTS_DEFAULT),
  };
  const json = flags.json === true;
  const ttlMs = number(flags['ttl-ms'], TTL_MS_DEFAULT);

  switch (command) {
    case 'status': {
      const view = status({ root, ...budgetOptions });
      if (json) {
        process.stdout.write(`${JSON.stringify(view, null, 2)}\n`);
        return 0;
      }
      const lines = [
        `governor on ${view.host}: ${view.inUse} of ${view.budget} slot(s) in use, ${view.free} free, ${view.waiters} waiting`,
        `  derivation   ${view.derivation}`,
        `  memory       ${view.freeMiB} MiB free of ${view.totalMiB} MiB, ${view.reserveMiB} MiB reserved`
          + (view.headroomLow ? '  <- HEADROOM LOW: the budget is at its floor, work is still granted' : ''),
      ];
      if (view.holders.length === 0) lines.push('  holders      none');
      for (const holder of view.holders) {
        lines.push(`  slot ${String(holder.slot).padStart(2)}      pid ${holder.pid} ${holder.kind}`
          + ` — held ${Math.round(holder.heldMs / 1000)}s, renewed ${Math.round(holder.renewedAgoMs / 1000)}s ago,`
          + ` expires in ${Math.round(holder.expiresInMs / 1000)}s${holder.note === '' ? '' : `  (${holder.note})`}`);
      }
      for (const dead of view.deadLeases) {
        lines.push(`  slot ${String(dead.slot).padStart(2)}      DEAD pid ${dead.pid}${dead.corrupt ? ' (corrupt lease)' : ` expired ${Math.round(dead.expiredForMs / 1000)}s ago`}`);
      }
      if (view.reaped.length > 0) {
        lines.push(`  reaped       ${view.reaped.map((entry) => `${entry.slot}:${entry.outcome}`).join(', ')}`);
      }
      lines.push('  read-only. Every number above came from the lease directory and measured memory in this process.');
      process.stdout.write(`${lines.join('\n')}\n`);
      return 0;
    }
    case 'acquire': {
      const request = {
        root,
        ...budgetOptions,
        kind: typeof flags.kind === 'string' ? flags.kind : 'cli',
        note: typeof flags.note === 'string' ? flags.note : '',
        ttlMs,
      };
      const waitMs = number(flags['wait-ms'], 0);
      const outcome = waitMs > 0 ? await acquireWaiting({ ...request, timeoutMs: waitMs }) : acquire(request);
      if (json) {
        process.stdout.write(`${JSON.stringify(outcome, null, 2)}\n`);
        return outcome.state === 'granted' ? 0 : 10;
      }
      if (outcome.state === 'granted') {
        process.stdout.write(`GRANTED slot ${outcome.lease.slot} id ${outcome.lease.id}`
          + ` ttl ${Math.round(outcome.lease.ttlMs / 1000)}s\n`);
        process.stdout.write(`  ${outcome.budget.arithmetic}\n`);
        process.stdout.write(`  release with: node bin/governor.mjs release --id ${outcome.lease.id}\n`);
        return 0;
      }
      process.stdout.write(`QUEUED position ${outcome.position + 1}`
        + ` (${outcome.active} active of ${outcome.budget.budget}, ${outcome.waiters} waiting)\n`);
      process.stdout.write(`  ${outcome.budget.arithmetic}\n`);
      process.stdout.write(`  nothing was refused: re-run with --wait-ms N to wait for a slot, or proceed and accept the extra load.\n`);
      return 10;
    }
    case 'renew': {
      const id = flags.id;
      if (typeof id !== 'string') {
        process.stderr.write('renew needs --id <id>\n');
        return 1;
      }
      const document = renew(root, id, ttlMs);
      if (document === undefined) {
        process.stdout.write('LOST: no lease with that id is held\n');
        return 1;
      }
      process.stdout.write(`RENEWED slot ${document.slot} until ${new Date(document.expiresAt).toISOString()}\n`);
      return 0;
    }
    case 'release': {
      const id = flags.id;
      if (typeof id !== 'string') {
        process.stderr.write('release needs --id <id>\n');
        return 1;
      }
      const outcome = release(root, id);
      process.stdout.write(outcome.released ? `RELEASED slot ${outcome.slot}\n` : 'NOT-HELD: nothing released\n');
      return outcome.released ? 0 : 1;
    }
    case 'reap': {
      const report = reap(root);
      if (json) {
        process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
        return 0;
      }
      if (report.length === 0) {
        process.stdout.write('nothing to reap\n');
        return 0;
      }
      for (const entry of report) {
        process.stdout.write(`${entry.outcome} slot ${entry.slot} pid ${entry.holderPid}`
          + `${entry.expiredForMs === null ? '' : ` expired ${Math.round(entry.expiredForMs / 1000)}s ago`}\n`);
      }
      return 0;
    }
    default: {
      process.stderr.write(`unknown command ${JSON.stringify(command)}\n${usage()}\n`);
      return 1;
    }
  }
}

main().then((code) => process.exit(code)).catch((error) => {
  process.stderr.write(`gov failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
