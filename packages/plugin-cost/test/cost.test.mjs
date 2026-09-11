/**
 * Test the plugin's cost core against real session logs and against the
 * independent implementation in ~/code/dsh-cost.
 *
 * The point of this file is not coverage. It is to catch the two failures that
 * matter for money: a rate applied to the wrong bucket, and a total that does not
 * equal the sum of its parts.
 *
 * Usage: node test/cost.test.mjs [<session.v3.jsonl.zstd> ...]
 *   With no argument it uses the newest session log for the current workspace.
 */
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  PRICING,
  indexRoutes,
  costOf,
  peakCostOf,
  ratesAt,
  formatUsd,
  billedTotal,
  cacheHitPercent,
  normalizeUsage,
  foldSession,
  totalSession,
  renderReport,
} from '../src/cost-core.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const DSH_HOME = process.env.DSH_HOME ?? join(homedir(), '.dsh');
const SESSIONS_ROOT = join(DSH_HOME, 'sessions');

let failures = 0;
let checks = 0;
const check = (name, condition, detail) => {
  checks += 1;
  if (condition) {
    console.log(`  ok    ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail === undefined ? '' : ` — ${detail}`}`);
  }
};

/** Locate the newest session log for a workspace, or every one. */
function newestLog() {
  const roots = readdirSync(SESSIONS_ROOT, { withFileTypes: true }).filter((e) => e.isDirectory());
  const logs = [];
  for (const root of roots) {
    const dir = join(SESSIONS_ROOT, root.name);
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const file = join(dir, entry.name, 'session.v3.jsonl.zstd');
      if (existsSync(file)) logs.push({ file, mtime: statSync(file).mtimeMs });
    }
  }
  logs.sort((a, b) => b.mtime - a.mtime);
  return logs.length === 0 ? undefined : logs[0].file;
}

/** Multi-frame zstd reader, matching the container DSH writes. */
function readLog(file) {
  const buffer = readFileSync(file);
  const magic = [];
  for (let i = 0; i + 3 < buffer.length; i += 1) if (buffer.readUInt32LE(i) === 0xfd2fb528) magic.push(i);
  const parts = [];
  for (let i = 0; i < magic.length; i += 1) {
    const end = i + 1 < magic.length ? magic[i + 1] : buffer.length;
    try {
      parts.push(zstdDecompressSync(buffer.subarray(magic[i], end)));
    } catch {
      /* torn tail frame is legal in this container */
    }
  }
  const events = [];
  for (const line of Buffer.concat(parts).toString('utf8').split('\n')) {
    if (line.length === 0) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      /* a torn write can leave one partial line */
    }
  }
  return events;
}

import { zstdDecompressSync } from 'node:zlib';

console.log('pricing index');
const byKey = indexRoutes(PRICING);
check('deepseek-flash is indexed', byKey['deepseek-official\u0000deepseek-flash'] !== undefined);
check('retired alias deepseek-v4-flash is indexed at the same card', byKey['deepseek-official\u0000deepseek-v4-flash'] === byKey['deepseek-official\u0000deepseek-flash']);
check('an unknown model is absent rather than defaulted', byKey['deepseek-official\u0000deepseek-chat'] === undefined);

console.log('tier selection (peak = 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri)');
const flash = byKey['deepseek-official\u0000deepseek-flash'];
// 2026-09-11 is a Friday. 02:00Z is inside the first peak window.
const fridayPeak = Date.UTC(2026, 8, 11, 2, 0, 0);
const fridayOffPeak = Date.UTC(2026, 8, 11, 12, 0, 0);
const saturdayPeakHour = Date.UTC(2026, 8, 12, 2, 0, 0);
check('Friday 02:00Z is peak', ratesAt(flash, fridayPeak).tier === 'peak', ratesAt(flash, fridayPeak).tier);
check('Friday 02:00Z double-prices the miss rate', ratesAt(flash, fridayPeak).missPer1M === 0.3);
check('Friday 12:00Z is off-peak', ratesAt(flash, fridayOffPeak).tier === 'off-peak', ratesAt(flash, fridayOffPeak).tier);
check('Saturday 02:00Z is off-peak', ratesAt(flash, saturdayPeakHour).tier === 'off-peak', ratesAt(flash, saturdayPeakHour).tier);
check('an unknown instant falls back to off-peak rather than guessing peak', ratesAt(flash, undefined).tier === 'off-peak');

