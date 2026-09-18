// psstart2.mjs — isolate the cost of the DSH encoding preamble and of -NoProfile.
import { performance } from 'node:perf_hooks';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';
const N = Number(process.argv[2] ?? 12);
const ENC = '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [System.Text.UTF8Encoding]::new($false); ';
function one(args) {
  return new Promise((res, rej) => {
    const t0 = performance.now();
    const c = spawn(PWSH, args, { windowsHide: true, stdio: ['ignore', 'ignore', 'ignore'] });
    c.on('error', rej); c.on('exit', () => res(performance.now() - t0));
  });
}
const stats = (xs) => { const s = [...xs].sort((a, b) => a - b); const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))]; return { n: s.length, min: +s[0].toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) }; };
const cases = {
  'exit 0': ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'exit 0'],
  'ENC + exit 0': ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', ENC + 'exit 0'],
  'ENC + Get-Date|Out-Null': ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', ENC + 'Get-Date | Out-Null'],
  'Get-Date|Out-Null': ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'Get-Date | Out-Null'],
  'exit 0 (with profile)': ['-NoLogo', '-NonInteractive', '-Command', 'exit 0'],
  'ENC + exit 0 (interleaved 2nd)': ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', ENC + 'exit 0'],
  '[System.Text.UTF8Encoding]::new($false) alone': ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '[System.Text.UTF8Encoding]::new($false) | Out-Null'],
};
const out = { host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), n: N, cases: {} };
for (const [name, args] of Object.entries(cases)) {
  const xs = [];
  for (let i = 0; i < N; i++) xs.push(await one(args));
  out.cases[name] = { argv: args.slice(3).join(' '), ...stats(xs) };
  console.log(name, JSON.stringify(out.cases[name]));
}
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\psstart2.json', JSON.stringify(out, null, 2));
