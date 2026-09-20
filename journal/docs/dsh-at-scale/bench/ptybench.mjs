// ptybench.mjs — cost of the persistent-shell path: the ctx.terminals seam is
// backed by node-pty (ConPTY on Windows, build 18309+). This measures, per
// ConPTY session: spawn cost, then the round-trip of writing one wrapped
// command and waiting for its end marker in the output stream.
import { performance } from 'node:perf_hooks';
import fs from 'node:fs';
const pty = await import('file:///C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/node-pty/lib/index.js');

const PWSH = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe';
const n = Number(process.argv[2] ?? 5);
const perSession = Number(process.argv[3] ?? 6);
const spawnMs = [], rtMs = [];
const results = [];
for (let i = 0; i < n; i++) {
  const t0 = performance.now();
  const p = pty.spawn(PWSH, ['-NoLogo'], { name: 'dumb', cols: 200, rows: 50, cwd: process.cwd(), env: { ...process.env } });
  await new Promise((r) => setTimeout(r, 150)); // let ConPTY attach, same as the tool's init barrier
  spawnMs.push(performance.now() - t0);
  let buffered = '';
  const data = p.onData((d) => { buffered += d; });
  await new Promise((r) => setTimeout(r, 1200)); // shell fully initialized
  for (let j = 0; j < perSession; j++) {
    const t1 = performance.now();
    const nonce = 'X' + i + '_' + j + 'Y';
    p.write(`Write-Output '__S_${nonce}__'; Write-Output '__E_${nonce}:0'\r`);
    const deadline = Date.now() + 20000;
    while (!buffered.includes('__E_' + nonce + ':0') && Date.now() < deadline) await new Promise((r) => setTimeout(r, 2));
    rtMs.push(performance.now() - t1);
    results.push({ cycle: i + '.' + j, spawnMs: +spawnMs.at(-1).toFixed(1), roundTripMs: +rtMs.at(-1).toFixed(1), sawEnd: buffered.includes('__E_' + nonce + ':0') });
  }
  data.dispose();
  p.kill();
  await new Promise((r) => setTimeout(r, 100));
}
function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
  return { n: s.length, min: +s[0].toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) };
}
const out = { host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), node: process.version, conpty: true, spawnMs: stats(spawnMs), roundTripMs: stats(rtMs), results };
console.log(JSON.stringify(out, null, 1));
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\ptybench.json', JSON.stringify(out, null, 2));
