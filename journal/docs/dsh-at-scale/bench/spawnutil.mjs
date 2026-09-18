// spawnutil.mjs — shared raw-spawn timing for the benchmark battery.
import { spawn } from 'node:child_process';
import { performance } from 'node:perf_hooks';

export function one(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const t0 = performance.now();
    let child;
    try { child = spawn(cmd, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], ...opts }); }
    catch (e) { reject(e); return; }
    const tSpawn = performance.now();
    child.on('error', reject);
    child.on('exit', () => resolve({ tSpawnMs: tSpawn - t0, tExitMs: performance.now() - t0 }));
  });
}

export async function battery(cases, n = 10, warm = 2) {
  const results = {};
  for (const [name, [cmd, args, opts]] of Object.entries(cases)) {
    const spawnTimes = [], exitTimes = [];
    for (let i = 0; i < n + warm; i++) {
      const r = await one(cmd, args, opts);
      if (i < warm) continue;
      spawnTimes.push(r.tSpawnMs); exitTimes.push(r.tExitMs);
    }
    results[name] = { cmd: [cmd, ...args].join(' '), spawnReturn: stats(spawnTimes), cycle: stats(exitTimes) };
    console.log(name, JSON.stringify(results[name]));
  }
  return results;
}

export function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
  return {
    n: s.length, min: +s[0].toFixed(1), p50: +q(0.5).toFixed(1),
    mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1),
    p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1),
  };
}
