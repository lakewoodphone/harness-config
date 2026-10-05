/**
 * Measure the SYNCHRONOUS main-thread work the DSH engine performs per session
 * event, using the engine's OWN exported functions and REAL session-log events
 * taken from this machine's ~/.dsh/sessions.
 *
 * READ-ONLY w.r.t. the engine: imports modules, reads a session log, writes
 * nothing outside this scratch dir. One process. No ports, no engine contact.
 *
 * What is MEASURED here:
 *   JSON.parse(line)                 -> read/replay cost of one durable event row
 *   snapshotJsonValue(obj)           -> dsh-util-values: validate+detach the payload
 *   deepFreeze(snapshot)             -> dsh-util-values: recursive freeze of the event
 *   structuredClone(obj)             -> what JsonlSessionHandle.enqueueLive does per event
 *   JSON.stringify(encode(ev))       -> what eventLine() does per event in a batch
 *   zstdCompress async (threadpool)  -> what compressZstdFrame() ACTUALLY does per batch
 *   zstdCompressSync                 -> COUNTERFACTUAL: what it would cost on the loop
 */
import { readFile } from "node:fs/promises";
import { zstdCompress, zstdCompressSync, zstdDecompressSync, constants } from "node:zlib";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";
import path from "node:path";
import os from "node:os";

const zstdCompressAsync = promisify(zstdCompress);
const CHECKSUM_OPTIONS = { params: { [constants.ZSTD_c_checksumFlag]: 1 } };
const NM = path.join(os.homedir(), ".dsh", "engine", "node_modules", "@deepseek-ai");
const mod = (p) => import(pathToFileURL(path.join(NM, p)).href);
const { snapshotJsonValue, deepFreeze } = await mod("dsh-util-values/lib/index.js");
const { sessionFormatCatalog } = await mod("dsh-session-format-catalog/lib/index.js");

