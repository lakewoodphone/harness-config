#!/usr/bin/env node
/**
 * profile-gate — prove this machine's engine CAN BOOT, without starting it.
 *
 * THE FAILURE THIS EXISTS FOR
 *
 * On 2026-09-17 the profile bundle `dsh-mesh-broker` was found to stop an engine booting:
 * `dsh-app-boot/lib/index.js:852` throws for any name in a profile's `dsh.profile.bundles`
 * whose package declares no `dsh.bundle.patch`, and a bundle list is a LAYER list, so ONE bad
 * name stops the whole engine. That was repaired on ZABZ-YOGA and ZABZ-TECH (H441) and on
 * lakewooechsmini (H451).
 *
 * Yocheved's laptop was never on that list. Its engine then rebooted on 2026-09-18 18:05 and
 * could not come back — **for ten days**. Nothing said so: the logon-trigger task fired four
 * minutes after boot and returned 0 while the engine died in under a second (L2609).
 *
 * WHY THIS CHECK AND NOT ANOTHER
 *
 * `dsh --profile <name> --dump-config` composes every layer, starts no server, evaluates no
 * `!!js`, and exits non-zero with the throwing line named. It is the cheapest real gate for a
 * profile, and — crucially for a machine whose engine is dead — IT DOES NOT NEED THE ENGINE.
 * It is a one-shot node process.
 *
 * A running engine proves nothing: an engine reads its profile at START, so a machine you have
 * not restarted since a profile change is UNVERIFIED, not healthy.
 *
 * Everything is assessed by ABSENCE OF THE DEFECT: every profile that exists under DSH_HOME is
 * composed, and any non-zero exit fails the run. Do not replace this with a list of the machines
 * (or the profiles) someone remembered to check — that list is exactly what missed her laptop.
 *
 * Exit codes: 0 all profiles compose · 1 at least one does not · 3 the harness could not be found.
 *
 * USAGE
 *   node scripts/profile-gate.mjs                 # every profile under DSH_HOME/profiles
 *   node scripts/profile-gate.mjs --profile web   # just one
 *   node scripts/profile-gate.mjs --json
 *   node scripts/profile-gate.mjs --dsh-bin <path/to/dsh/lib/bin.js>
 *   node scripts/profile-gate.mjs --json --profile web --dsh-bin ... | jq .
 */

import { existsSync, readdirSync, statSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';

function home() { return process.env.DSH_HOME || path.join(os.homedir(), '.dsh'); }

function parseArgs(argv) {
  const out = { flags: [], vals: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const n = argv[i + 1];
      if (n === undefined || n.startsWith('--')) out.flags.push(k);
      else { out.vals[k] = n; i++; }
    }
  }
  return out;
}

/**
 * Find the harness entry point. Deliberately a search, not a constant: this runs on machines
 * whose install location differs (npm prefix, npx cache, a portable tree, a POSIX home), and a
 * hardcoded path is how a gate silently checks nothing. Every candidate that was tried is
 * reported so a "not found" is diagnosable rather than mysterious.
 */
