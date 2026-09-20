// spawnbench.mjs — measure process-spawn cost on Windows with counter deltas.
// Usage: node spawnbench.mjs <case> [n]
// Cases: pwsh, pwsh-nop, node-e, npx, cmd-echo, pwsh-runnerlike
import { spawn, spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import fs from 'node:fs';

const WARM = 2; // discarded iterations

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const t0 = performance.now();
    let child;
    try {
      child = spawn(cmd, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], ...opts });
    } catch (e) { reject(e); return; }
    const tSpawn = performance.now();
    child.on('error', reject);
    child.on('exit', (code) => {
      const tExit = performance.now();
      resolve({ code, tSpawnMs: tSpawn - t0, tExitMs: tExit - t0 });
    });
  });
}

function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
  const mean = s.reduce((a, b) => a + b, 0) / s.length;
  return { n: s.length, min: +s[0].toFixed(1), p50: +q(0.5).toFixed(1), mean: +mean.toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) };
}

const CASES = {
  'pwsh':        ['C:\\Program Files\\PowerShell\\7\\pwsh.exe', ['-Command', 'exit 0']],
  'pwsh-nop':    ['C:\\Program Files\\PowerShell\\7\\pwsh.exe', ['-NoProfile', '-NonInteractive', '-Command', 'exit 0']],
  'node-e':      ['node', ['-e', 'process.exit(0)']],
  'npx':         ['cmd.exe', ['/d', '/c', 'npx --no-install --version']],
  'npx-cmd-shim':['C:\\Users\\ezabz\\AppData\\Roaming\\npm\\npx.cmd', ['--no-install', '--version']],
  'cmd-echo':    ['cmd.exe', ['/d', '/c', 'exit 0']],
  'where':       ['where.exe', ['cmd.exe']],
};

const which = process.argv[2] ?? 'all';
const n = Number(process.argv[3] ?? 15);

const names = which === 'all' ? Object.keys(CASES) : [which];
const out = { host: process.env.COMPUTERNAME, node: process.version, cpu: process.env.PROCESSOR_IDENTIFIER, measuredAt: new Date().toISOString(), cases: {} };

for (const name of names) {
  const spec = CASES[name];
  if (!spec) { console.error('unknown case', name); process.exit(2); }
  const spawnTimes = [], exitTimes = [], codes = [];
  for (let i = 0; i < n + WARM; i++) {
    // resourceUsage deltas around each iteration, in-process
    const ru0 = process.resourceUsage();
    let r;
    try { r = await run(spec[0], spec[1]); } catch (e) { codes.push('ERR ' + e.code); continue; }
    const ru1 = process.resourceUsage();
    if (i < WARM) continue;
    spawnTimes.push(r.tSpawnMs);
    exitTimes.push(r.tExitMs);
    codes.push(r.code);
    void ru0; void ru1;
  }
  const ru0 = process.resourceUsage();
  const t0 = performance.now();
  for (let i = 0; i < 3; i++) await run(spec[0], spec[1]);
  const ru1 = process.resourceUsage();
  out.cases[name] = {
    cmd: [spec[0], ...spec[1]].join(' '),
    spawnReturn: stats(spawnTimes),
    exit: stats(exitTimes),
    codes: [...new Set(codes)].slice(0, 3),
    minorFaultsPerSpawn: Math.round((ru1.minorPageFault - ru0.minorPageFault) / 3),
    majorFaultsPerSpawn: Math.round((ru1.majorPageFault - ru0.majorPageFault) / 3),
    userCpuMsPerSpawn: +(((ru1.userCPUTime - ru0.userCPUTime) / 1000) / 3).toFixed(1),
    sysCpuMsPerSpawn: +(((ru1.systemCPUTime - ru0.systemCPUTime) / 1000) / 3).toFixed(1),
    wallMsPerSpawn: +((performance.now() - t0) / 3).toFixed(1),
  };
  console.log(JSON.stringify(out.cases[name]));
}

const file = process.argv[4] ?? `C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\spawn-${which}.json`;
fs.writeFileSync(file, JSON.stringify(out, null, 2));
console.error('wrote ' + file);
