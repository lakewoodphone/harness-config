#!/usr/bin/env node
/**
 * ps-mesh.mjs — reach the rest of the company's machines from a manager workstation.
 *
 * WHY THIS EXISTS (owner's instruction, 2026-09-15): "her computers should be able to access the mesh
 * and get info and .env keys from the office desktop and the yoga laptop fully, i can't have it
 * crippled in any way."
 *
 * The access ALREADY WORKED and nothing used it. Measured from the office Mac before writing this:
 * `ssh desktop-ts hostname` answers, `ssh secratary-ts` answers, `ssh laptop-ts` answers, and the
 * authority's `.env` is readable key-by-key. Claude's raw ssh is fine for a person who knows the host
 * names; a tool is what makes it usable by her agent without it having to remember that desktop-ts is
 * the office desktop and secratary-ts is the company server.
 *
 * WHAT IT IS: a thin, read-mostly wrapper over `ssh` to the named machines. It knows the fleet, it
 * reports reachability honestly, and it never invents a hostname.
 *
 * SAFETY, WHICH IS THE OWNER'S ACTUAL RULE FOR HER
 * "she gets full full access, just since she's not a developer, her agent should realize this and not
 * do anything very dangerous unless she realizes what shes doing and clearly authorizes."
 * So: reads and normal commands run freely, and the handful of commands that can destroy data are
 * REFUSED unless the manager explicitly confirms for that exact command. That is a guard rail, not a
 * restriction on her authority -- she can always say yes.
 *
 * Usage:
 *   node ps-mesh.mjs hosts                         # what is in the fleet, and what answers
 *   node ps-mesh.mjs run <host> "command"          # run a command on a host
 *   node ps-mesh.mjs file <host> <path>            # read a file (cat)
 *   node ps-mesh.mjs env <host> [path]             # list VARIABLE NAMES in a .env (never values)
 *   node ps-mesh.mjs env <host> <path> --key NAME  # print ONE value, when she needs it
 *
 * Hosts are the fleet's own ssh aliases: desktop-ts, secratary-ts, laptop-ts, linux-pc-ts.
 */
import os from 'node:os';
import { spawnSync } from 'node:child_process';

const ARGS = process.argv.slice(2);
const VERB = (ARGS[0] || 'hosts').toLowerCase();
const MACHINE = os.hostname();

/**
 * The fleet, by the ssh aliases that actually exist in every machine's ~/.ssh/config.
 * `where` is plain English, because her agent should not have to know that `zabz-tech` is the desktop.
 */
const FLEET = [
  { alias: 'desktop-ts', where: "the owner's office desktop (ZABZ-TECH), i9/64GB", user: 'ezabz' },
  { alias: 'secratary-ts', where: 'the company server (secratary) — the authoritative database and the autonomous company', user: 'zabz' },
  { alias: 'laptop-ts', where: "the owner's Yoga laptop (ZABZ-YOGA), where he works at night", user: 'ezabz' },
  { alias: 'linux-pc-ts', where: 'the Linux PC (zabz-tech-linux)', user: 'zabz' },
];

/**
 * Commands that can destroy data or take a system down, which the manager must explicitly confirm.
 * This list is the company's own hard-won one: this business has lost customer data twice, once to a
 * `pm clear` on a customer phone and once to a `pm clear com.whatsapp` that took ~90 GB of WhatsApp
 * media with it. Both are on the list.
 */
const DANGEROUS = [
  { re: /\bpm\s+clear\b/, what: 'pm clear on a device — DELETES app data AND media, not just cache' },
  { re: /\bpm\s+(uninstall|disable-user)\b/, what: 'uninstalling/disabling a package' },
  { re: /\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+/, what: 'recursive/forced delete' },
  { re: /\bgit\s+reset\s+--hard\b/, what: 'git reset --hard — discards uncommitted work' },
  { re: /\bgit\s+push\b[^\n]*--force\b|\bgit\s+push\s+-f\b/, what: 'force push — rewrites published history' },
  { re: /\b(drop\s+table|delete\s+from|truncate\s+table)\b/i, what: 'destructive SQL' },
  { re: /\b(fastboot\s+erase|factory\s*reset|wipe_data|format\s+userdata)\b/i, what: 'device wipe / factory reset' },
  { re: /\b(shutdown|reboot|halt|poweroff)\b/, what: 'taking a machine down' },
  { re: /\bdd\s+if=|>\s*\/dev\/(sd|nvme|disk)/, what: 'raw disk write' },
];

