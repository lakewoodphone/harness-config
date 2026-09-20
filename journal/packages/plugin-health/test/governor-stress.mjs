#!/usr/bin/env node
/**
 * Cross-process proof for the admission governor.
 *
 * WHAT THIS PROVES, AND WHY IT NEEDS REAL PROCESSES
 * The governor's whole claim is that two OS processes cannot both take slot 7 —
 * that the create-with-`wx` is the mutual exclusion and the rename-guarded reap
 * cannot steal a renewed lease. An in-process test cannot show that: shared
 * module state would hide exactly the race being tested. So this spawns real
 * `node bin/governor.mjs` children, concurrently, against a scratch lease
 * directory, and asserts on the files they left behind.
 *
 *   node test/governor-stress.mjs [--contenders 30] [--slots 5]
 *
 * Checks:
 *   1. exactly `slots` contenders are GRANTED and the rest are QUEUED (exit 10);
 *   2. no slot number appears twice in the granted set;
 *   3. exactly `slots` lease files exist, one per slot, all parseable;
 *   4. a killed holder's lease is reaped once its TTL passes, and exactly one of
 *      two concurrent reapers wins the rename (the other reports `vanished`);
 *   5. the slot is reusable afterwards.
 *
 * Exit 0 = all checks passed. Exit 1 = a check failed, with the failure named.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI = path.join(HERE, '..', 'bin', 'governor.mjs');

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const index = args.indexOf(`--${name}`);
  return index === -1 ? fallback : Number(args[index + 1]);
};
const CONTENDERS = flag('contenders', 30);
const SLOTS = flag('slots', 5);

let failures = 0;
const check = (label, condition, detail = '') => {
  if (condition) {
    process.stdout.write(`  ok   ${label}\n`);
  } else {
    failures += 1;
    process.stdout.write(`  FAIL ${label}${detail === '' ? '' : ` — ${detail}`}\n`);
  }
};

/** Run the CLI and resolve with its exit code and stdout. */
function run(argv) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [CLI, ...argv], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('exit', (code) => resolve({ code, stdout, stderr }));
  });
}

const root = mkdtempSync(path.join(tmpdir(), 'gov-stress-'));
process.stdout.write(`governor stress: ${CONTENDERS} contenders, budget ${SLOTS}, leases in ${root}\n`);

try {
  // ── 1..3: concurrent acquisition ─────────────────────────────────────────
  // A short TTL (2.5 s) so the expiry/reap half of this test runs in seconds
  // rather than minutes. TTL is a documented part of the protocol, not a
  // test-only hook.
  const started = Date.now();
  const outcomes = await Promise.all(
    Array.from({ length: CONTENDERS }, (_, index) => run(['acquire', '--root', root, '--max-slots', String(SLOTS), '--min-slots', '1', '--ttl-ms', '2500', '--kind', `contender-${index}`])),
  );
  const elapsed = Date.now() - started;
  const granted = outcomes.filter((outcome) => outcome.code === 0);
  const queued = outcomes.filter((outcome) => outcome.code === 10);
  const other = outcomes.filter((outcome) => outcome.code !== 0 && outcome.code !== 10);

  process.stdout.write(`\n${CONTENDERS} concurrent acquires finished in ${elapsed} ms\n`);
  check('every contender either GRANTED or QUEUED, none errored', other.length === 0, other.map((outcome) => `${outcome.code}:${outcome.stderr.trim()}`).join(' | '));
  check(`exactly ${SLOTS} were granted`, granted.length === SLOTS, `got ${granted.length}`);
  check(`the rest (${CONTENDERS - SLOTS}) were queued`, queued.length === CONTENDERS - SLOTS, `got ${queued.length}`);
  check('a queued caller is told its position, not refused', queued.every((outcome) => /QUEUED position \d+/.test(outcome.stdout)));

  const slots = granted.map((outcome) => Number(/GRANTED slot (\d+)/.exec(outcome.stdout)?.[1]));
  check('every grant names a slot', slots.every((slot) => Number.isInteger(slot)));
  check('no slot was granted twice', new Set(slots).size === slots.length, `slots ${slots.join(',')}`);

  const files = readdirSync(path.join(root, 'leases')).filter((name) => name.endsWith('.lease'));
  check(`exactly ${SLOTS} lease files exist`, files.length === SLOTS, `got ${files.length}: ${files.join(',')}`);
  let parsed = 0;
  for (const name of files) {
    try {
      const document = JSON.parse(readFileSync(path.join(root, 'leases', name), 'utf8'));
      if (typeof document.id === 'string' && Number.isInteger(document.slot) && Number.isInteger(document.pid)) parsed += 1;
    } catch {
      // counted as unparsed
    }
  }
  check('every lease file is a complete document', parsed === files.length, `${parsed} of ${files.length}`);
  check('every holder is a distinct process id', new Set(files.map((name) => JSON.parse(readFileSync(path.join(root, 'leases', name), 'utf8')).pid)).size === files.length);

  // ── 4..5: expiry, double reap, reuse ─────────────────────────────────────
  process.stdout.write('\nreap race:\n');
  const statusBefore = await run(['status', '--root', root, '--json']);
  const view = JSON.parse(statusBefore.stdout);
  check('status agrees with the lease files', view.inUse === SLOTS, `status says ${view.inUse}, files say ${files.length}`);
  check('status publishes the arithmetic behind the budget', typeof view.derivation === 'string' && view.derivation.includes('per slot'), view.derivation);

  // The holders were granted a 2.5 s TTL and their processes have exited, so
  // they are exactly the case the reaper exists for: gone, but not released.
  await new Promise((resolve) => setTimeout(resolve, 3500));
  const [firstReap, secondReap] = await Promise.all([
    run(['reap', '--root', root, '--json']),
    run(['reap', '--root', root, '--json']),
  ]);
  const reports = [firstReap, secondReap].map((outcome) => {
    try {
      return JSON.parse(outcome.stdout);
    } catch {
      return [];
    }
  });
  const reapedCounts = reports.map((report) => report.filter((entry) => entry.outcome === 'reaped').length);
  check('both reapers ran cleanly', firstReap.code === 0 && secondReap.code === 0);
  check('the same lease was reaped by exactly one reaper', reapedCounts[0] + reapedCounts[1] === SLOTS, `reaped counts ${reapedCounts.join(' + ')} for ${SLOTS} expired leases`);
  const after = await run(['status', '--root', root, '--json']);
  const afterView = JSON.parse(after.stdout);
  check('the slots are free again after the reap', afterView.inUse === 0, `inUse=${afterView.inUse}`);
  const reuse = await run(['acquire', '--root', root, '--max-slots', String(SLOTS), '--min-slots', '1', '--kind', 'reuse']);
  check('a freed slot is reusable', reuse.code === 0, reuse.stdout.trim());
} finally {
  rmSync(root, { recursive: true, force: true });
}

process.stdout.write(failures === 0 ? '\nall governor stress checks passed\n' : `\n${failures} check(s) FAILED\n`);
process.exit(failures === 0 ? 0 : 1);