// scanZstdFrames: logic copied verbatim from
// node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js:1300-1363
// (concatenated independent frames; Node's own one-shot decoder stops after one).
const ZSTD_MAGIC = 4247762216;
function scanZstdFrames(buffer, maxFrames = Number.POSITIVE_INFINITY) {
  const frames = [];
  let offset = 0;
  while (offset < buffer.length) {
    const start = offset;
    if (buffer.length - offset < 4) return { frames, tornStart: start };
    if (buffer.readUInt32LE(offset) !== ZSTD_MAGIC) throw new Error(`invalid frame magic at ${offset}`);
    offset += 4;
    if (offset === buffer.length) return { frames, tornStart: start };
    const descriptor = buffer.readUInt8(offset);
    offset += 1;
    const contentSizeFlag = descriptor >>> 6;
    const singleSegment = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictionaryFlag = descriptor & 3;
    const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
    offset += (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
    for (;;) {
      if (buffer.length - offset < 3) return { frames, tornStart: start };
      const blockHeader = buffer.readUIntLE(offset, 3);
      offset += 3;
      const lastBlock = (blockHeader & 1) !== 0;
      const blockType = (blockHeader >>> 1) & 3;
      const blockSize = blockHeader >>> 3;
      offset += blockType === 1 ? 1 : blockSize;
      if (lastBlock) break;
    }
    if (checksum) offset += 4;
    frames.push({ start, end: offset });
    if (frames.length === maxFrames) return { frames };
  }
  return { frames };
}

function decodeZstdFileSync(p, comp) {
  const { frames, tornStart } = scanZstdFrames(comp);
  const parts = frames.map((f) => zstdDecompressSync(comp.subarray(f.start, f.end)));
  return { buf: Buffer.concat(parts), frameCount: frames.length, tornStart };
}

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
function timeMedian(fn, k) {
  const out = [];
  for (let i = 0; i < k; i++) {
    const t0 = process.hrtime.bigint();
    fn();
    out.push(Number(process.hrtime.bigint() - t0) / 1e6);
  }
  return median(out);
}
async function timeMedianAsync(fn, k) {
  const out = [];
  for (let i = 0; i < k; i++) {
    const t0 = process.hrtime.bigint();
    await fn();
    out.push(Number(process.hrtime.bigint() - t0) / 1e6);
  }
  return median(out);
}

const sessionPath = process.argv[2];
const comp = await readFile(sessionPath);
const { buf: raw, frameCount, tornStart } = decodeZstdFileSync(sessionPath, comp);
const lines = raw.toString("utf8").split("\n").filter((l) => l.length > 0);
const header = lines[0];
const eventLines = lines.slice(1);
const sizes = eventLines.map((l) => Buffer.byteLength(l)).sort((a, b) => a - b);
const q = (p) => sizes[Math.min(sizes.length - 1, Math.floor(p * sizes.length))];

console.log(JSON.stringify({
  session: path.basename(path.dirname(sessionPath)),
  compressedBytes: comp.length,
  plaintextBytes: raw.length,
  zstdFrameCount: frameCount,
  tornStart: tornStart ?? null,
  eventCount: eventLines.length,
  eventsPerFrame: +(eventLines.length / frameCount).toFixed(2),
  eventBytes: {
    p50: q(0.5), p90: q(0.9), p99: q(0.99),
    max: sizes[sizes.length - 1],
    mean: Math.round(sizes.reduce((a, b) => a + b, 0) / sizes.length),
    totalMB: +(sizes.reduce((a, b) => a + b, 0) / 1048576).toFixed(2),
  },
  maxEventShareOfLogPct: +((sizes[sizes.length - 1] / sizes.reduce((a, b) => a + b, 0)) * 100).toFixed(2),
  headerBytes: Buffer.byteLength(header),
}, null, 1));

// pick the largest event, the p50 event, and the largest tool/result event
let maxLine = "", maxLen = -1, medLine = eventLines[0], medErr = Infinity;
let maxTool = "", maxToolLen = -1;
for (const l of eventLines) {
  const n = Buffer.byteLength(l);
  if (n > maxLen) { maxLen = n; maxLine = l; }
  if (Math.abs(n - q(0.5)) < medErr) { medErr = Math.abs(n - q(0.5)); medLine = l; }
  if (l.includes('"tool/result"') && l.includes('"toolCallId"') && n > maxToolLen) { maxToolLen = n; maxTool = l; }
}

const cases = [
  ["max-event", maxLine],
  ["p50-event", medLine],
  ["max-tool-result", maxTool || maxLine],
];

// --- structural stats: what one zstd frame holds (= one durable append batch) ---
{
  const { frames } = scanZstdFrames(comp);
  const frameSizes = frames.map((f) => f.end - f.start);
  const bucket = { "1": 0, "2": 0, "3-5": 0, "6-20": 0, "21+": 0 };
  // decode each frame, count newlines -> events per frame
  let perFrame = [];
  for (const f of frames) {
    const t = zstdDecompressSync(comp.subarray(f.start, f.end));
    let n = 0;
    for (const b of t) if (b === 10) n++;
    if (t.length > 0 && t[t.length - 1] !== 10) n++;
    perFrame.push(n);
  }
  for (const n of perFrame) {
    if (n === 1) bucket["1"]++;
    else if (n === 2) bucket["2"]++;
    else if (n <= 5) bucket["3-5"]++;
    else if (n <= 20) bucket["6-20"]++;
    else bucket["21+"]++;
  }
  const s = [...frameSizes].sort((a, b) => a - b);
  console.log("\nframeStats=" + JSON.stringify({
    frames: frames.length,
    eventsPerFrame_p50: [...perFrame].sort((a, b) => a - b)[perFrame.length >> 1],
    eventsPerFrame_mean: +(perFrame.reduce((a, b) => a + b, 0) / perFrame.length).toFixed(2),
    maxEventsInOneFrame: Math.max(...perFrame),
    eventsPerFrameHistogram: bucket,
    frameBytes_p50: s[s.length >> 1],
    frameBytes_p90: s[Math.floor(0.9 * s.length)],
    frameBytes_max: s[s.length - 1],
  }));

  // event type mix by bytes
  const byType = new Map();
  for (const l of eventLines) {
    const t = (l.match(/^\{"(?:type|v)":"([^"]+)"/) || [])[1] || (l.match(/"type":"([^"]+)"/) || [])[1] || "?";
    const e = byType.get(t) ?? { n: 0, bytes: 0 };
    e.n++; e.bytes += Buffer.byteLength(l);
    byType.set(t, e);
  }
  const tot = [...byType.values()].reduce((a, b) => a + b.bytes, 0);
  const rows = [...byType.entries()].sort((a, b) => b[1].bytes - a[1].bytes).slice(0, 8)
    .map(([t, e]) => `${t}: n=${e.n} bytes=${(e.bytes / 1048576).toFixed(2)}MB share=${((e.bytes / tot) * 100).toFixed(1)}%`);
  console.log("eventTypeMixByBytes:\n  " + rows.join("\n  "));
}

if (process.env.STATS_ONLY === "1") process.exit(0);

console.log("\ncase,bytes,encoding_used,parse_ms,snapshotJsonValue_ms,deepFreeze_ms,structuredClone_ms,JSON.stringify(encoded)_ms,zstd_async_ms,zstd_sync_COUNTERFACTUAL_ms");
for (const [name, line] of cases) {
  const bytes = Buffer.byteLength(line);
  const obj = JSON.parse(line);
  let encoded = obj, enc = "identity";
  try {
    const e = sessionFormatCatalog.encodeCurrentEvent(obj);
    if (e !== undefined) { encoded = e; enc = "encodeCurrentEvent"; }
  } catch (err) { enc = "identity(" + err.constructor.name + ")"; }
  const k = bytes > 500000 ? 12 : 40;
  const parseMs = timeMedian(() => JSON.parse(line), k);
  const snapMs = timeMedian(() => snapshotJsonValue(obj), k);
  const freezeMs = timeMedian(() => deepFreeze(snapshotJsonValue(obj)), k);
  const cloneMs = timeMedian(() => structuredClone(obj), k);
  const strMs = timeMedian(() => JSON.stringify(encoded), k);
  const buf = Buffer.from(line + "\n", "utf8");
  const zAsync = await timeMedianAsync(() => zstdCompressAsync(buf, CHECKSUM_OPTIONS), k);
  const zSync = timeMedian(() => zstdCompressSync(buf, CHECKSUM_OPTIONS), k);
  console.log([name, bytes, enc, parseMs.toFixed(3), snapMs.toFixed(3), freezeMs.toFixed(3), cloneMs.toFixed(3), strMs.toFixed(3), zAsync.toFixed(3), zSync.toFixed(3)].join(","));
}

// --- batch composition: what ONE 200 ms drain window looks like under load ---
// Each live session coalesces up to 200 ms of its own events into one batch
// (index.js:186-192). With 12 concurrent agent loops, the engine's own numbers
// (11-13 loops) are used to state the aggregate. Measure 12x the p90 event.
{
  const p90 = eventLines.slice().sort((a, b) => Buffer.byteLength(a) - Buffer.byteLength(b))[Math.floor(0.9 * eventLines.length)];
  const one = Buffer.byteLength(p90);
  const batch12 = Buffer.alloc(one * 12, 0x20);
  const t = timeMedian(() => zstdCompressSync(batch12, CHECKSUM_OPTIONS), 6);
  const ta = await timeMedianAsync(() => zstdCompressAsync(batch12, CHECKSUM_OPTIONS), 6);
  console.log(`\nBATCH p90-event x12 = ${batch12.length} bytes: zstd_sync=${t.toFixed(2)}ms zstd_async=${ta.toFixed(2)}ms`);
}