function checkDanger(cmd) {
  for (const d of DANGEROUS) if (d.re.test(cmd)) return d;
  return null;
}

function run(alias, command, timeoutMs = 120000) {
  const r = spawnSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'LogLevel=ERROR', alias, command], {
    encoding: 'utf8', timeout: timeoutMs,
  });
  return { ok: r.status === 0, out: (r.stdout || '').trim(), err: (r.stderr || '').trim(), code: r.status };
}

function main() {
  if (VERB === 'hosts' || VERB === 'host') {
    console.log(`  fleet, as seen from ${MACHINE}:`);
    for (const h of FLEET) {
      const r = run(h.alias, 'hostname', 15000);
      const state = r.ok ? `reachable (${r.out.split('\n')[0]})` : `UNREACHABLE${r.err ? ' — ' + r.err.split('\n')[0].slice(0, 60) : ''}`;
      console.log(`    ${h.alias.padEnd(14)} ${state}`);
      console.log(`      ${h.where}`);
    }
    console.log('\n  run one:  ps-mesh run desktop-ts "hostname"');
    return;
  }

  const host = ARGS[1];
  if (!host) { console.error(`ps-mesh ${VERB}: needs a host. Try: ps-mesh hosts`); process.exit(2); }
  const known = FLEET.find((f) => f.alias === host);
  if (!known) {
    console.error(`ps-mesh: "${host}" is not in the fleet. Known: ${FLEET.map((f) => f.alias).join(', ')}`);
    process.exit(2);
  }

  if (VERB === 'run') {
    const cmd = ARGS[2];
    if (!cmd) { console.error('ps-mesh run: needs a command in quotes'); process.exit(2); }
    const danger = checkDanger(cmd);
    if (danger && !ARGS.includes('--i-authorize-this')) {
      console.error(`ps-mesh: REFUSED — this looks destructive: ${danger.what}`);
      console.error(`  command: ${cmd}`);
      console.error('  If Yocheved has said to do exactly this, in this conversation, re-run with:');
      console.error('    --i-authorize-this');
      process.exit(3);
    }
    const r = run(host, cmd, 180000);
    if (r.out) console.log(r.out);
    if (r.err) console.error(r.err);
    process.exit(r.ok ? 0 : 1);
  }

  if (VERB === 'file') {
    const p = ARGS[2];
    if (!p) { console.error('ps-mesh file: needs a path'); process.exit(2); }
    const r = run(host, `cat "${p}"`, 60000);
    if (r.out) console.log(r.out);
    if (r.err) console.error(r.err);
    process.exit(r.ok ? 0 : 1);
  }

  if (VERB === 'env') {
    // A .env is the machine's secrets. Listing the NAMES is safe and answers "what is configured
    // here"; printing a VALUE is a deliberate act, so it needs --key and says what it is doing.
    const p = ARGS[2] && !ARGS[2].startsWith('--') ? ARGS[2] : null;
    if (!p) { console.error('ps-mesh env: needs the .env path, e.g. /home/zabz/personal-secretary-mvp/.env'); process.exit(2); }
    const keyIdx = ARGS.indexOf('--key');
    if (keyIdx !== -1) {
      const key = ARGS[keyIdx + 1];
      if (!key) { console.error('ps-mesh env: --key needs a name'); process.exit(2); }
      // Only the requested name, and only its own line: never the whole file.
      const r = run(host, `grep -m1 '^${key}=' "${p}"`, 30000);
      if (!r.ok || !r.out) { console.error(`ps-mesh: ${key} is not set in ${p} on ${host}`); process.exit(1); }
      console.log(r.out);
      return;
    }
    const r = run(host, `grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "${p}" | tr -d '=' | sort`, 30000);
    if (!r.ok) { console.error(r.err || `could not read ${p}`); process.exit(1); }
    const names = r.out.split('\n').filter(Boolean);
    console.log(`  ${names.length} variable(s) configured in ${p} on ${host} (names only):`);
    for (const n of names) console.log(`    ${n}`);
    console.log('\n  one value:  ps-mesh env ' + host + ' ' + p + ' --key NAME');
    return;
  }

  console.error('ps-mesh: commands -> hosts | run <host> "cmd" | file <host> <path> | env <host> <path> [--key NAME]');
  process.exit(2);
}

main();
