// qos.mjs — does windowsHide (a hidden, never-focused window) change pwsh start
// cost on this host? Microsoft documents that Win11 QoS classifies a
// non-foreground process lower and that "automated tests lacking user input may
// trigger this feature, lowering QoS and skewing results".
import { performance } from 'node:perf_hooks';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';
const REP = Number(process.argv[2] ?? 12);
function one(opts) {
  return new Promise((res, rej) => {
    const t0 = performance.now();
    const c = spawn(PWSH, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'Get-Date|Out-Null'], { stdio: ['ignore', 'ignore', 'ignore'], ...opts });
    c.on('error', rej); c.on('exit', () => res(performance.now() - t0));
  });
}
const variants = {
  'windowsHide:true (harness default)': { windowsHide: true },
  'windowsHide:false (visible window)': { windowsHide: false },
  'windowsHide:true + detached + priority': { windowsHide: true, detached: false },
  'windowsHide:true (repeat)': { windowsHide: true },
};
const o = {}; for (const k of Object.keys(variants)) o[k] = [];
for (let i = 0; i < REP; i++) for (const [k, v] of Object.entries(variants)) o[k].push(await one(v));
const stats = (xs) => { const s = [...xs].sort((a, b) => a - b); const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))]; return { n: s.length, min: +s[0].toFixed(1), p10: +q(0.1).toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) }; };
const out = { measuredAt: new Date().toISOString(), host: process.env.COMPUTERNAME, reps: REP, cases: {} };
for (const [k, xs] of Object.entries(o)) { out.cases[k] = stats(xs); console.log(k, JSON.stringify(out.cases[k])); }
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\qos.json', JSON.stringify(out, null, 2));
