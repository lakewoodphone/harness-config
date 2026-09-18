// steady2.mjs — interleaved A/B (round-robin) so machine-load drift cancels.
import { performance } from 'node:perf_hooks';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';
const ENC = '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [System.Text.UTF8Encoding]::new($false); ';
const REP = Number(process.argv[2] ?? 24);
const base = ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command'];
const variants = {
  'plain-exit': [null, base.concat('exit 0')],
  'enc-exit': [null, base.concat(ENC + 'exit 0')],
  'enc-getdate': [null, base.concat(ENC + 'Get-Date|Out-Null')],
  'enc-echo': [null, base.concat(ENC + 'Write-Output hi')],
  'noprofile-off': [null, ['-NoLogo', '-NonInteractive', '-Command', ENC + 'exit 0']],
  'nomodules': [{ ...process.env, PSModulePath: '' }, base.concat(ENC + 'exit 0')],
  'noautoload': [{ ...process.env, PSModulePath: process.env.PSModulePath }, base.concat(ENC + 'Set-Variable -Name PSModuleAutoLoadingPreference -Value None; exit 0')],
};
function one(args, env) {
  return new Promise((res, rej) => {
    const t0 = performance.now();
    const c = spawn(PWSH, args, { windowsHide: true, stdio: ['ignore', 'ignore', 'ignore'], env: env ?? process.env });
    c.on('error', rej); c.on('exit', () => res(performance.now() - t0));
  });
}
const samples = Object.fromEntries(Object.keys(variants).map((k) => [k, []]));
for (let r = 0; r < REP; r++) for (const [k, [env, args]] of Object.entries(variants)) samples[k].push(await one(args, env));
const stats = (xs) => { const s = [...xs].sort((a, b) => a - b); const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))]; return { n: s.length, min: +s[0].toFixed(1), p10: +q(0.1).toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) }; };
const out = { host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), reps: REP, cases: {} };
for (const [k, xs] of Object.entries(samples)) { out.cases[k] = stats(xs); console.log(k, JSON.stringify(out.cases[k])); }
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\steady2.json', JSON.stringify(out, null, 2));
