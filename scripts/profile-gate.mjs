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
 * Find a harness that ACTUALLY RUNS. Deliberately a search, not a constant: install locations
 * differ per machine (npm prefix, npx cache, a portable tree, `/home/<user>/dsh-engine`, a POSIX
 * system prefix), and a hardcoded path is how a gate silently checks nothing.
 *
 * EXISTENCE IS NOT ENOUGH, AND THAT COST A FALSE ALARM. Measured on secratary 2026-09-28: the
 * first existing candidate was `~/.dsh/profiles/node_modules/@deepseek-ai/dsh/lib/bin.js` — a
 * vestigial 9 KB copy — run with `/usr/bin/node` v20. That pair exits **0 with no output for
 * every argument, including -V** (L173's entry-point-no-op), so a gate that trusted "the file
 * exists" declared a healthy machine CANNOT-BOOT. The install that machine really uses is
 * `/home/zabz/dsh-engine/node_modules/...` run with `/home/zabz/node/bin/node` (v24).
 *
 * So candidates are PROBED as (node, bin) PAIRS and the first pair that produces output wins.
 * A node that no-ops is as much a wrong answer as a missing file. Every pair tried is reported.
 */
function nodeCandidates() {
  const list = [];
  if (process.env.DSH_NODE) list.push(process.env.DSH_NODE);
  list.push(process.execPath);
  if (process.platform === 'win32') {
    list.push('C:\\Program Files\\nodejs\\node.exe');
    list.push(path.join(os.homedir(), 'node', 'node.exe'));
  } else {
    list.push(path.join(os.homedir(), 'node', 'bin', 'node'));
    list.push('/usr/local/bin/node');
    list.push('/usr/bin/node');
  }
  return [...new Set(list)].filter((p) => { try { return existsSync(p); } catch { return false; } });
}

function binCandidates(explicit) {
  const out = [];
  const add = (p) => { if (p && !out.includes(p)) out.push(p); };
  if (explicit) add(explicit);
  if (process.env.DSH_BIN) add(process.env.DSH_BIN);

  const win = process.platform === 'win32';
  const sep = win ? path.sep : '/';
  const suffix = ['node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js'].join(sep);

  add(path.join(home(), 'dsh-engine', suffix));       // secratary's layout
  add(path.join(home(), 'profiles', suffix));         // profile-local install
  add(path.join(home(), 'dsh', suffix));              // her laptop's portable install
  add(path.join(path.dirname(path.dirname(process.execPath)), 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js'));
  if (win) {
    add(path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx', '1e7f6d9597241db0', suffix));
    add(`C:\\Users\\cheve\\dsh\\${suffix}`);
    add(`C:\\Users\\ezabz\\dsh\\${suffix}`);
    const npxRoot = path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx');
    if (existsSync(npxRoot)) for (const d of readdirSync(npxRoot)) add(path.join(npxRoot, d, suffix));
  } else {
    add('/usr/lib/node_modules/@deepseek-ai/dsh/lib/bin.js');
    add('/usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js');
  }
  return out.filter((p) => { try { return existsSync(p); } catch { return false; } });
}

/** Does this pair answer at all? -V is the cheapest question that a no-op cannot fake. */
function pairAnswers(node, bin) {
  try {
    const out = execFileSync(node, [bin, '-V'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 30000 });
    return out.trim().length > 0;
  } catch { return false; }
}

/**
 * The proven pair, or an explicit refusal.
 *
 * A machine where NOTHING answers is reported as `no-working-harness` — a refusal — and never as
 * a bad profile, because "I could not exercise the harness" and "the harness is broken" are
 * different facts and only one of them is a defect on that machine.
 */
function resolveHarness(explicit) {
  const bins = binCandidates(explicit);
  const nodes = nodeCandidates();
  const tried = [];
  for (const bin of bins) {
    for (const node of nodes) {
      const ok = pairAnswers(node, bin);
      tried.push({ node, bin, answers: ok });
      if (ok) return { bin, node, tried };
    }
  }
  return { bin: undefined, node: undefined, tried };
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
const { bin, node, tried } = resolveHarness(args.vals['dsh-bin']);

if (bin === undefined) {
  const out = {
    host: os.hostname(),
    home: home(),
    verdict: 'no-working-harness',
    tried,
    note: 'no (node, dsh) pair on this machine produced any output — including for -V — so the gate checked'
      + ' NOTHING. This is a REFUSAL and it is NOT the same as a bad profile: an unexercisable harness'
      + ' is not a broken machine. Fix the resolution (see `tried`) or pass --dsh-bin.',
  };
  if (args.flags.includes('json')) console.log(JSON.stringify(out, null, 2));
  else {
    console.error(`FAIL ${os.hostname()}: no working harness, so NOTHING was checked (this is a refusal, not a verdict)`);
    for (const t of tried) console.error(`     tried node=${t.node} bin=${t.bin} answers=${t.answers}`);
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
    const out = execFileSync(node, [bin, '--profile', name, '--dump-config'], {
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
  // Provenance: WHICH node and WHICH install produced this verdict. Without these two fields a
  // "CANNOT-BOOT" cannot be told apart from a gate that resolved the wrong copy — which is
  // exactly the false alarm secratary produced on 2026-09-28.
  node,
  dshBin: bin,
  nodeVersion: (() => { try { return execFileSync(node, ['--version'], { encoding: 'utf8' }).trim(); } catch { return 'unknown'; } })(),
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
  console.log(`     via node ${payload.nodeVersion} (${node})`);
  console.log(`     and ${bin}`);
  for (const r of results) {
    console.log(`     ${r.ok ? 'ok  ' : 'FAIL'} ${r.profile.padEnd(12)} ${r.ok ? `${r.lines} lines in ${r.ms}ms` : r.failure}`);
  }
  if (failed.length > 0) {
    console.log('     -- this engine CANNOT START. A running old engine proves nothing: the profile is read at boot.');
  }
}
process.exitCode = failed.length === 0 ? 0 : 1;
