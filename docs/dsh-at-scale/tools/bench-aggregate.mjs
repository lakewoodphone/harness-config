/**
 * Measure the AGGREGATE synchronous main-thread cost of the real per-event path
 * over a whole real session log, and the same for one real projection checkpoint.
 *
 * Measured: snapshotJsonValue (dsh-util-values), deepFreeze, structuredClone,
 * JSON.stringify — using the engine's own exported functions.
 * Inferred (not measured, no export): validateSessionEventData's traversal,
 * the zod viewSchema.parse inside dsh-session-projection drive(), and each
 * subscriber's handler body.
 */
import { readFile } from "node:fs/promises";
import { zstdDecompressSync } from "node:zlib";
import { pathToFileURL } from "node:url";
import path from "node:path";
import os from "node:os";

const NM = path.join(os.homedir(), ".dsh", "engine", "node_modules", "@deepseek-ai");
const mod = (p) => import(pathToFileURL(path.join(NM, p)).href);
const { snapshotJsonValue, deepFreeze } = await mod("dsh-util-values/lib/index.js");

const ZSTD_MAGIC = 4247762216;
function scanZstdFrames(buffer) {
  const frames = [];
  let offset = 0;
  while (offset < buffer.length) {
    if (buffer.length - offset < 4) return frames;
    if (buffer.readUInt32LE(offset) !== ZSTD_MAGIC) return frames;
    offset += 4;
    const d = buffer.readUInt8(offset); offset += 1;
    const contentSizeFlag = d >>> 6;
    const singleSegment = (d & 32) !== 0;
    const checksum = (d & 4) !== 0;
    const dictionaryFlag = d & 3;
    offset += (singleSegment ? 0 : 1) + (dictionaryFlag === 3 ? 4 : dictionaryFlag) + (contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag);
    for (;;) {
      if (buffer.length - offset < 3) return frames;
      const bh = buffer.readUIntLE(offset, 3); offset += 3;
      const last = (bh & 1) !== 0, bt = (bh >>> 1) & 3, bs = bh >>> 3;
      offset += bt === 1 ? 1 : bs;
      if (last) break;
    }
    if (checksum) offset += 4;
    frames.push({ start: 0, end: offset });
    frames[frames.length - 1].start = frames.length === 1 ? 0 : frames[frames.length - 2].end;
  }
  return frames;
}
function decode(p, comp) {
  const fs = scanZstdFrames(comp);
  return { buf: Buffer.concat(fs.map((f) => zstdDecompressSync(comp.subarray(f.start, f.end)))), frames: fs.length };
}

const sessionPath = process.argv[2];
const comp = await readFile(sessionPath);
const { buf, frames } = decode(sessionPath, comp);
const lines = buf.toString("utf8").split("\n").filter((l) => l.length > 0).slice(1);

let nSnapshot = 0, nFreeze = 0, nClone = 0, nStringify = 0, bytes = 0;
const perEvent = [];
for (const l of lines) {
  const obj = JSON.parse(l);
  const b = Buffer.byteLength(l);
  bytes += b;
  let t = process.hrtime.bigint();
  const snap = snapshotJsonValue(obj);
  const d1 = Number(process.hrtime.bigint() - t) / 1e6;
  t = process.hrtime.bigint();
  deepFreeze(snap);
  const d2 = Number(process.hrtime.bigint() - t) / 1e6;
  t = process.hrtime.bigint();
  structuredClone(obj);
  const d3 = Number(process.hrtime.bigint() - t) / 1e6;
  t = process.hrtime.bigint();
  JSON.stringify(obj);
  const d4 = Number(process.hrtime.bigint() - t) / 1e6;
  nSnapshot += d1; nFreeze += d2; nClone += d3; nStringify += d4;
  perEvent.push({ b, d1, d2, d3, d4, total: d1 + d2 + d3 + d4 });
}
perEvent.sort((a, b) => b.total - a.total);
const top10 = perEvent.slice(0, 10).reduce((a, e) => a + e.total, 0);
const totalMs = nSnapshot + nFreeze + nClone + nStringify;
console.log(JSON.stringify({
  session: path.basename(path.dirname(sessionPath)),
  events: lines.length,
  zstdFrames: frames,
  eventBytesTotal: bytes,
  totalMB: +(bytes / 1048576).toFixed(2),
  syncMs: {
    snapshotJsonValue: +nSnapshot.toFixed(1),
    deepFreeze: +nFreeze.toFixed(1),
    structuredClone: +nClone.toFixed(1),
    JSONstringify: +nStringify.toFixed(1),
    TOTAL: +totalMs.toFixed(1),
  },
  msPerMBofEvents: +(totalMs / (bytes / 1048576)).toFixed(1),
  worstEvent: { bytes: perEvent[0].b, totalMs: +perEvent[0].total.toFixed(2) },
  top10EventsShareOfTotalPct: +((top10 / totalMs) * 100).toFixed(1),
  syntheticMsPerSecondAt10EventsPerSessionPerSecond: +(totalMs / (bytes / 1048576) * 10 * 3.4 / 1000).toFixed(2),
}, null, 1));

// --- one real projection checkpoint ---
const pcDir = path.join(os.homedir(), ".dsh", "storages", "session_projcache", "sessions");
const record = JSON.parse(await readFile(path.join(pcDir, path.basename(process.argv[3])), "utf8"));
const rows = record.record.rows;
const rowBytes = JSON.stringify(rows).length;
const K = 30;
const med = (fn) => {
  const xs = [];
  for (let i = 0; i < K; i++) { const t = process.hrtime.bigint(); fn(); xs.push(Number(process.hrtime.bigint() - t) / 1e6); }
  xs.sort((a, b) => a - b); return xs[K >> 1];
};
console.log(JSON.stringify({
  checkpoint: {
    session: path.basename(process.argv[3]),
    keys: Object.keys(rows).length,
    compactRowBytes: rowBytes,
    onDiskBytes: Buffer.byteLength(await readFile(path.join(pcDir, path.basename(process.argv[3])))),
    structuredClone_rows_ms: +med(() => structuredClone(rows)).toFixed(3),
    snapshotJsonValue_rows_ms: +med(() => snapshotJsonValue(rows)).toFixed(3),
    JSONstringify_rows_ms: +med(() => JSON.stringify(rows)).toFixed(3),
    snapshotJsonValue_perUnit_clone_ms_INFERRED: +med(() => { for (const k of Object.keys(rows)) structuredClone(rows[k].val); }).toFixed(3),
  }
}, null, 1));
