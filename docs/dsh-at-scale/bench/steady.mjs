// steady.mjs — long steady-state series; the MINIMUM is the cleanest estimator of
// startup cost under a noisy host, so report min/p10 alongside p50.
import { performance } from 'node:perf_hooks';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';
const RUNNER = 'C:\\Users\\ezabz\\AppData\\Local\\npm-cache\\_npx\\1e7f6d9597241db0\\node_modules\\@deepseek-ai\\dsh-subprocess-local\\lib\\runner.js';
const N = Number(process.argv[2] ?? 30);
const ENC = '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [System.Text.UTF8Encoding]::new($false); ';
function one(cmd, args) {
  return new Promise((res, rej) => {
    const t0 = performance.now();
    const c = spawn(cmd, args, { windowsHide: true, stdio: ['ignore', 'ignore', 'ignore'] });
    c.on('error', rej); c.on('exit', () => res(performance.now() - t0));
  });
}
const stats = (xs) => { const s = [...xs].sort((a, b) => a - b); const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))]; return { n: s.length, min: +s[0].toFixed(1), p10: +q(0.1).toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) }; };
const cases = {
  'cmd exit': ['cmd.exe', ['/d', '/c', 'exit 0']],
  'pwsh enc exit': [PWSH, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', ENC + 'exit 0']],
  'pwsh enc getdate': [PWSH, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', ENC + 'Get-Date|Out-Null']],
  'pwsh enc echo': [PWSH, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', ENC + "Write-Output hi"]],
  'runner idle': [process.execPath, [RUNNER]],
  'node -e': ['node', ['-e', '0']],
};
const out = { host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), n: N, cases: {}, series: {} };
for (const [name, [c, a]] of Object.entries(cases)) {
  const xs = [];
  for (let i = 0; i < N; i++) xs.push(await one(c, a));
  out.cases[name] = stats(xs); out.series[name] = xs.map((x) => +x.toFixed(0));
  console.log(name, JSON.stringify(out.cases[name]));
}
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\steady.json', JSON.stringify(out, null, 2));
