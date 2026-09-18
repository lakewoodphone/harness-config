// sesslat.mjs — measure tool-call end-to-end latency from a DSH session v3 log.
// The artifact is a concatenated-Zstd-frame JSONL container: each durable batch
// is one checksummed frame. Frame boundaries are found structurally (the same
// walk dsh-session-persistence-jsonl/lib/index.js:scanZstdFrames does), so no
// plaintext line is ever guessed at.
//
// Method: a tool call and its result are separate events; their timestamp delta
// is the visible latency the owner feels. This needs no cooperation from the
// running engine and works on a loaded machine because it is pure log reading.
// Usage: node sesslat.mjs <sessionDir> [toolNameFilter]
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const ZSTD_MAGIC = 0xfd2fb528;
const dir = process.argv[2];
const only = process.argv[3];

function scanFrames(buffer) {
  const frames = [];
  let offset = 0;
  while (offset < buffer.length) {
    if (buffer.length - offset < 4) break;
    if (buffer.readUInt32LE(offset) !== ZSTD_MAGIC) throw new Error(`bad frame magic at ${offset}`);
    const start = offset;
    offset += 4;
    const descriptor = buffer.readUInt8(offset); offset += 1;
    const contentSizeFlag = descriptor >>> 6;
    const singleSegment = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictionaryFlag = descriptor & 3;
    const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
    offset += (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
    for (;;) {
      const blockHeader = buffer.readUIntLE(offset, 3); offset += 3;
      const lastBlock = (blockHeader & 1) !== 0;
      const blockType = (blockHeader >>> 1) & 3;
      const blockSize = blockHeader >>> 3;
      offset += blockType === 1 ? 1 : blockSize;
      if (lastBlock) break;
    }
    if (checksum) offset += 4;
    frames.push({ start, end: offset });
  }
  return frames;
}

const file = path.join(dir, 'session.v3.jsonl.zstd');
const buf = fs.readFileSync(file);
const frames = scanFrames(buf);
const events = [];
let torn = 0;
for (const f of frames) {
  try {
    const txt = zlib.zstdDecompressSync(buf.subarray(f.start, f.end)).toString('utf8');
    for (const l of txt.split('\n')) {
      if (!l.trim()) continue;
      try { events.push(JSON.parse(l)); } catch { torn++; }
    }
  } catch { torn++; }
}

const kinds = new Map();
for (const e of events) kinds.set(e.type, (kinds.get(e.type) ?? 0) + 1);

const tid = (e) => e.data?.callId ?? e.data?.message?.source?.callId ?? e.callId ?? e.toolCallId ?? e.id;
const tname = (e) => e.data?.name ?? e.name ?? e.toolName;
const ts = (e) => e.time ?? e.timestamp ?? e.ts ?? e.at;

const pending = new Map();
const samples = [];
for (const e of events) {
  const k = String(e.type ?? '');
  const t = ts(e);
  if (t === undefined) continue;
  const id = tid(e);
  if (id === undefined) continue;
  if (/tool.?call/i.test(k) && !/result/i.test(k)) pending.set(id, { t, name: tname(e) ?? '?' });
  else if (/tool.?result/i.test(k)) {
    const p = pending.get(id);
    if (p === undefined) continue;
    pending.delete(id);
    if (only !== undefined && p.name !== only) continue;
    samples.push({ tool: p.name, ms: +(t - p.t).toFixed(1), at: p.t });
  }
}

const byTool = new Map();
for (const s of samples) { const a = byTool.get(s.tool) ?? []; a.push(s.ms); byTool.set(s.tool, a); }
function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
  return { n: s.length, min: s[0], p10: q(0.1), p50: q(0.5), mean: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1), p90: q(0.9), max: s.at(-1) };
}
const out = {
  file, bytes: buf.length, frames: frames.length, events: events.length, unparsed: torn,
  kinds: [...kinds.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20),
  tools: {},
};
for (const [tool, xs] of [...byTool].sort((a, b) => b[1].length - a[1].length)) out.tools[tool] = stats(xs);
console.log(JSON.stringify(out, null, 1));
const dest = path.join('C:\\Users\\ezabz\\code\\_dsh-scale\\bench', `sesslat-${path.basename(dir).slice(0, 12)}.json`);
fs.writeFileSync(dest, JSON.stringify({ ...out, samples }, null, 2));
console.error('wrote ' + dest);
