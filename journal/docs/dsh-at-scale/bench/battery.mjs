// battery.mjs — one interleaved battery so every case sees the same machine load.
// Measures, per case: process-creation cost (spawn -> 'spawn' event) and full
// cycle (spawn -> exit). Run: node battery.mjs [n]
import fs from 'node:fs';
import { performance } from 'node:perf_hooks';
import { battery, one, stats } from './spawnutil.mjs';

const n = Number(process.argv[2] ?? 10);
const DSH = 'C:\\Users\\ezabz\\AppData\\Local\\npm-cache\\_npx\\1e7f6d9597241db0\\node_modules\\@deepseek-ai\\';
const RUNNER = DSH + 'dsh-subprocess-local\\lib\\runner.js';
const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';

const cases = {
  // reference: Windows process creation, cheapest target
  'cmd-exit': ['cmd.exe', ['/d', '/c', 'exit 0']],
  // pwsh, exactly the argv pwsh-local builds (mode A: bypassing runner)
  'pwsh-noprofile': [PWSH, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'exit 0']],
  'pwsh-with-profile': [PWSH, ['-NoLogo', '-NonInteractive', '-Command', 'exit 0']],
  // the runner process itself, idle: this is the per-call cost mode B pays first
  'runner-idle': [process.execPath, [RUNNER]],
  // node startup with the compile cache warm
  'node-e': ['node', ['-e', 'process.exit(0)']],
  // a realistic small command workload under each mode
  'pwsh-work': [PWSH, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); Get-Date | Out-Null']],
};

const out = { host: process.env.COMPUTERNAME, node: process.version, startedAt: new Date().toISOString(), n, cases: await battery(cases, n) };

// Second pass: the same cases measured in-process around each spawn so the
// per-case CPU and page-fault cost is visible (resourceUsage is a per-process
// running total, so a delta around one case is that case's cost).
out.resourceUsage = {};
for (const [name, [cmd, args]] of Object.entries(cases)) {
  const r0 = process.resourceUsage();
  const t0 = performance.now();
  for (let i = 0; i < 5; i++) await one(cmd, args);
  const wall = (performance.now() - t0) / 5;
  const r1 = process.resourceUsage();
  out.resourceUsage[name] = {
    minorFaults: Math.round((r1.minorPageFault - r0.minorPageFault) / 5),
    majorFaults: Math.round((r1.majorPageFault - r0.majorPageFault) / 5),
    userCpuMs: +(((r1.userCPUTime - r0.userCPUTime) / 1000) / 5).toFixed(1),
    sysCpuMs: +(((r1.systemCPUTime - r0.systemCPUTime) / 1000) / 5).toFixed(1),
    wallMs: +wall.toFixed(1),
  };
  console.log('ru', name, JSON.stringify(out.resourceUsage[name]));
}

out.finishedAt = new Date().toISOString();
const file = 'C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\battery.json';
fs.writeFileSync(file, JSON.stringify(out, null, 2));
console.error('wrote ' + file);
