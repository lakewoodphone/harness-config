/**
 * Run every check for this plugin and report one verdict.
 *
 * Each check answers a different question, and a passing build does not imply any
 * of the others:
 *   build      — the generated files match the sources they are generated from
 *   cost       — the rates, the tier arithmetic, and the fold against real logs
 *   client     — the browser half registers and renders under the module loader
 *   profile    — the profile loader can resolve the package by name and use its manifest
 *
 * Usage: node test/verify.mjs
 */
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

const checks = [
  ['build', ['scripts/build.mjs', '--check'], 'the generated files are current'],
  ['cost', ['test/cost.test.mjs'], 'rates, tier arithmetic, and the fold on real logs'],
  ['client', ['test/client-smoke.mjs'], 'the browser half registers and renders'],
  ['profile', ['test/profile-resolution.manual.mjs'], 'the profile loader can resolve the package'],
];

const results = [];
for (const [name, args, purpose] of checks) {
  const run = spawnSync(process.execPath, args, { cwd: ROOT, encoding: 'utf8' });
  const ok = run.status === 0;
  results.push({ name, ok, purpose, stdout: run.stdout ?? '', stderr: run.stderr ?? '' });
}

console.log('');
console.log('verification summary');
for (const result of results) {
  console.log(`  ${result.ok ? 'PASS' : 'FAIL'}  ${result.name.padEnd(8)} ${result.purpose}`);
}

const failed = results.filter((result) => !result.ok);
if (failed.length > 0) {
  console.log('');
  for (const result of failed) {
    console.log(`--- ${result.name} output ---`);
    console.log((result.stdout + result.stderr).trim().split('\n').slice(-25).join('\n'));
  }
}

console.log('');
console.log(failed.length === 0 ? 'ALL CHECKS PASSED' : `${failed.length} of ${results.length} checks FAILED`);
process.exit(failed.length === 0 ? 0 : 1);