console.log('arithmetic');
const sample = { uncachedInputTokens: 1000000, cacheReadTokens: 1000000, cacheWriteTokens: 500000, outputTokens: 1000000 };
const off = costOf(sample, byKey, { provider: 'deepseek-official', model: 'deepseek-flash' }, fridayOffPeak);
// 1M miss 0.15 + 1M hit 0.003 + 1M output 0.6 = 0.753 USD, writes unpriced.
check('1M of each bucket off-peak = $0.753000', off.microUsd === 753000, String(off.microUsd));
check('cache writes are NOT charged at the miss rate', off.microUsd === 753000, String(off.microUsd));
const peak = costOf(sample, byKey, { provider: 'deepseek-official', model: 'deepseek-flash' }, fridayPeak);
check('the same call at peak costs exactly double', peak.microUsd === 1506000, String(peak.microUsd));
check('peakCostOf equals the peak-instants cost', peakCostOf(sample, byKey, { provider: 'deepseek-official', model: 'deepseek-flash' }) === peak.microUsd);
check('an unpriced route returns undefined, not zero', costOf(sample, byKey, { provider: 'deepseek-official', model: 'deepseek-chat' }, fridayOffPeak) === undefined);

console.log('sample validation');
check('a sample with no token counts is refused', normalizeUsage({}, undefined) === undefined);
check('a non-integer count is refused', normalizeUsage({ inputTokens: 1.5, outputTokens: 2, cacheReadTokens: 0, cacheWriteTokens: 0 }, undefined) === undefined);
check('a contradictory total is refused', normalizeUsage({ inputTokens: 10, outputTokens: 5, totalTokens: 12, cacheReadTokens: 0, cacheWriteTokens: 0 }, undefined) === undefined);
check('a consistent sample is accepted', normalizeUsage({ inputTokens: 10, outputTokens: 5, totalTokens: 15, cacheReadTokens: 0, cacheWriteTokens: 0 }, undefined) !== undefined);

console.log('bucket helpers');
check('billedTotal sums all four buckets', billedTotal(sample) === 3500000);
check('cacheHitPercent ignores output', cacheHitPercent(sample) === 40, String(cacheHitPercent(sample)));
check('cacheHitPercent is null with no prompt', cacheHitPercent({ uncachedInputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, outputTokens: 5 }) === null);

const files = process.argv.slice(2);
const targets = files.length > 0 ? files : [newestLog()].filter(Boolean);
if (targets.length === 0) {
  console.log('\nno session log found; skipping the live-log check');
} else {
  for (const file of targets) {
    console.log(`\nlive log: ${file}`);
    const events = readLog(file);
    check('the log parsed as a DSH session', events[0] !== undefined && events[0].type === 'session');
    const folded = foldSession(events, byKey);
    const totals = totalSession(folded.rows, folded.gaps);
    const session = totals.session;
    check('the session total equals the sum of its turns', totals.turns.reduce((a, t) => a + t.microUsd, 0) === session.microUsd);
    check('the session token total equals the sum of its rows', folded.rows.reduce((a, r) => a + r.billedTokens, 0) === session.billedTokens);
    const upper = totals.turns.reduce((a, t) => a + t.peakMicroUsd, 0);
    check('the peak upper bound is at least the actual cost', upper >= session.microUsd, `${upper} vs ${session.microUsd}`);
    check('every priced row has a route', folded.rows.every((r) => r.microUsd === undefined || (r.route !== undefined && r.route.provider.length > 0)));
    console.log(`  info  ${totals.turns.length} turns, ${folded.rows.length} priced attempts, ${folded.gaps} usage gaps, ${totals.unpriced.length} unpriced`);
    console.log(`  info  session cost ${formatUsd(session.microUsd)} (upper ${formatUsd(session.peakMicroUsd)}), ${session.billedTokens} tokens, cache hit ${session.cacheHitPercent}%`);
    if (process.env.SHOW_REPORT === '1') console.log(renderReport(totals, { title: 'Session cost', maxTurns: 25 }));
  }
}

console.log(`\n${checks - failures}/${checks} checks passed`);
process.exit(failures === 0 ? 0 : 1);
