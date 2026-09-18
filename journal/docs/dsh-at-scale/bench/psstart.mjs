// psstart.mjs — what actually costs time in a PowerShell 7 start on this host.
// A/B under the same load: module autoload on/off, JIT/assembly cache warm-up,
// and a second identical run after the first (OS image cache effect).
import { performance } from 'node:perf_hooks';
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';
const N = Number(process.argv[2] ?? 14);

function one(args, env) {
  return new Promise((resolve, reject) => {
    const t0 = performance.now();
    const c = spawn(PWSH, args, { windowsHide: true, stdio: ['ignore', 'ignore', 'ignore'], env: env ?? process.env });
    c.on('error', reject);
    c.on('exit', () => resolve(performance.now() - t0));
  });
}
function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
  return { n: s.length, min: +s[0].toFixed(1), p25: +q(0.25).toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p75: +q(0.75).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) };
}
const base = ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'exit 0'];
const envNoModules = { ...process.env, PSModulePath: '' };

const cases = {
  'A. baseline (-NoLogo -NoProfile -NonInteractive -Command exit 0)': () => one(base),
  'B. same argv, PSModulePath empty': () => one(base, envNoModules),
  'C. same argv, DSH-style UTF8 preamble + Get-Date': () => one(['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); Get-Date|Out-Null']),
  'D. baseline again (2nd identical pass, image-cache effect)': () => one(base),
  'E. baseline with PSModulePath empty, 2nd pass': () => one(base, envNoModules),
};

const out = { host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), node: process.version, n: N, cases: {}, series: {} };
for (const [name, fn] of Object.entries(cases)) {
  const xs = [];
  for (let i = 0; i < N; i++) xs.push(await fn());
  out.cases[name] = stats(xs);
  out.series[name] = xs.map((x) => +x.toFixed(0));
  console.log(name, JSON.stringify(out.cases[name]));
}
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\psstart.json', JSON.stringify(out, null, 2));