function findDshBin(explicit) {
  const tried = [];
  const add = (p) => { if (p) tried.push(p); return p; };
  const candidates = [];
  if (explicit) candidates.push(add(explicit));
  if (process.env.DSH_BIN) candidates.push(add(process.env.DSH_BIN));

  const win = process.platform === 'win32';
  const sep = win ? '\\' : '/';
  const suffix = `node_modules${sep}@deepseek-ai${sep}dsh${sep}lib${sep}bin.js`;

  // 1. the profile-local install (this is where a per-machine install puts it)
  candidates.push(add(path.join(home(), 'profiles', suffix)));
  // 2. a sibling of the running node (npm prefix layout)
  candidates.push(add(path.join(path.dirname(path.dirname(process.execPath)), 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js')));
  // 3. the owner's npx cache and the portable tree her box used
  if (win) {
    candidates.push(add(path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx', '1e7f6d9597241db0', suffix.replace(/\\/g, path.sep))));
    candidates.push(add(`C:\\Users\\cheve\\dsh\\${suffix}`));
    candidates.push(add(`C:\\Users\\ezabz\\dsh\\${suffix}`));
    const npxRoot = path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx');
    if (existsSync(npxRoot)) {
      for (const d of readdirSync(npxRoot)) candidates.push(add(path.join(npxRoot, d, suffix)));
    }
  } else {
    candidates.push(add('/usr/lib/node_modules/@deepseek-ai/dsh/lib/bin.js'));
    candidates.push(add('/usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js'));
  }
  for (const c of candidates) {
    try { if (c && existsSync(c)) return { bin: c, tried }; } catch { /* keep looking */ }
  }
  return { bin: undefined, tried: tried.filter(Boolean) };
}

/** Profiles are directories under DSH_HOME/profiles, excluding the module tree. */
function listProfiles(only) {
  const root = path.join(home(), 'profiles');
  if (only) return [only];
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true })
    .filter((d) => d.isDirectory() && d.name !== 'node_modules')
    .map((d) => d.name)
    .sort();
}

/**
 * Pull the DIAGNOSIS out of a failed dump, not a line of source code.
 *
 * Node prints a code frame for a throw — the source line, a caret, and only then the message —
 * and `dsh-app-boot`'s throw happens to contain the string "declares no dsh.bundle" inside its
 * own template literal. A naive "first line mentioning the defect" therefore reports
 * `if (declared === void 0) throw new Error(...)` instead of the sentence an operator needs.
 * Measured on this exact defect, 2026-09-28. So: real message first, code frame only as a
 * last resort, and never a line that is obviously the throwing statement itself.
 */
function extractFailure(text, status) {
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
  const message = lines.find((l) => /^Error:\s/.test(l) || /^(TypeError|ReferenceError|SyntaxError|YAMLParseError):\s/.test(l));
  if (message !== undefined) return message;
  const named = lines.find((l) => /: profile bundle .* declares no dsh\.bundle/.test(l));
  if (named !== undefined) return named.endsWith('`') ? named : named;
  const useful = lines.find((l) => !/^(if \(|throw |\^|\}|\{)/.test(l) && /Cannot find|DUPLICATE_KEY|not found|declares no dsh\.bundle/.test(l));
  if (useful !== undefined) return useful;
  return lines[0] ?? `exit ${status ?? '?'}`;
}

const args = parseArgs(process.argv.slice(2));
const started = Date.now();
const { bin, tried } = findDshBin(args.vals['dsh-bin']);

if (bin === undefined) {
  const out = {
    host: os.hostname(),
    home: home(),
    verdict: 'harness-not-found',
    tried,
    note: 'the gate could not locate @deepseek-ai/dsh/lib/bin.js, so it checked NOTHING - this is a refusal, not a pass',
  };
  if (args.flags.includes('json')) console.log(JSON.stringify(out, null, 2));
  else {
    console.error(`FAIL ${os.hostname()}: harness not found, so NOTHING was checked`);
    for (const t of tried) console.error(`     tried ${t}`);
  }
  process.exit(3);
}

const profiles = listProfiles(args.vals.profile);
const results = [];
for (const name of profiles) {
  const dir = path.join(home(), 'profiles', name);
  if (!existsSync(path.join(dir, 'package.json'))) {
    results.push({ profile: name, ok: false, reason: 'no package.json (profile is not initialised)' });
    continue;
  }
  const t0 = Date.now();
  let ok = false, lines = 0, failure;
  try {
    const out = execFileSync(process.execPath, [bin, '--profile', name, '--dump-config'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 120000,
    });
    lines = out.split('\n').filter((l) => l.trim().length > 0).length;
    ok = lines > 0;   // exit 0 with NO output is the entry point no-opping (L173), not a pass
    if (!ok) failure = 'exit 0 but produced no output — the entry point no-opped (L173)';
  } catch (error) {
    const text = `${error.stdout ?? ''}${error.stderr ?? ''}`;
    failure = extractFailure(text, error.status);
  }
  results.push({ profile: name, ok, lines, ms: Date.now() - t0, failure });
}

const failed = results.filter((r) => !r.ok);
const payload = {
  host: os.hostname(),
  home: home(),
  dshBin: bin,
  profiles: results,
  verdict: failed.length === 0 ? 'ok' : 'CANNOT-BOOT',
  checkedMs: Date.now() - started,
  note: failed.length === 0
    ? `all ${results.length} profile(s) compose; a running engine is not required and was not used`
    : `${failed.length} of ${results.length} profile(s) fail to compose — this engine cannot start`,
};

if (args.flags.includes('json')) {
  console.log(JSON.stringify(payload, null, 2));
} else {
  console.log(`${failed.length === 0 ? 'OK  ' : 'FAIL'} ${payload.host}  profiles=${results.length}  ${payload.checkedMs}ms`);
  for (const r of results) {
    console.log(`     ${r.ok ? 'ok  ' : 'FAIL'} ${r.profile.padEnd(12)} ${r.ok ? `${r.lines} lines in ${r.ms}ms` : r.failure}`);
  }
  if (failed.length > 0) {
    console.log('     -- this engine CANNOT START. A running old engine proves nothing: the profile is read at boot.');
  }
}
process.exitCode = failed.length === 0 ? 0 : 1;
