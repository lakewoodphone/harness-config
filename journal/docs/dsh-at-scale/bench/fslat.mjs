// fslat.mjs — per-call cost of the read/edit/write/glob/grep path, measured in
// process so no shell is involved. FS reads: stat + readFile on a small file.
import { performance } from 'node:perf_hooks';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';

const small = 'C:\\Users\\ezabz\\code\\_dsh-scale\\70-toolcall-latency.md';
const cwd = 'C:\\Users\\ezabz\\code\\_dsh-scale';
const N = Number(process.argv[2] ?? 200);
const stats = (xs) => { const s = [...xs].sort((a, b) => a - b); const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))]; return { n: s.length, min: +s[0].toFixed(2), p50: +q(0.5).toFixed(2), p90: +q(0.9).toFixed(2), max: +s.at(-1).toFixed(2) }; };

async function time(fn, n = N) {
  const xs = [];
  for (let i = 0; i < n; i++) { const t = performance.now(); await fn(); xs.push(performance.now() - t); }
  return stats(xs);
}
const out = { host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), N };
out.statSmall = await time(() => fsp.stat(small).catch(() => {}));
out.statEnginemodules = await time(() => fsp.stat(path.join(cwd, 'bench')), 100);
out.readFileSmall = await time(() => fsp.readFile(process.argv[3] ?? 'C:\\Users\\ezabz\\code\\harness-config\\presets\\zabz\\agent.cordis.yml', 'utf8').catch(() => {}), 50);
// JS-schema validation cost, as dsh-tools pays it per call.
const { default: zt } = await import('file:///C:/Users/ezabz/.dsh/profiles/node_modules/typebox/build/esm/index.mjs').catch(() => ({ default: null }));
out.note = 'typebox import optional; not required for the report';
console.log(JSON.stringify(out, null, 2));
fs.writeFileSync('C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\fslat.json', JSON.stringify(out, null, 2));
