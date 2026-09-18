/**
 * Is the proxy's streaming actually smooth, or does it stall?
 *
 * The first verification reported a 1000 ms maximum inter-chunk gap through the proxy against
 * 175 ms direct. That is either a cold start on the first request (expected, once per isolate) or
 * genuine buffering (a defect, because it would eat the speed this proxy exists to restore).
 * Those have completely different fixes, so they are separated rather than averaged together.
 *
 * Usage: node gap-analysis.mjs <apiKey> [proxyBase] [runs]
 */
import https from 'node:https';

const [, , apiKey, base, runsArg] = process.argv;
const runs = Number(runsArg || 6);
const MODEL = 'deepseek-flash';
const PROMPT = 'Write a short paragraph about phone screen repair.';

function callOnce() {
  return new Promise((resolve) => {
    const u = new URL(base + '/v1/chat/completions');
    const payload = JSON.stringify({
      model: MODEL, messages: [{ role: 'user', content: PROMPT }],
      max_tokens: 200, stream: true, stream_options: { include_usage: true },
    });
    const t0 = process.hrtime.bigint();
    let tFirst = null, last = null;
    const gaps = [];
    let events = 0, done = false;
    const req = https.request({
      hostname: u.hostname, path: u.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}`, 'Content-Length': Buffer.byteLength(payload) },
    }, (res) => {
      let buf = '';
      res.on('data', (chunk) => {
        const now = Number(process.hrtime.bigint() - t0) / 1e6;
        if (tFirst === null) tFirst = now;
        if (last !== null) gaps.push(Math.round(now - last));
        last = now;
        buf += chunk.toString();
        const lines = buf.split('\n'); buf = lines.pop();
        for (const l of lines) {
          if (l.startsWith('data:')) {
            const d = l.slice(5).trim();
            if (d === '[DONE]') { done = true; continue; }
            if (d) events++;
          }
        }
      });
      res.on('end', () => {
        const total = Number(process.hrtime.bigint() - t0) / 1e6;
        const sorted = [...gaps].sort((a, b) => b - a);
        resolve({
          ttft: tFirst === null ? null : Math.round(tFirst),
          total: Math.round(total),
          events, done,
          maxGap: sorted[0] ?? 0,
          secondGap: sorted[1] ?? 0,
          gapsOver300: gaps.filter((g) => g > 300).length,
        });
      });
    });
    req.on('error', (e) => resolve({ error: e.message }));
    req.setTimeout(120000, () => req.destroy(new Error('timeout')));
    req.write(payload); req.end();
  });
}

console.log(`${runs} sequential runs through ${base}\n`);
console.log('run  TTFT ms  total ms  events  maxGap  gaps>300ms  [DONE]');
const rows = [];
for (let i = 1; i <= runs; i++) {
  const r = await callOnce();
  rows.push(r);
  if (r.error) { console.log(`${String(i).padStart(3)}  ERROR ${r.error}`); continue; }
  console.log(`${String(i).padStart(3)}  ${String(r.ttft).padStart(7)}  ${String(r.total).padStart(8)}  ${String(r.events).padStart(6)}  ${String(r.maxGap).padStart(6)}  ${String(r.gapsOver300).padStart(10)}  ${r.done}`);
}
const ok = rows.filter((r) => !r.error);
if (ok.length > 1) {
  console.log('\n--- is the first run the outlier? (cold start vs buffering) ---');
  console.log(`  run 1     maxGap ${ok[0].maxGap} ms, TTFT ${ok[0].ttft} ms`);
  const rest = ok.slice(1);
  const avgRest = Math.round(rest.reduce((a, r) => a + r.maxGap, 0) / rest.length);
  console.log(`  runs 2+   avg maxGap ${avgRest} ms  (max ${Math.max(...rest.map((r) => r.maxGap))} ms)`);
  const firstIsOutlier = rest.every((r) => r.maxGap < ok[0].maxGap);
  console.log(`  verdict   : ${firstIsOutlier ? 'COLD START on run 1 - steady state streams cleanly' : 'stalls recur - investigate buffering'}`);
}
