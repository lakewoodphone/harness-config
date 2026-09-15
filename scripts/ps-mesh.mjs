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
import fs from 'node:fs';
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
  { alias: 'desktop-ts', where: "the owner's office desktop (ZABZ-TECH), i9/64GB", user: 'ezabz', os: 'windows' },
  { alias: 'secratary-ts', where: 'the company server (secratary) — the authoritative database and the autonomous company', user: 'zabz', os: 'linux' },
  { alias: 'laptop-ts', where: "the owner's Yoga laptop (ZABZ-YOGA), where he works at night", user: 'ezabz', os: 'windows' },
  { alias: 'linux-pc-ts', where: 'the Linux PC (zabz-tech-linux)', user: 'zabz', os: 'linux' },
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

function run(alias, command, timeoutMs = 120000, { stdin } = {}) {
  const r = spawnSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'LogLevel=ERROR', alias, command], {
    encoding: 'utf8', timeout: timeoutMs, input: stdin,
  });
  return { ok: r.status === 0, out: (r.stdout || '').trim(), err: (r.stderr || '').trim(), code: r.status };
}

/**
 * Run a PowerShell script on a WINDOWS host.
 *
 * FOUR FAILED ATTEMPTS ARE RECORDED HERE because each one looked like a different problem, and all of
 * them were the same problem -- quoting through node -> ssh -> cmd.exe -> PowerShell:
 *   1. `grep` on a Windows host: no such command. Failed loudly, which was fine.
 *   2. PowerShell inline with escaped quotes: the escaping was eaten and it reported "0 variables"
 *      instead of erroring. The WORSE kind of wrong -- it reads as an answer.
 *   3. PowerShell inline, simplified: still eaten. `ssh host "..."` on Windows passes the string
 *      through cmd.exe before PowerShell sees it.
 *   4. Piping the script to `powershell -Command -` over stdin: verified by hand in PowerShell that
 *      the remote logic is correct (it returns 334 matching lines), but the same bytes sent from node
 *      produced nothing. Rather than keep bisecting a transport I do not control, the transport is
 *      removed.
 *
 * WHAT WORKS: `-EncodedCommand`, which takes BASE64 UTF-16LE. Base64 contains no quotes, no
 * backslashes and no metacharacters, so no layer between here and the remote PowerShell has anything
 * to mangle. This is worth the extra three lines: every previous attempt was correct logic defeated by
 * a quoting layer, which is not a bug anyone can reason about from the output.
 */
function psRemote(alias, script, timeoutMs = 60000) {
  const encoded = Buffer.from(script, 'utf16le').toString('base64');
  return run(alias, `powershell -NoProfile -EncodedCommand ${encoded}`, timeoutMs);
}

function readEnvNamesWindows(alias, p) {
  const script = [
    `$f = '${p}'`,
    'if (Test-Path $f) {',
    // Skip comment lines: a .env carries commented-out examples, and they are not "configured" --
    // reporting them made the list longer and less true.
    "  Get-Content $f | Where-Object { $_ -like '*=*' -and -not $_.TrimStart().StartsWith('#') } | ForEach-Object { ($_ -split '=')[0].Trim() } | Where-Object { $_ -ne '' } | Sort-Object -Unique",
    '} else { "NOSUCHFILE" }',
  ].join('\n');
  return psRemote(alias, script, 60000);
}

function readEnvValueWindows(alias, p, key) {
  const script = [
    `$f = '${p}'`,
    'if (Test-Path $f) {',
    `  Get-Content $f | Where-Object { $_ -like '${key}=*' } | Select-Object -First 1`,
    '} else { "NOSUCHFILE" }',
  ].join('\n');
  return psRemote(alias, script, 45000);
}

