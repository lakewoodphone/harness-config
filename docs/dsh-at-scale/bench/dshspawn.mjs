// dshspawn.mjs — measure the DSH Windows Job-runner spawn path end to end,
// exactly as @deepseek-ai/dsh-pwsh-local does it: runner.js (Job owner) ->
// CreateProcessW inside the Job -> poll(10ms) exit detection.
// Usage: node dshspawn.mjs <n> [program] [..args]
import { performance } from 'node:perf_hooks';
import fs from 'node:fs';
const M = 'file:///C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/';
const { loadWin32ProcessBindings, probeCurrentTokenJobSupport } = await import(M + 'dsh-win32-process/lib/index.js');
const { LocalSubprocessRuntime } = await import(M + 'dsh-subprocess-local/lib/index.js');
const { l: spawnRunnerInvocation, u: targetEnvironment } = await import(M + 'dsh-subprocess-local/lib/runner-launch-COYGu0Dl.js');
await import(M + 'dsh-subprocess-local/lib/index.js');

// Minimal plugin context: the runtime only uses ctx.effect at construction and ctx.logger on fallback.
const ctx = { logger: { warn: (m) => console.error('[warn] ' + m) }, effect: () => () => {} };
const runtime = new LocalSubprocessRuntime(ctx);

const n = Number(process.argv[2] ?? 10);
const argv = process.argv.slice(3);
if (argv.length === 0) argv.push('C:\\Program Files\\PowerShell\\7\\pwsh.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'exit 0');

const collect = (maxBytes) => ({ maxBytes, spill: { maxBytes: 1 << 20 } });
const spec = {
  argv,
  cwd: process.cwd(),
  env: { ...process.env },
  stdio: { stdin: 'ignore', stdout: collect(64000), stderr: collect(64000) },
  graceMs: 2000,
};
validateSubprocessSpec(spec);
const env = targetEnvironment(spec);
const binding = prepareManagedProcessBinding({});

// probe once (production re-probes every spawn)
const tProbeStart = performance.now();
let probeOk = false;
try { const api = loadWin32ProcessBindings(); probeCurrentTokenJobSupport(api); probeOk = true; } catch (e) { probeOk = { err: String(e) }; }
const probeMs = performance.now() - tProbeStart;

const spawnReturn = [], exit = [], doneAt = [];
for (let i = 0; i < n; i++) {
  const t0 = performance.now();
  const handle = bindManagedProcess(spec, launchWindowsJob(spec, env), binding);
  const tSpawn = performance.now();
  await handle.done;
  doneAt.push(performance.now() - t0);
  spawnReturn.push(tSpawn - t0);
  // exit observation latency = done minus (exit recorded by runner) is not visible; use done
}
function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
  return { n: s.length, min: +s[0].toFixed(1), p50: +q(0.5).toFixed(1), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: +q(0.9).toFixed(1), max: +s.at(-1).toFixed(1) };
}
const out = {
  host: process.env.COMPUTERNAME, measuredAt: new Date().toISOString(), node: process.version,
  target: argv.join(' '),
  probeMs: +probeMs.toFixed(1), probeOk,
  launchReturnMs: stats(spawnReturn),
  doneMs: stats(doneAt),
  runnerInvocation: spawnRunnerInvocation(),
};
console.log(JSON.stringify(out));
fs.writeFileSync(`C:\\Users\\ezabz\\code\\_dsh-scale\\bench\\dshspawn-${n}.json`, JSON.stringify(out, null, 2));
