// check-config-names.mjs — does every package name a config file DECLARES actually resolve?
//
// WHY THIS EXISTS (2026-09-30, the owner's ZABZ-YOGA outage). The live profile patch named a
// package the running engine no longer shipped. Nothing checked that. The engine booted, the web
// UI served, and only when a session was created did the preset registry throw
// `agent-preset/invalid: <row> ... never started` -- a message that names the row and hides the
// cause, because a row whose module fails to import is reported by the absence of a fiber.
// The fix took hours; this check answers it in a second.
//
// USAGE
//   node scripts/check-config-names.mjs --home <DSH_HOME> [--engine <install dir>]
//   exit 0 = every declared name resolves; exit 1 = at least one does not (each is printed).
//
// It checks, in the same resolution context the engine uses:
//   $DSH_HOME/profiles/<name>/cordis.patch.yml   every @deepseek-ai/* name
//   $DSH_HOME/.agent-presets/<id>/agent.cordis.yml   every row module name
// Subpaths (e.g. @deepseek-ai/dsh-tool-subagent-control/list-agents) are resolved as a MODULE,
// not by testing for a directory -- a directory test reports a subpath as missing when it is
// perfectly valid, which is exactly the false positive this script was written to retire.

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const argv = process.argv.slice(2);
const getArg = (flag, fallback) => {
  const i = argv.indexOf(flag);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const home = getArg('--home', process.env.DSH_HOME || join(process.env.USERPROFILE || '', '.dsh'));
const engine = getArg('--engine', join(home, 'engine'));

if (!existsSync(engine)) {
  console.error(`check-config-names: engine install not found: ${engine}`);
  process.exit(1);
}
const require_ = createRequire(join(engine, 'package.json'));

function resolveName(name) {
  try {
    require_.resolve(name + '/package.json');
    return null;
  } catch { }
  try {
    require_.resolve(name);
    return null;
  } catch (e) {
    return e.code || e.message;
  }
}

function namesIn(text) {
  const out = new Set();
  for (const m of text.matchAll(/name:\s*['"]?([^'"\s]+)['"]?/g)) {
    const n = m[1];
    if (n.startsWith('@deepseek-ai/')) out.add(n);
  }
  return [...out];
}

let failures = 0;
const scanned = [];

const profilesDir = join(home, 'profiles');
if (existsSync(profilesDir)) {
  for (const p of readdirSync(profilesDir, { withFileTypes: true })) {
    if (!p.isDirectory()) continue;
    const f = join(profilesDir, p.name, 'cordis.patch.yml');
    if (!existsSync(f)) continue;
    const names = namesIn(readFileSync(f, 'utf8'));
    const bad = names.map(n => [n, resolveName(n)]).filter(([, e]) => e);
    scanned.push(`profile ${p.name}: ${names.length} declared`);
    for (const [n, e] of bad) { console.log(`  MISSING  profile ${p.name}  ${n}  (${e})`); failures++; }
  }
}

const presetsDir = join(home, '.agent-presets');
if (existsSync(presetsDir)) {
  for (const p of readdirSync(presetsDir, { withFileTypes: true })) {
    if (!p.isDirectory()) continue;
    const f = join(presetsDir, p.name, 'agent.cordis.yml');
    if (!existsSync(f)) continue;
    const names = namesIn(readFileSync(f, 'utf8'));
    const bad = names.map(n => [n, resolveName(n)]).filter(([, e]) => e);
    scanned.push(`preset ${p.name}: ${names.length} row modules`);
    for (const [n, e] of bad) { console.log(`  MISSING  preset ${p.name}  ${n}  (${e})`); failures++; }
  }
}

console.log(`check-config-names: ${scanned.join('; ')}`);
console.log(failures === 0
  ? `check-config-names: OK — every declared package name resolves against ${engine}`
  : `check-config-names: ${failures} declared name(s) DO NOT RESOLVE against ${engine}`);
process.exit(failures === 0 ? 0 : 1);