/**
 * Read a file from a remote host BYTE-FAITHFULLY, and write one back the same way.
 *
 * WHY THIS IS NOT JUST `cat` -- WHICH IS WHAT IT WAS. Found by her agent and filed as journal P166 and
 * L1568, from her Mac, with the damage named:
 *
 *   "ps-mesh file is the documented way to read a file from another machine, and on Windows hosts it
 *    silently mangles every non-ASCII character, so the natural workflow 'read a record over the mesh,
 *    edit it, write it back' quietly degrades customer records."
 *
 * The old implementation ran `cat "<path>"` over ssh. On a Windows host that goes through cmd.exe and
 * PowerShell and the bytes come back re-encoded, so content is altered with NO error raised. That is
 * the worst shape this tool could have: its whole purpose is moving customer records between machines,
 * and it corrupted them silently. Reading to look at something was fine; reading as the first half of
 * an edit was not, and nothing said so.
 *
 * THE FIX IS BASE64, not a cleverer `cat`. Base64 is pure ASCII, so no layer between the two machines
 * -- ssh, cmd.exe, PowerShell, or node's utf8 decoding -- has a character available to mangle. Encode
 * on the far side, decode here. `scp` would also be faithful but needs a second connection plus a temp
 * file at each end; base64 rides the connection already open.
 *
 * `write` exists so the whole workflow is correct rather than half of it: a faithful read with an
 * unfaithful write would still corrupt the record on the way back.
 */
/** Windows hosts need a different remote shell (no grep, no cat, cmd.exe in the path). */
function isWindowsHost(alias) {
  const f = FLEET.find((x) => x.alias === alias);
  return Boolean(f && f.os === 'windows');
}

function readFileB64(alias, p, timeoutMs = 120000) {
  const cmd = isWindowsHost(alias)
    ? 'powershell -NoProfile -EncodedCommand ' + Buffer.from(
        "if (Test-Path '" + p + "') { [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path '" + p + "').Path)) } else { 'NOSUCHFILE' }",
        'utf16le').toString('base64')
    : "if [ -f '" + p + "' ]; then base64 < '" + p + "' | tr -d '\\n'; else echo NOSUCHFILE; fi";
  return run(alias, cmd, timeoutMs);
}

