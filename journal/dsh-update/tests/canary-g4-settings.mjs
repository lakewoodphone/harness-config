#!/usr/bin/env node
/**
 * dsh-update / tests/canary-g4-settings.mjs — OPT-IN. Proves gate G4's detector can FIRE.
 *
 *   node tests/canary-g4-settings.mjs [--version <ver>] [--prefix <installRoot>] [--no-control]
 *
 * This is NOT part of tests/run.mjs, because run.mjs must run with node alone, no engine and no
 * network. This script runs a real engine against a throwaway isolated home in the OS temp directory
 * (never the live DSH_HOME, never a port):
 *
 *   control : the deployment's own settings document       -> the engine must boot cleanly, no diagnostics
 *   canary  : the same document with a DUPLICATE_KEY added -> the engine must refuse, and the
 *             diagnostic scan must return at least one hit
 *
 * The control step performs one real model turn (it is the same boot the gates use), so it costs a
 * few seconds and a few tokens; --no-control skips it and runs only the canary, which fails before
 * any model call.
 *
 * Why this exists: a detector that has never fired is not a detector. Measured here on 2026-09-23
 * against 0.1.5-rc.1 — an unknown key, an unknown section, a wrong value type, an out-of-range number
 * and an invalid enum value all boot with exit 0 and print NOTHING; only a document the loader
 * cannot parse is rejected. That limitation is recorded in lib/verify.mjs and in verify.json notes.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import process from 'node:process';
import { copyTree, measure, resolveEngine, scanSettingsDiagnostics } from '../lib/verify.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (name, dflt) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : dflt; };
const VERSION = arg('--version', '0.1.5-rc.1');
const NO_CONTROL = argv.includes('--no-control');
const LIVE_HOME = process.env.DSH_HOME && process.env.DSH_HOME.trim() !== ''
  ? process.env.DSH_HOME
  : path.join(process.env.USERPROFILE ?? os.homedir(), '.dsh');

const resolved = resolveEngine(VERSION, arg('--prefix'));
if (!resolved.enginePath) {
  console.error(`canary: no engine for ${VERSION} found (pass --prefix <installRoot>)`);
  process.exit(2);
}
console.log(`canary: engine ${resolved.enginePath}\ncanary: source ${resolved.source}\ncanary: live home (read-only) ${LIVE_HOME}`);

const DEST = path.join(os.tmpdir(), `dsh-update-g4-canary-${VERSION}`);
const HOME = path.join(DEST, 'home');
const CWD = path.join(DEST, 'cwd');
const SETTINGS = path.join(HOME, 'settings.yaml');
const stats = { files: 0, bytes: 0, links: 0, dirs: 0, copiedLinks: 0, replacedLinks: 0, linkTargetsLeftAsDirs: 0 };
fs.mkdirSync(CWD, { recursive: true });
for (const rel of ['settings.yaml', 'profiles', '.agent-presets', '.credentials.yaml']) {
  const src = path.join(LIVE_HOME, rel);
  if (fs.existsSync(src)) copyTree(src, path.join(HOME, rel), stats);
}
console.log(`canary: isolated home ${HOME}\ncanary: copy ${stats.files} files/${stats.bytes} bytes, ${stats.links} links (source: ${JSON.stringify(measure(path.join(LIVE_HOME, 'profiles')))})`);
const clean = fs.readFileSync(SETTINGS, 'utf8');
const duplicated = `${clean}agent-loop:\n  maxParallelToolCalls: 20\n`;

function boot(label) {
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [resolved.enginePath, '--profile', 'headless', 'Reply with the single word OK.'], {
    env: { ...process.env, DSH_HOME: HOME }, cwd: CWD, encoding: 'utf8', timeout: 240000, maxBuffer: 64 * 1024 * 1024,
  });
  const ms = Date.now() - t0;
  const hits = scanSettingsDiagnostics(`${r.stderr}\n${r.stdout}`);
  const log = path.join(DEST, `${label}.txt`);
  fs.writeFileSync(log, `exit ${r.status}\nSTDOUT\n${r.stdout}\nSTDERR\n${r.stderr}\n`);
  console.log(`\n-- ${label}: exit ${r.status} in ${ms} ms; stdout ${JSON.stringify((r.stdout ?? '').trim().slice(0, 40))}; stderr ${(r.stderr ?? '').length} bytes; diagnostic hits ${hits.length}`);
  for (const h of hits) console.log(`   [${h.pattern}] ${h.text.slice(0, 240)}`);
  console.log(`   verbatim output: ${log}`);
  return { exit: r.status, hits, ms };
}

let failures = 0;
if (!NO_CONTROL) {
  fs.writeFileSync(SETTINGS, clean);
  const control = boot('control-clean-settings');
  if (control.exit !== 0 || control.hits.length > 0) {
    console.log(`   CANARY FAILED: the untouched document should boot cleanly (exit 0, no hits)`);
    failures += 1;
  } else {
    console.log('   canary control ok: exit 0 and no diagnostics on the untouched document');
  }
}
fs.writeFileSync(SETTINGS, duplicated);
const canary = boot('canary-duplicate-key');
if (canary.exit === 0) {
  console.log('   CANARY FAILED: a document the loader cannot parse still booted (exit 0)');
  failures += 1;
} else if (canary.hits.length === 0) {
  console.log('   CANARY FAILED: the boot failed but the diagnostic scan found no pattern match — G4 would report a failure for the wrong reason, and B6 would report none');
  failures += 1;
} else {
  console.log(`   canary ok: the malformed document was refused (exit ${canary.exit}) and ${canary.hits.length} diagnostic pattern(s) matched — G4 can fire`);
}
fs.writeFileSync(SETTINGS, clean);
console.log(`\ncanary: settings.yaml restored byte-identical: ${fs.readFileSync(SETTINGS, 'utf8') === clean}`);
console.log(`canary: ${failures === 0 ? 'PASS (exit 0)' : `FAIL (${failures} expectation(s) unmet)`}`);
process.exitCode = failures === 0 ? 0 : 1;
