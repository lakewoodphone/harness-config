/**
 * One measurement level, with the TARGET's own counters captured alongside it.
 *
 * WHY THE SAMPLER IS HELD BY A LIVE SSH SESSION, AND NOT DETACHED
 * A `Start-Process`-detached sampler on the target is killed the moment the ssh session that
 * launched it exits — measured here: the CSV it wrote contains the header and nothing else, while
 * the identical script run inside a live session produced a row every four seconds. So the remote
 * program runs the sampler in the FOREGROUND for a bounded number of seconds and then prints the
 * CSV it collected, and the ssh session stays open for the whole level. No detached process, no
 * stray to clean up, and the rows cannot outlive the session that owns them.
 *
 * The driver runs locally, in parallel, so the sampler's window covers the level and a little
 * either side of it.
 *
 *   node packages/plugin-mesh-http/test/run-level.mjs \
 *     --node zabz-tech --transport v2 --n 12 --label v2-n12 --sampler-seconds 150 \
 *     --secret-file C:/Users/ezabz/AppData/Local/Temp/mesh-tech-secret.env --out C:/Users/ezabz/mesh-sweep
 *
 * `--no-children` runs the sampler alone: it is how the capture mechanism is verified without
 * spending a single agent turn.
 */

import { spawn } from 'node:child_process';
import { closeSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs, runLevel } from './concurrency-sweep.mjs';

const TARGET_SSH = process.env.MESH_TARGET_SSH ?? 'desktop-ts';
const TARGET_SAMPLER = process.env.MESH_TARGET_SAMPLER
  ?? 'C:/Users/ezabz/code/harness-config/packages/plugin-mesh-http/test/sweep-sampler.ps1';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The program the target runs: sample for N seconds, then hand the whole CSV back on stdout. */
export function samplerProgram({ label, seconds, sampler = TARGET_SAMPLER }) {
  return [
    '$ErrorActionPreference = "Continue"',
    '$env:HTTP_PROXY=""; $env:HTTPS_PROXY=""; $env:NO_PROXY="*"',
    `$csv = "$env:TEMP\\sweep-${label}.csv"`,
    'Remove-Item $csv -Force -ErrorAction SilentlyContinue',
    'Write-Output "SAMPLER-BEGIN"',
    `& pwsh -NoProfile -File '${sampler}' -Csv $csv -PeriodSec 3 -DurationSec ${seconds} -Label ${label} 2>&1 | ForEach-Object { Write-Output ("SAMPLER-ERR: " + $_) }`,
    'Write-Output "SAMPLER-END"',
    'Get-Content -LiteralPath $csv -Raw',
  ].join('\n');
}

export async function runLevelWithSampler({ label, samplerSeconds, noChildren, ...levelOptions }) {
  const outDir = path.join(levelOptions.out, label);
  mkdirSync(outDir, { recursive: true });
  const stdoutPath = path.join(outDir, 'target-session.stdout.txt');
  const stderrPath = path.join(outDir, 'target-session.stderr.txt');
  const so = openSync(stdoutPath, 'w');
  const se = openSync(stderrPath, 'w');
  const program = samplerProgram({ label, seconds: samplerSeconds });
  const encoded = Buffer.from(program, 'utf16le').toString('base64');
  const startedAt = Date.now();
  const ssh = spawn('ssh', [
    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=20',
    TARGET_SSH, 'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded,
  ], { stdio: ['ignore', so, se], windowsHide: true });
  const closed = new Promise((resolve) => { ssh.on('close', (code) => resolve(code)); });

  // Give the sampler three rows before anything is dispatched, so the level has a baseline on both
  // sides. A sampler that produced no row by now is a broken capture, and it is worth knowing
  // BEFORE the turns are spent — that is the lesson of the first two tries.
  await sleep(9000);
  const seen = readFileSync(stdoutPath, 'utf8');
  if (!seen.includes('SAMPLER-BEGIN')) {
    ssh.kill('SIGKILL');
    throw new Error(`the sampler never started; see ${stderrPath}`);
  }

  let level = null;
  if (noChildren !== true) {
    level = await runLevel({ label, ...levelOptions });
    writeFileSync(path.join(outDir, 'caller.json'), `${JSON.stringify(level, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify({ ...level, raw: undefined }, null, 2)}\n`);
  }

  // Let the sampler record the settling tail, then wait for the session to close on its own.
  const remainingMs = samplerSeconds * 1000 - (Date.now() - startedAt) + 20000;
  const timedOut = await Promise.race([
    closed.then(() => false),
    sleep(Math.max(remainingMs, 15000)).then(() => true),
  ]);
  if (timedOut) {
    ssh.kill('SIGKILL');
    await closed;
  } else {
    await closed;
  }
  try { closeSync(so); } catch { /* closed */ }
  try { closeSync(se); } catch { /* closed */ }

  const sessionOut = readFileSync(stdoutPath, 'utf8');
  const csvStart = sessionOut.indexOf('label,ts,');
  const csv = csvStart === -1 ? '' : sessionOut.slice(csvStart);
  writeFileSync(path.join(outDir, 'target.csv'), csv, 'utf8');
  const rows = csv.split(/\r?\n/).filter((line) => line.trim() !== '').length;
  const result = {
    label, samplerSeconds, sshExit: await closed, sessionMs: Date.now() - startedAt,
    csvRows: rows, csvPath: path.join(outDir, 'target.csv'), callerPath: level === null ? null : path.join(outDir, 'caller.json'),
  };
  process.stdout.write(`${JSON.stringify({ phase: 'capture', ...result }, null, 2)}\n`);
  if (rows === 0) throw new Error(`no counter rows captured; see ${stdoutPath}`);
  return result;
}

const isMain = process.argv[1] !== undefined && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const argv = process.argv.slice(2);
  const capture = { samplerSeconds: 120, noChildren: false };
  const rest = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--sampler-seconds') capture.samplerSeconds = Number(argv[++i]);
    else if (argv[i] === '--no-children') capture.noChildren = true;
    else rest.push(argv[i]);
  }
  const options = parseArgs(rest);
  await runLevelWithSampler({ ...capture, ...options });
  process.exit(0);
}