function writeFileB64(alias, p, b64, timeoutMs = 120000) {
  if (isWindowsHost(alias)) {
    const script = [
      "$b64 = '" + b64 + "'",
      '$bytes = [Convert]::FromBase64String($b64)',
      "[IO.File]::WriteAllBytes('" + p + "', $bytes)",
      '$bytes.Length',
    ].join('\n');
    return psRemote(alias, script, timeoutMs);
  }
  const cmd = "printf '%s' '" + b64 + "' | base64 -d > '" + p + "' && wc -c < '" + p + "' | tr -d ' '";
  return run(alias, cmd, timeoutMs);
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
  // Windows hosts run `ssh host "cmd"` through cmd.exe/PowerShell: no grep, no cat, and \r\n output.
  // Chosen per host rather than assumed, which is what broke the office-desktop attempt first time.
  const windows = known.os === 'windows';

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

  if (VERB === 'file' || VERB === 'read') {
    const p = ARGS[2];
    if (!p) { console.error('ps-mesh file: needs a path'); process.exit(2); }
    const r = readFileB64(host, p, 120000);
    if (!r.ok) { console.error(r.err || `could not read ${p} on ${host}`); process.exit(1); }
    if (/NOSUCHFILE/.test(r.out) && r.out.trim() === 'NOSUCHFILE') { console.error(`ps-mesh: no file at ${p} on ${host}`); process.exit(1); }
    // Decode to BYTES, then emit bytes. Writing the decoded buffer to stdout rather than a string is
    // the whole point: a string would re-encode and we would be back where we started.
    const b64 = r.out.replace(/\s+/g, '');
    let buf;
    try { buf = Buffer.from(b64, 'base64'); }
    catch { console.error('ps-mesh: remote did not return valid base64'); process.exit(1); }
    const outIdx = ARGS.indexOf('--out');
    if (outIdx !== -1) {
      const local = ARGS[outIdx + 1];
      if (!local) { console.error('ps-mesh file: --out needs a local path'); process.exit(2); }
      fs.writeFileSync(local, buf);
      console.log(`  wrote ${local} (${buf.length} bytes, byte-faithful)`);
    } else {
      process.stdout.write(buf);
    }
    return;
  }

  if (VERB === 'write') {
    // The other half of a safe read-modify-write, and it did not exist before her agent reported the
    // read defect -- fixing only the read would leave the workflow half-correct.
    const p = ARGS[2];
    const fromIdx = ARGS.indexOf('--from');
    const local = fromIdx !== -1 ? ARGS[fromIdx + 1] : null;
    if (!p || !local) { console.error('ps-mesh write: needs <host> <remote path> --from <local file>'); process.exit(2); }
    if (!fs.existsSync(local)) { console.error(`ps-mesh write: local file not found: ${local}`); process.exit(1); }
    const textIdx = ARGS.indexOf('--text');
    const bytes = textIdx !== -1 ? Buffer.from(ARGS[textIdx + 1], 'utf8') : fs.readFileSync(local);
    const r = writeFileB64(host, p, bytes.toString('base64'), 120000);
    if (!r.ok) { console.error(r.err || `could not write ${p} on ${host}`); process.exit(1); }
    console.log(`  wrote ${p} on ${host} (${bytes.length} bytes sent, byte-faithful)`);
    if (r.out.trim()) console.log(`  remote reports ${r.out.trim()} bytes`);
    return;
  }

  if (VERB === 'env') {
    // A .env holds the machine's secrets. Listing the NAMES answers "what is configured here" and is
    // safe; printing a VALUE is a deliberate act, so it needs --key and says which one it is doing.
    const p = ARGS[2] && !ARGS[2].startsWith('--') ? ARGS[2] : null;
    if (!p) { console.error('ps-mesh env: needs the .env path, e.g. /home/zabz/personal-secretary-mvp/.env'); process.exit(2); }
    const keyIdx = ARGS.indexOf('--key');
    if (keyIdx !== -1) {
      const key = ARGS[keyIdx + 1];
      if (!key) { console.error('ps-mesh env: --key needs a name'); process.exit(2); }
      const r = windows ? readEnvValueWindows(host, p, key) : run(host, `grep -m1 '^${key}=' "${p}"`, 30000);
      if (!r.ok || !r.out || /NOSUCHFILE/.test(r.out)) { console.error(`ps-mesh: ${key} is not set in ${p} on ${host}`); process.exit(1); }
      const line = r.out.split('\n').map((l) => l.replace(/\r$/, '')).find((l) => l.startsWith(`${key}=`)) || '';
      const value = line.slice(key.length + 1).trim();
      // A secret pasted into a terminal ends up in scrollback, in a log, or in a model's context.
      // Show enough to confirm WHICH value it is, and require an explicit flag to print all of it.
      if (ARGS.includes('--show-secret')) { console.log(`${key}=${value}`); return; }
      const shown = value.length <= 4 ? '*'.repeat(value.length) : `${value.slice(0, 4)}${'*'.repeat(Math.max(0, value.length - 4))}`;
      console.log(`  ${key} on ${host}: ${shown}   (${value.length} chars)`);
      console.log(`  to print it in full:  add --show-secret`);
      return;
    }
    const r = windows
      ? readEnvNamesWindows(host, p)
      : run(host, `grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${p}" | grep -v '^[[:space:]]*#' | sed 's/=.*//' | sort -u`, 45000);
    if (!r.ok) { console.error(r.err || `could not read ${p} on ${host}`); process.exit(1); }
    if (/NO SUCH FILE/i.test(r.out)) { console.error(`ps-mesh: no file at ${p} on ${host}`); process.exit(1); }
    const names = r.out.split('\n').map((l) => l.trim().replace(/\r$/, '')).filter(Boolean);
    console.log(`  ${names.length} variable(s) configured in ${p} on ${host} (names only):`);
    for (const n of names) console.log(`    ${n}`);
    console.log('\n  one value:  ps-mesh env ' + host + ' ' + p + ' --key NAME');
    return;
  }

  console.error('ps-mesh: commands -> hosts | run <host> "cmd" | file <host> <path> | env <host> <path> [--key NAME]');
  process.exit(2);
}

main();
