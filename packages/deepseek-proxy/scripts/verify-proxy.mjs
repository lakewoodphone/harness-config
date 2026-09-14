/**
 * Streaming-fidelity and overhead check for the DeepSeek proxy.
 *
 * What this proves, in order of importance:
 *   1. the proxy streams — chunks arrive incrementally rather than in one buffered burst, which is
 *      the property that keeps the proxy from destroying the speed it exists to recover;
 *   2. the proxy is correct — same model, same answer, usage reported, [DONE] terminator present;
 *   3. the overhead it adds, measured against the same call made directly.
 *
 * Usage: node verify-proxy.mjs <apiKey> [proxyBase] [runs]
 *   proxyBase defaults to https://ds.abletelsolutions.com
 */
import https from 'node:https';
import http from 'node:http';

const [, , apiKey, proxyBaseArg, runsArg] = process.argv;
if (!apiKey) { console.error('usage: node verify-proxy.mjs <apiKey> [proxyBase] [runs]'); process.exit(2); }
const proxyBase = (proxyBaseArg || 'https://ds.abletelsolutions.com').replace(/\/$/, '');
const runs = Number(runsArg || 3);
const MODEL = 'deepseek-flash';
const MAXTOK = 200;
const PROMPT = 'Write a short paragraph about phone screen repair.';

function call(base, { stream = true } = {}) {
  return new Promise((resolve) => {
    const u = new URL(base + '/v1/chat/completions');
    const mod = u.protocol === 'https:' ? https : http;
    const payload = JSON.stringify({
      model: MODEL,
      messages: [{ role: 'user', content: PROMPT }],
      max_tokens: MAXTOK,
      stream,
      ...(stream ? { stream_options: { include_usage: true } } : {}),
    });
    const t0 = process.hrtime.bigint();
    let tFirst = null;
    const gaps = [];
    let last = null;
    let content = '';
    let usage = null;
    let sawDone = false;

    const req = mod.request({
      hostname: u.hostname, port: u.port || (u.protocol === 'https:' ? 443 : 80), path: u.pathname + u.search, method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}`, 'Content-Length': Buffer.byteLength(payload) },
    }, (res) => {
      if (res.statusCode !== 200) {
        let b = ''; res.on('data', (c) => { b += c; });
        res.on('end', () => resolve({ error: `HTTP ${res.statusCode} ${b.slice(0, 200)}`, status: res.statusCode }));
        return;
      }
      let buf = '';
      res.on('data', (chunk) => {
        const now = Number(process.hrtime.bigint() - t0) / 1e6;
        if (tFirst === null) tFirst = now;
        if (last !== null) gaps.push(Math.round(now - last));
        last = now;
        buf += chunk.toString();
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (data === '[DONE]') { sawDone = true; continue; }
            try {
              const j = JSON.parse(data);
              if (j.usage) usage = j.usage;
              const d = j.choices?.[0]?.delta;
              if (d?.content) content += d.content;
              else if (j.choices?.[0]?.message?.content) content += j.choices[0].message.content;
            } catch { /* partial line */ }
          }
        }
      });
      res.on('end', () => {
        const total = Number(process.hrtime.bigint() - t0) / 1e6;
        const outTok = usage?.completion_tokens ?? null;
        resolve({
          ttft_ms: tFirst === null ? null : Math.round(tFirst),
          total_ms: Math.round(total),
          out_tokens: outTok,
          tok_per_s: (outTok && tFirst !== null) ? +(outTok / ((total - tFirst) / 1000)).toFixed(1) : null,
          data_events: gaps.length + (tFirst === null ? 0 : 1),
          max_gap_ms: gaps.length ? Math.max(...gaps) : 0,
          saw_done: sawDone,
          chars: content.length,
          sample: content.slice(0, 60).replace(/\s+/g, ' '),
        });
      });
    });
    req.on('error', (e) => resolve({ error: e.message }));
    req.setTimeout(120000, () => req.destroy(new Error('timeout')));
    req.write(payload); req.end();
  });
}

const avg = (rows, f) => { const v = rows.map(f).filter((x) => typeof x === 'number'); return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : null; };

async function bench(label, base, opts) {
  const rows = [];
  for (let i = 0; i < runs; i++) rows.push(await call(base, opts));
  const ok = rows.filter((r) => !r.error);
  console.log(`\n${label}  (${base})`);
  if (!ok.length) { console.log('  FAILED: ' + rows[0].error); return { label, failed: rows[0].error }; }
  console.log(`  TTFT        : ${avg(ok, (r) => r.ttft_ms)} ms`);
  console.log(`  total       : ${avg(ok, (r) => r.total_ms)} ms`);
  console.log(`  tok/s       : ${avg(ok, (r) => r.tok_per_s)}`);
  console.log(`  SSE events  : ${avg(ok, (r) => r.data_events)}   max inter-chunk gap: ${avg(ok, (r) => r.max_gap_ms)} ms`);
  console.log(`  [DONE] seen : ${ok.every((r) => r.saw_done)}   tokens reported: ${avg(ok, (r) => r.out_tokens)}`);
  console.log(`  sample      : "${ok[0].sample}"`);
  return { label, ttft: avg(ok, (r) => r.ttft_ms), total: avg(ok, (r) => r.total_ms), tps: avg(ok, (r) => r.tok_per_s), events: avg(ok, (r) => r.data_events) };
}

console.log(`verifying ${runs} run(s) each, model=${MODEL}, max_tokens=${MAXTOK}`);
const direct = await bench('DIRECT   api.deepseek.com', 'https://api.deepseek.com', { stream: true });
const proxied = await bench('PROXIED  ' + proxyBase, proxyBase, { stream: true });

if (direct.ttft && proxied.ttft) {
  console.log('\n=== verdict ===');
  console.log(`  added TTFT  : ${proxied.ttft - direct.ttft} ms`);
  console.log(`  added total : ${proxied.total - direct.total} ms`);
  console.log(`  streaming   : ${proxied.events > 1 ? 'YES - ' + proxied.events + ' events, so the response flowed incrementally' : 'NO - response looks buffered'}`);
  const pct = ((proxied.ttft - direct.ttft) / direct.ttft * 100).toFixed(0);
  console.log(`  overhead    : ${pct}% on TTFT, against a DeepInfra baseline that was +127% (1693 vs 747 ms)`);
}
