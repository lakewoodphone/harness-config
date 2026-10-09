#!/usr/bin/env node
/**
 * sessions — read ANY DSH session on ANY machine, in one command.
 *
 * WHY THIS EXISTS
 *
 * "Pull up the session I just had on my phone" has failed repeatedly, and it
 * failed for boring, fixable reasons. Each one is a design decision below:
 *
 *   1. THE STORE IS NOT ONE PLACE. Sessions live in
 *      `$DSH_HOME/sessions/<workspace-slug>/<id>/session.v*.*.jsonl.zstd`
 *      AND in `$DSH_HOME/sessions-archive/<slug>/<id>/` once
 *      `session-corpus.mjs archive` has moved older ones out of the live tree.
 *      A reader that knows only the live tree reports "no such session" for a
 *      session that exists. This tool reads both.
 *   2. THE FILE IS NOT ONE ZSTD STREAM. It is one independent frame per appended
 *      event (often thousands of frames). A single `zstdDecompressSync(buffer)`
 *      or Python `stream_reader` stops at the first frame and returns a 200-byte
 *      header — the session looks empty. This tool splits on the zstd magic and
 *      decodes every frame, widening the window when a magic sequence occurs by
 *      chance inside compressed data.
 *   3. THE SESSION MAY BE ON ANOTHER MACHINE, and that machine may not have a
 *      usable zstd binding: measured 2026-10-09, `secratary` runs node v20
 *      (`zlib.zstdDecompressSync` is undefined below v22.15) and a Python with
 *      no `zstandard` module. So decoding is done HERE, never there: the tool
 *      transfers the compressed file and decodes locally. `zstd` is never a
 *      remote dependency.
 *   4. A BINARY `cat` THROUGH POWERSHELL CORRUPTS BYTES. `pwsh` decodes a
 *      native command's stdout to text. Any pipeline that fetches a session
 *      through the shell can silently mangle it. Node's own `spawn` captures
 *      raw Buffers, so the whole fetch/decoder path lives in this file.
 *   5. GUI CHATS AND SUBAGENTS SHARE THE STORE. The owner means the chat he
 *      actually had; a fleet of subagents is normal and dominates by count.
 *      `list` hides subagents by default and says so.
 *   6. A TRANSCRIPT READ CAN POISON A CONTEXT. A long session is mostly
 *      runtime-context snapshots, skill catalogs and tool noise. Default output
 *      is the human conversation only; `--tools`/`--reasoning`/`--all-user`
 *      opt into the rest.
 *   7. EVERY READING CARRIES ITS SOURCE. Host, path, file mtime, size, event
 *      count, frames decoded, frames that failed, and the age of the cached
 *      inventory all print with the transcript. An empty result is reported as
 *      a refusal with the reason, never as "nothing there".
 *
 * USAGE
 *   node scripts/sessions.mjs doctor
 *   node scripts/sessions.mjs nodes
 *   node scripts/sessions.mjs list [--host H] [--all] [--since 7d] [--limit 30]
 *                                   [--project SUB] [--sub] [--refresh] [--json]
 *   node scripts/sessions.mjs find <words...> [--host H] [--all] [--since 30d]
 *                                   [--limit 10] [--full] [--json]
 *   node scripts/sessions.mjs show <id|latest> [--host H] [--all] [--user|--turn N]
 *                                   [--tools] [--reasoning] [--all-user]
 *                                   [--max-chars N] [--json] [--out FILE]
 *   node scripts/sessions.mjs grep <regex> <id|latest> [--host H] [--tools]
 *   node scripts/sessions.mjs resolve <id|latest> [--all] [--json]
 *
 * <id> may be a full id, a unique prefix, a substring, `latest`, `latest@host`,
 * `host:id`, or the full `session-<uuid>` directory name.
 *
 * CONFIG  ~/.dsh/session-nodes.json   {"nodes":{"secratary":"secratary-ts"}}
 *         (a node maps to an ssh alias; `local` is always present and needs none)
 *         `--host <ssh-alias-or-node>` always works and overrides the file.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { spawn } from 'node:child_process';

// ---------------------------------------------------------------------------
// constants and provenance
// ---------------------------------------------------------------------------

const SESSION_FILE_RE = /^session\.v(\d+)\.jsonl\.zstd$/;
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const INDEX_PATH = path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'session-index.json');
const NODES_PATH = path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'session-nodes.json');
const INDEX_TTL_MS = 5 * 60 * 1000;
/**
 * An id -> file mapping is stable, so resolution may use a much older
 * inventory than a "what is newest" listing may. Measured 2026-10-09: `ssh
 * secratary-ts hostname` costs 1.4 s on a good attempt and 11.0 s on a bad one
 * (Tailscale jitter), so re-inventorying the fleet to resolve an id we have
 * already seen is several seconds of pure waste. A miss forces a refresh, so the
 * only cost of a stale entry is one extra round-trip on a session that moved.
 */
const RESOLVE_TTL_MS = 6 * 60 * 60 * 1000;
const SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15',
  '-o', 'ServerAliveCountMax=2', '-o', 'LogLevel=ERROR'];
/** A session file larger than this is refused rather than silently truncated. */
const MAX_TRANSFER_BYTES = 512 * 1024 * 1024;

const DEFAULT_NODES = {
  secratary: 'secratary-ts',
  'zabz-tech': 'zabz-tech-ts',
  'zabz-tech-linux': 'linux-pc-ts',
  'mac-mini': 'mac-mini-ts',
  'zabz-yoga': 'zabz-yoga-ts',
};

const LOCAL_HOSTNAME = String(os.hostname() || 'local').toLowerCase();
const LOCAL_NODE = 'local';

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

const nowIso = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
const ms = (n) => (n < 1000 ? `${n} ms` : `${(n / 1000).toFixed(1)} s`);
const kb = (n) => (n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / 1048576).toFixed(1)} MB`);
const ageStr = (iso) => {
  if (!iso) return 'unknown';
  const s = Math.round((Date.now() - Date.parse(iso)) / 1000);
  if (!Number.isFinite(s)) return 'unknown';
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${(s / 3600).toFixed(1)}h ago`;
  return `${(s / 86400).toFixed(1)}d ago`;
};
const tsStr = (msEpoch) => (msEpoch ? new Date(msEpoch).toISOString().replace('T', ' ').slice(0, 16) + 'Z' : '?');

/** `7d`, `36h`, `90m`, `45s`, `2026-10-01` -> epoch ms. */
function parseSince(text) {
  if (!text) return null;
  const s = String(text).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return Date.parse(s + 'T00:00:00Z');
  const m = /^(\d+(?:\.\d+)?)([dhms])$/.exec(s);
  if (!m) return null;
  const mult = { d: 86400000, h: 3600000, m: 60000, s: 1000 }[m[2]];
  return Date.now() - Number(m[1]) * mult;
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) out[key] = true;
      else { out[key] = next; i++; }
    } else out._.push(a);
  }
  return out;
}

/** POSIX single-quote a path for the remote shell. */
const shq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;

/** Run a program, capture raw bytes. Never goes through a shell, so bytes survive. */
function run(cmd, args, { input = null, timeoutMs = 20000 } = {}) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(cmd, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (error) {
      resolve({ code: -1, stdout: Buffer.alloc(0), stderr: Buffer.from(String(error.message)), timedOut: false });
      return;
    }
    const out = [], err = [];
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; try { child.kill('SIGKILL'); } catch { /* gone */ } }, timeoutMs);
    child.stdout.on('data', (d) => out.push(d));
    child.stderr.on('data', (d) => err.push(d));
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ code: -1, stdout: Buffer.concat(out), stderr: Buffer.concat([...err, Buffer.from(String(error.message))]), timedOut });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, stdout: Buffer.concat(out), stderr: Buffer.concat(err), timedOut });
    });
    if (input != null) child.stdin.end(input); else child.stdin.end();
  });
}

const isLocalHost = (host) => host === LOCAL_NODE || host === LOCAL_HOSTNAME || host === 'localhost';

// ---------------------------------------------------------------------------
// node configuration
// ---------------------------------------------------------------------------

function loadNodes() {
  const nodes = { ...DEFAULT_NODES };
  try {
    if (fs.existsSync(NODES_PATH)) {
      const doc = JSON.parse(fs.readFileSync(NODES_PATH, 'utf8'));
      const extra = doc.nodes || doc;
      for (const [name, target] of Object.entries(extra)) {
        if (typeof target === 'string') nodes[name] = target;
      }
    }
  } catch { /* a broken config file must not break reading */ }
  // The machine we are standing on is never reached over ssh — that would be a
  // self-connection that burns 8 s and reports a misleading "unreachable".
  for (const [name, alias] of Object.entries(nodes)) {
    if (name.toLowerCase() === LOCAL_HOSTNAME) delete nodes[name];
    void alias;
  }
  return nodes;
}

const NODES = loadNodes();

// ---------------------------------------------------------------------------
// zstd: decode EVERY frame
// ---------------------------------------------------------------------------

let ZSTD_IMPL = null;
function zstdImpl() {
  if (ZSTD_IMPL) return ZSTD_IMPL;
  if (typeof zlib.zstdDecompressSync === 'function') ZSTD_IMPL = 'node-zlib';
  else ZSTD_IMPL = 'none';
  return ZSTD_IMPL;
}

/**
 * Split on the zstd magic and decode each frame independently.
 *
 * Two details are load-bearing and were each paid for once:
 *   * the magic can occur by chance inside compressed data, so a tight window
 *     is tried first and widened on failure (up to 6 candidate boundaries);
 *   * a frame that still will not decode is COUNTED, not swallowed — a partially
 *     decoded session must announce itself, because the alternative is a
 *     confident transcript with a hole in it.
 */
function decodeFrames(buf) {
  const offsets = [];
  let i = 0;
  while ((i = buf.indexOf(ZSTD_MAGIC, i)) !== -1) { offsets.push(i); i += 4; }
  if (offsets.length === 0) {
    return { text: buf.toString('utf8'), frames: 0, failed: 0, plain: true };
  }
  offsets.push(buf.length);
  const parts = [];
  let failed = 0;
  for (let k = 0; k < offsets.length - 1; k++) {
    let ok = false;
    for (let j = k + 1; j < Math.min(k + 6, offsets.length); j++) {
      try {
        parts.push(zlib.zstdDecompressSync(buf.subarray(offsets[k], offsets[j])));
        k = j - 1;
        ok = true;
        break;
      } catch { /* widen the window */ }
    }
    if (!ok) failed++;
  }
  return { text: Buffer.concat(parts).toString('utf8'), frames: offsets.length - 1, failed, plain: false };
}

function parseEvents(text) {
  const events = [];
  let bad = 0;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch { bad++; }
  }
  return { events, bad };
}

// ---------------------------------------------------------------------------
// remote + local access
// ---------------------------------------------------------------------------

/** The inventory program, run ON the target host. Node is guaranteed there (DSH
 *  runs on it); it only stats files, so it needs no zstd and works on old node. */
const INVENTORY_SCRIPT = `
const fs=require('fs'),path=require('path'),os=require('os');
const home=process.env.DSH_HOME||path.join(os.homedir(),'.dsh');
const roots=[['live',path.join(home,'sessions')],['archive',path.join(home,'sessions-archive')]];
const pcdir=path.join(home,'storages','session_projcache','sessions');
const out=[];
function val(rows,k){const r=rows[k];if(r&&typeof r==='object'&&'val' in r)return r.val;return undefined;}
for(const [kind,root] of roots){
  let wss;try{wss=fs.readdirSync(root)}catch(e){continue;}
  for(const ws of wss){
    const wsdir=path.join(root,ws);let ents;
    try{ents=fs.readdirSync(wsdir)}catch(e){continue;}
    for(const dir of ents){
      const sdir=path.join(wsdir,dir);let files;
      try{files=fs.readdirSync(sdir)}catch(e){continue;}
      for(const f of files){
        if(!/^session\\.v\\d+\\.jsonl\\.zstd$/.test(f))continue;
        let st;try{st=fs.statSync(path.join(sdir,f))}catch(e){continue;}
        const sid=dir.replace(/^session-/,'');
        const rec={kind,ws,dir,sid,file:path.join(sdir,f),mtime:Math.round(st.mtimeMs),bytes:st.size};
        for(const cand of ['session-'+sid+'.json',sid+'.json']){
          const p=path.join(pcdir,cand);
          try{
            const j=JSON.parse(fs.readFileSync(p,'utf8'));
            const r=(j.record)||{};const rows=r.rows||{};
            rec.title=val(rows,'title')||null;
            rec.preset=val(rows,'agentPreset')||null;
            const stats=val(rows,'sessionStats');
            if(stats&&typeof stats==='object')rec.turns=stats.turns||null;
            if(r.identity){rec.cwd=r.identity.cwd||null;rec.createdAt=r.identity.createdAt||null;}
            break;
          }catch(e){}
        }
        out.push(rec);
      }
    }
  }
}
process.stdout.write(JSON.stringify({host:os.hostname(),count:out.length,sessions:out}));
`;

/** Fetch an inventory from one node (local = in-process, remote = one ssh call). */
async function inventory(host, { timeoutMs = 25000 } = {}) {
  if (isLocalHost(host)) {
    const r = await run(process.execPath, ['-e', INVENTORY_SCRIPT], { timeoutMs: 60000 });
    if (r.code !== 0) {
      return { host: LOCAL_NODE, ok: false, error: String(r.stderr).trim().slice(0, 300) || `node exit ${r.code}`, sessions: [] };
    }
    try { const j = JSON.parse(String(r.stdout)); return { host: LOCAL_NODE, ok: true, hostname: j.host, sessions: j.sessions }; }
    catch (e) { return { host: LOCAL_NODE, ok: false, error: 'inventory returned unparseable JSON: ' + e.message, sessions: [] }; }
  }
  const alias = NODES[host] || host;
  let r = await run('ssh', [...SSH_OPTS, alias, 'node'], { input: INVENTORY_SCRIPT, timeoutMs });
  // `node` is not always on PATH for a NON-INTERACTIVE ssh session. Measured
  // 2026-10-09: the mac mini's zsh answers `command not found: node` while DSH
  // runs there happily, because the PATH is set in an interactive rc file. Only
  // when the direct attempt fails does this pay a second round-trip to search
  // the usual install locations.
  if (r.code !== 0 && !r.timedOut && /command not found|not recognized|No such file/i.test(String(r.stderr))) {
    const finder = 'for c in /usr/local/bin/node /opt/homebrew/bin/node /usr/bin/node '
      + '"$HOME"/node/bin/node "$HOME"/.local/bin/node "$HOME"/.nvm/versions/node/*/bin/node '
      + '"$HOME"/.volta/bin/node /snap/bin/node; do [ -x "$c" ] && exec "$c"; done; exit 127';
    const r2 = await run('ssh', [...SSH_OPTS, alias, `sh -c ${shq(finder)}`], { input: INVENTORY_SCRIPT, timeoutMs });
    if (r2.code === 0 && r2.stdout.length > 0) r = r2;
    else r = { ...r, stderr: Buffer.concat([r.stderr, Buffer.from(`\n[retried with an explicit node search: ${String(r2.stderr).trim().slice(0, 200) || 'exit ' + r2.code}]`)]) };
  }
  if (r.timedOut) return { host, ok: false, error: `ssh ${alias}: timed out after ${ms(timeoutMs)}`, sessions: [] };
  if (r.code !== 0) return { host, ok: false, error: `ssh ${alias}: ${String(r.stderr).trim().slice(0, 300) || `exit ${r.code}`}`, sessions: [] };
  try {
    const j = JSON.parse(String(r.stdout));
    // A node whose hostname is us is us: never read ourselves through ssh twice.
    if (String(j.host).toLowerCase() === LOCAL_HOSTNAME) {
      return { host: LOCAL_NODE, ok: true, hostname: j.host, sessions: j.sessions, selfAlias: alias };
    }
    return { host, ok: true, hostname: j.host, alias, sessions: j.sessions };
  } catch (e) {
    return { host, ok: false, error: `$?=0 but unparseable inventory: ${e.message}`, sessions: [] };
  }
}

/**
 * Host-level failures cost one round-trip to learn and must never be paid again
 * in the same run: a Windows node whose ssh shell has no `head` used to fail 113
 * times out of 200 candidates, which is most of a four-minute search spent
 * rediscovering one fact about one machine.
 */
const HOST_FAILURE = new Map();

/**
 * Errors that mean "the network said no this time", not "this machine cannot do
 * it". Measured 2026-10-09: 16 concurrent ssh sessions to one host made 103 of
 * 107 reads fail with `connect to host ... port 22: Connection timed out` —
 * a transient, load-induced refusal. Retrying and NOT memoizing those is the
 * difference between a search that works and one that reports 96% missing data.
 */
const TRANSIENT = /timed out|Connection (?:timed out|refused|reset|closed)|Broken pipe|kex_exchange|banner exchange|Resource temporarily unavailable|No route to host/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Run a node program on a remote host, script over STDIN.
 *
 * Node is the only interpreter guaranteed on every node (DSH runs on all of
 * them), the script arrives on stdin so NOTHING needs shell quoting, and node
 * writes raw bytes — which matters because a Windows node's ssh shell is
 * PowerShell (`cat`/`head` do not exist there) and a text-mode shell can mangle
 * binary output.
 */
async function remoteNode(host, script, { timeoutMs = 120000, memoize = true } = {}) {
  const alias = NODES[host] || host;
  const known = HOST_FAILURE.get(host);
  if (known) throw new Error(`host ${host} already failed in this run (${known})`);
  let last = '';
  for (let attempt = 0; attempt < 3; attempt++) {
    const r = await run('ssh', [...SSH_OPTS, alias, 'node'], { input: script, timeoutMs });
    if (r.code === 0 && r.stdout.length > 0) return r;
    last = r.timedOut
      ? `timed out after ${ms(timeoutMs)}`
      : (String(r.stderr).trim().replace(/\s+/g, ' ').slice(0, 220) || `exit ${r.code}`);
    if (attempt < 2 && (r.timedOut || TRANSIENT.test(last))) { await sleep(500 * (attempt + 1)); continue; }
    break;
  }
  if (memoize && !TRANSIENT.test(last)) HOST_FAILURE.set(host, last);
  throw new Error(`ssh ${alias}: ${last}`);
}

/** Fetch raw bytes of one session file (all of it, or the first `maxBytes`). */
async function fetchBytes(rec, maxBytes = null) {
  if (rec.host === LOCAL_NODE) {
    const st = fs.statSync(rec.file);
    if (maxBytes && st.size > maxBytes) {
      const fd = fs.openSync(rec.file, 'r');
      const buf = Buffer.alloc(maxBytes);
      const n = fs.readSync(fd, buf, 0, maxBytes, 0);
      fs.closeSync(fd);
      return { buf: buf.subarray(0, n), truncated: true, fileBytes: st.size };
    }
    return { buf: fs.readFileSync(rec.file), truncated: false, fileBytes: st.size };
  }
  if (!maxBytes && rec.bytes > MAX_TRANSFER_BYTES) {
    throw new Error(`session is ${kb(rec.bytes)} — over the ${kb(MAX_TRANSFER_BYTES)} transfer ceiling`);
  }
  const script = 'const fs=require("fs");const b=fs.readFileSync('
    + JSON.stringify(rec.file) + ');process.stdout.write('
    + (maxBytes ? `b.subarray(0,${maxBytes})` : 'b') + ');';
  const r = await remoteNode(rec.host, script);
  if (r.stdout.length === 0) throw new Error(`read 0 bytes from ${rec.host}:${rec.file} — refusing to report an empty session`);
  return { buf: r.stdout, truncated: maxBytes != null, fileBytes: rec.bytes };
}

const SEG = Buffer.from('@@SEG ');

/**
 * Read the head (or the whole) of MANY session files on ONE host in ONE ssh
 * call.
 *
 * This is the fix for the measured failure: one ssh per session meant one
 * connection per session, and a host's sshd/Tailscale path answered 103 of 107
 * of them with a timeout. A framed stream — `@@SEG <i> <len> <size> <err>\n`
 * followed by exactly `len` raw bytes — carries the same data over a single
 * connection and is length-delimited, so a frame can never be found by accident
 * inside compressed data.
 */
async function fetchBatch(host, recs, maxBytes) {
  const out = new Map();
  if (recs.length === 0) return out;
  const jobs = recs.map((r) => [r.file, maxBytes || 0]);
  const script = 'const fs=require("fs");const jobs='
    + JSON.stringify(jobs)
    + ';for(let i=0;i<jobs.length;i++){const f=jobs[i][0];let max=jobs[i][1];'
    + 'try{const st=fs.statSync(f);const len=max?Math.min(max,st.size):st.size;const buf=Buffer.alloc(len);'
    + 'const fd=fs.openSync(f,"r");fs.readSync(fd,buf,0,len,0);fs.closeSync(fd);'
    + 'fs.writeSync(1,Buffer.from("@@SEG "+i+" "+len+" "+st.size+" \\n"));fs.writeSync(1,buf);}'
    + 'catch(e){fs.writeSync(1,Buffer.from("@@SEG "+i+" 0 0 "+String(e.message).replace(/[\\r\\n]+/g," ")+"\\n"));}}';
  const r = await remoteNode(host, script, { timeoutMs: 180000 });
  const buf = r.stdout;
  let pos = 0;
  let frames = 0;
  while (pos < buf.length) {
    if (!buf.subarray(pos, pos + SEG.length).equals(SEG)) {
      const nl = buf.indexOf(0x0a, pos);
      if (nl === -1) break;
      pos = nl + 1;
      continue;
    }
    const nl = buf.indexOf(0x0a, pos);
    if (nl === -1) break;
    const parts = buf.subarray(pos + SEG.length, nl).toString('utf8').split(' ');
    pos = nl + 1;
    const idx = Number(parts[0]);
    const len = Number(parts[1]);
    const size = Number(parts[2]);
    const err = parts.slice(3).join(' ').trim();
    const blob = buf.subarray(pos, pos + len);
    pos += len;
    frames++;
    const rec = recs[idx];
    if (!rec) continue;
    if (err) out.set(rec.id, { error: err });
    else out.set(rec.id, { buf: blob, fileBytes: size, truncated: maxBytes != null && size > len });
  }
  if (frames === 0) throw new Error(`ssh ${host}: the batch read returned no frames for ${recs.length} file(s)`);
  return out;
}

/** Read a full session: bytes -> events, with the decoding accounted for. */
async function readSession(rec) {
  if (!isLocalHost(rec.host) && zstdImpl() === 'none') {
    throw new Error('local node has no zstd decoder (needs node >= 22.15 for zlib.zstdDecompressSync)');
  }
  const { buf, truncated, fileBytes } = await fetchBytes(rec);
  const dec = decodeFrames(buf);
  const { events, bad } = parseEvents(dec.text);
  return { events, bad, frames: dec.frames, failedFrames: dec.failed, bytes: buf.length, fileBytes, truncated };
}

// ---------------------------------------------------------------------------
// the cached inventory across the fleet
// ---------------------------------------------------------------------------

function readIndexCache() {
  try {
    const doc = JSON.parse(fs.readFileSync(INDEX_PATH, 'utf8'));
    if (doc && doc.version === 1 && Array.isArray(doc.nodes)) return doc;
  } catch { /* absent or broken -> rebuild */ }
  return null;
}

function writeIndexCache(doc) {
  try {
    const tmp = INDEX_PATH + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(doc));
    fs.renameSync(tmp, INDEX_PATH);
  } catch { /* a cache that cannot be written is not an error */ }
}

function targetHosts(args) {
  if (typeof args.host === 'string') {
    if (args.host === 'all') return [LOCAL_NODE, ...Object.keys(NODES)];
    return [isLocalHost(args.host) ? LOCAL_NODE : args.host];
  }
  // Default: the whole fleet. The first call pays the ssh round-trips, then the
  // cache makes it instant; a reader that quietly looked at one machine and
  // reported "not found" is the failure this default removes.
  return [LOCAL_NODE, ...Object.keys(NODES)];
}

async function gather(options = {}) {
  const { refresh = false, hosts = null, log = () => {}, maxAgeMs = INDEX_TTL_MS } = options;
  const wanted = hosts || [LOCAL_NODE, ...Object.keys(NODES)];
  const cache = readIndexCache();
  const ageMs = cache ? Date.now() - Date.parse(cache.fetchedAt) : Infinity;
  const usable = cache && !refresh && ageMs < maxAgeMs;
  const cachedByHost = new Map();
  if (usable) for (const n of cache.nodes) cachedByHost.set(n.host, n);

  const need = wanted.filter((h) => !cachedByHost.has(h));
  const results = [];
  for (const h of wanted) if (cachedByHost.has(h)) results.push(cachedByHost.get(h));

  if (need.length > 0) {
    log(`inventory: reading ${need.length} node(s) — ${need.join(', ')}`);
    const t0 = Date.now();
    const fresh = await Promise.all(need.map((h) => inventory(h, { timeoutMs: 25000 })));
    for (const f of fresh) results.push(f);
    log(`inventory: done in ${ms(Date.now() - t0)}`);
    const merged = new Map();
    if (cache) for (const n of cache.nodes) merged.set(n.host, n);
    for (const f of results) merged.set(f.host, f);
    writeIndexCache({ version: 1, fetchedAt: nowIso(), nodes: [...merged.values()] });
  }
  return { nodes: results, fetchedAt: usable ? cache.fetchedAt : nowIso(), cached: usable };
}

function flatten(nodeResults) {
  const rows = [];
  for (const n of nodeResults) {
    if (!n.ok) continue;
    for (const s of n.sessions) {
      const p = String(s.dir || '').split('/').pop();
      rows.push({
        host: n.host,
        hostname: n.hostname || n.host,
        kind: s.kind,
        project: s.ws,
        dir: p,
        id: s.sid,
        file: s.file,
        mtime: s.mtime,
        bytes: s.bytes,
        title: s.title || null,
        preset: s.preset || null,
        cwd: s.cwd || null,
        // Convention (journal L2062): a directory named `session-<uuid>` is a
        // chat the owner had; a bare `<uuid>` directory is a subagent. The
        // transcript header is the authority and `show` reports that instead.
        role: /^session-/.test(p) ? 'main' : 'sub',
      });
    }
  }
  rows.sort((a, b) => b.mtime - a.mtime);
  return rows;
}

function matchId(row, needle) {
  const n = String(needle).replace(/^session-/, '');
  return row.id === n || row.id.startsWith(n) || row.id.includes(n) || row.dir.includes(String(needle));
}

async function resolveOne(idArg, nodeResults, { log = () => {} } = {}) {
  const rows = flatten(nodeResults);
  if (rows.length === 0) return { error: 'no sessions were listed on any node — nothing to resolve against' };
  let host = null;
  let needle = idArg;
  const at = /^([^:@/]+)@([^:@/]+)$/.exec(idArg);
  const colon = /^([a-z0-9._-]+):(.+)$/i.exec(idArg);
  if (at && (at[1] === 'latest' || NODES[at[1]] || at[1] === LOCAL_NODE)) { needle = 'latest'; host = at[2]; }
  else if (colon && (NODES[colon[1]] || colon[1] === LOCAL_NODE)) { host = colon[1]; needle = colon[2]; }
  let pool = rows;
  if (host) pool = rows.filter((r) => r.host === host || r.hostname === host);
  if (needle === 'latest') {
    pool = pool.filter((r) => r.kind === 'live');
    const main = pool.filter((r) => r.role === 'main');
    const pick = (main.length ? main : pool)[0];
    if (!pick) return { error: 'no session found' };
    return { rec: pick, rows };
  }
  const hits = pool.filter((r) => matchId(r, needle));
  if (hits.length === 0) return { error: `no session matching ${JSON.stringify(idArg)}`, rows };
  if (hits.length > 1) log(`note: ${hits.length} sessions match ${JSON.stringify(idArg)} — using the newest (${hits[0].id} on ${hits[0].host})`);
  return { rec: hits[0], rows, ambiguous: hits.length > 1 ? hits.slice(0, 8) : null };
}

// ---------------------------------------------------------------------------
// transcript rendering
// ---------------------------------------------------------------------------

const isNoiseUser = (e) => {
  const d = e.data || {};
  const kind = d.source && d.source.kind;
  if (kind && kind !== 'user') return true;
  const blocks = Array.isArray(d.content) ? d.content : [];
  const text = blocks.filter((b) => b.type === 'text').map((b) => b.text || '').join('\n');
  if (/^Current runtime context\./.test(text)) return true;
  if (/^<system-reminder>/.test(text)) return true;
  if (/^A skill is a reusable set/.test(text)) return true;
  return false;
};

function contentBlocks(msg) {
  if (!msg) return [];
  if (Array.isArray(msg.content)) return msg.content;
  if (typeof msg.content === 'string') return [{ type: 'text', text: msg.content }];
  if (typeof msg.text === 'string') return [{ type: 'text', text: msg.text }];
  return [];
}

const clip = (s, n) => {
  s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n) + `…[+${s.length - n}ch]` : s;
};

function headerOf(events) {
  const h = events.find((e) => e.type === 'session') || {};
  let title = null;
  for (const e of events) if (e.type === 'session/title' && e.data && e.data.title) title = e.data.title;
  return { header: h, title };
}

/**
 * Walk the events and produce renderable rows.
 *
 * `turn` counts human turns (noise excluded), which is what "the turn where he
 * said X" means; a raw event index would be useless to a human.
 */
function renderRows(events, opts) {
  const rows = [];
  let turn = 0;
  for (const e of events) {
    const d = e.data || {};
    switch (e.type) {
      case 'user/message': {
        const noise = isNoiseUser(e);
        if (!noise) turn++;
        if (noise && !opts.allUser) break;
        const text = contentBlocks(d).map((b) => {
          if (b.type === 'text') return b.text || '';
          if (b.type === 'image') return `[image ${b.attachment && b.attachment.name ? b.attachment.name : ''} ${b.attachment && b.attachment.originalDimensions ? b.attachment.originalDimensions.width + 'x' + b.attachment.originalDimensions.height : ''}]`;
          return `[${b.type}]`;
        }).join('\n').trim();
        if (!text) break;
        rows.push({ turn, type: noise ? 'context' : 'user', time: e.time, text: clip(text, opts.maxChars), full: text });
        break;
      }
      case 'assistant/message': {
        const msg = d.message || d;
        const parts = [];
        let toolCalls = 0;
        let reasoning = 0;
        for (const b of contentBlocks(msg)) {
          if (b.type === 'text') parts.push((b.text || '').trim());
          else if (b.type === 'tool-call') {
            toolCalls++;
            if (opts.tools) parts.push(`  → ${b.name} ${clip(b.arguments, opts.toolChars)}`);
          } else if (b.type === 'reasoning') {
            reasoning++;
            if (opts.reasoning) parts.push(`  [reasoning] ${clip(b.text, opts.reasoningChars)}`);
          }
        }
        const text = parts.filter(Boolean).join('\n');
        const notes = [];
        if (toolCalls && !opts.tools) notes.push(`${toolCalls} tool call${toolCalls > 1 ? 's' : ''}`);
        if (reasoning && !opts.reasoning) notes.push(`${reasoning} reasoning block${reasoning > 1 ? 's' : ''}`);
        if (!text && notes.length === 0) break;
        rows.push({
          turn, type: 'assistant', time: e.time,
          text: clip(text + (notes.length ? `\n  (${notes.join(', ')})` : ''), opts.maxChars), full: text,
        });
        break;
      }
      case 'tool/call':
        if (!opts.tools) break;
        rows.push({ turn, type: 'call', time: e.time, text: clip(`${d.name || d.toolName} ${d.arguments}`, opts.toolChars), full: '' });
        break;
      case 'tool/result':
        if (!opts.tools) break;
        rows.push({ turn, type: 'result', time: e.time, text: clip(d.message && d.message.content ? JSON.stringify(d.message.content) : JSON.stringify(d), opts.toolChars), full: '' });
        break;
      case 'deliverables/presented':
        if (!opts.tools) break;
        rows.push({ turn, type: 'present', time: e.time, text: clip(JSON.stringify(d.files || d), 400), full: '' });
        break;
      default: break;
    }
  }
  return rows;
}

function renderTranscript(rec, meta, rows, opts) {
  const lines = [];
  const n = rows.length;
  const width = String(meta.turnCount).length;
  for (const r of rows) {
    const t = r.time ? new Date(r.time).toISOString().slice(11, 19) : '--:--:--';
    const turn = r.type === 'context' ? ' ctx ' : ` t${String(r.turn).padStart(width)}`;
    const label = { user: 'USER', context: '•CTX', assistant: 'ZABZ', call: 'CALL', result: ' rslt', present: 'PRES' }[r.type];
    lines.push(`[${t}]${turn} ${label}  ${r.text}`);
  }
  void n;
  return lines.join('\n');
}

function provenance(rec, info, nodeResults, opts) {
  const nodes = nodeResults.map((n) => (n.ok ? `${n.host}(${n.sessions.length})` : `${n.host}(UNREACHABLE: ${n.error})`)).join('  ');
  const lines = [
    `session   ${rec.id}  [${rec.role === 'main' ? 'GUI chat' : 'subagent by directory convention'}]`,
    `host      ${rec.host}${rec.hostname && rec.hostname !== rec.host ? ` (${rec.hostname})` : ''}   project ${rec.project}/${rec.dir}`,
    `file      ${rec.file}`,
    `source    mtime ${tsStr(rec.mtime)} (${ageStr(new Date(rec.mtime).toISOString())})  size ${kb(rec.bytes)}  kind ${rec.kind}`,
    `title     ${info.title || rec.title || '(none)'}   preset ${info.header.preset || rec.preset || '?'}   cwd ${info.header.cwd || rec.cwd || '?'}`,
    `origin    ${info.header.origin || 'main'}${info.header.parentSession ? `  parent ${info.header.parentSession}` : ''}`,
    `decoded   ${info.events.length} events, ${info.frames} zstd frames, ${info.failedFrames} failed, ${info.bad} unparseable line(s)`,
    `inventory ${ageStr((opts.indexFetchedAt || ''))} — nodes: ${nodes}`,
  ];
  if (info.failedFrames > 0) lines.push(`WARNING   ${info.failedFrames} zstd frame(s) did not decode — this transcript has a gap`);
  if (info.truncated) lines.push(`WARNING   only the first ${kb(info.bytes)} of ${kb(info.fileBytes)} was read`);
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// commands
// ---------------------------------------------------------------------------

async function cmdDoctor() {
  const checks = [];
  const add = (ok, name, detail) => checks.push({ ok, name, detail });

  const impl = zstdImpl();
  add(impl !== 'none', 'local zstd decoder', impl === 'node-zlib' ? `zlib.zstdDecompressSync present (node ${process.version})` : 'MISSING — needs node >= 22.15; nothing can be decoded');

  // Round-trip proof: build a two-frame payload and decode it with our own splitter.
  if (impl !== 'none') {
    try {
      const a = zlib.zstdCompressSync(Buffer.from('{"type":"session","id":"selftest"}\n'));
      const b = zlib.zstdCompressSync(Buffer.from('{"type":"user/message","data":{"text":"hello"}}\n'));
      const d = decodeFrames(Buffer.concat([a, b]));
      const { events } = parseEvents(d.text);
      add(d.frames === 2 && events.length === 2, 'multi-frame decode', `${d.frames} frames, ${events.length} events, ${d.failed} failed`);
    } catch (error) { add(false, 'multi-frame decode', String(error.message)); }
  }

  // The cache's existence is not a capability — being able to WRITE it is. A
  // check that fails on a healthy machine because it has not run yet teaches
  // people to ignore the doctor, so this one tests the actual operation.
  try {
    const probe = INDEX_PATH + '.doctor-probe';
    fs.writeFileSync(probe, 'x');
    fs.unlinkSync(probe);
    add(true, 'index cache writable', INDEX_PATH);
  } catch (error) { add(false, 'index cache writable', `${INDEX_PATH}: ${error.message}`); }
  add(true, 'node config', fs.existsSync(NODES_PATH)
    ? NODES_PATH
    : `no ${NODES_PATH} — built-in defaults in use: ${[LOCAL_NODE, ...Object.keys(NODES)].join(', ')} (write the file to add a machine)`);

  const inv = await gather({ refresh: true, log: () => {} });
  for (const n of inv.nodes) {
    add(n.ok, `node ${n.host}`, n.ok ? `${n.sessions.length} session file(s)${n.hostname ? ` on ${n.hostname}` : ''}` : n.error);
  }

  // End-to-end: resolve the newest live chat and decode its header.
  const rows = flatten(inv.nodes).filter((r) => r.kind === 'live');
  const newest = rows.find((r) => r.role === 'main') || rows[0];
  if (newest) {
    try {
      const info = await readSession(newest);
      const { header } = headerOf(info.events);
      add(info.events.length > 0, 'end-to-end read', `${newest.id}@${newest.host}: ${info.events.length} events, ${info.frames} frames, origin=${header.origin || 'main'}`);
    } catch (error) { add(false, 'end-to-end read', `${newest.id}@${newest.host}: ${error.message}`); }
  } else add(false, 'end-to-end read', 'no live session anywhere to test with');

  for (const c of checks) console.log(`${c.ok ? 'OK  ' : 'FAIL'}  ${c.name.padEnd(22)} ${c.detail}`);
  const failed = checks.filter((c) => !c.ok).length;
  console.log(`\n${failed === 0 ? 'all checks passed' : `${failed} check(s) failed`}`);
  return failed === 0 ? 0 : 1;
}

async function cmdNodes(args) {
  const inv = await gather({ refresh: !!args.refresh, log: (m) => console.error(m) });
  console.log(`local hostname  ${LOCAL_HOSTNAME}`);
  console.log(`index           ${INDEX_PATH}  (fetched ${ageStr(inv.fetchedAt)}, cached=${inv.cached})`);
  console.log(`node config     ${fs.existsSync(NODES_PATH) ? NODES_PATH : 'built-in defaults'}\n`);
  console.log('node        ssh alias           status        sessions  live  archive  newest');
  for (const n of inv.nodes) {
    const live = n.sessions.filter((s) => s.kind === 'live').length;
    const arch = n.sessions.filter((s) => s.kind === 'archive').length;
    const newest = n.sessions.reduce((a, s) => Math.max(a, s.mtime || 0), 0);
    console.log(`${n.host.padEnd(11)} ${String(n.alias || '(local)').padEnd(19)} ${(n.ok ? 'ok' : 'UNREACHABLE').padEnd(13)} ${String(n.sessions.length).padStart(8)}  ${String(live).padStart(4)}  ${String(arch).padStart(7)}  ${tsStr(newest)}`);
    if (!n.ok) console.log(`            └ ${n.error}`);
  }
  return 0;
}

async function cmdList(args) {
  const t0 = Date.now();
  const inv = await gather({ refresh: !!args.refresh, hosts: targetHosts(args), log: (m) => console.error(m) });
  let rows = flatten(inv.nodes);
  const since = parseSince(typeof args.since === 'string' ? args.since : '');
  if (args.since && !since) { console.error(`list: --since ${args.since} is not 7d/36h/90m/2026-10-01`); return 2; }
  if (since) rows = rows.filter((r) => r.mtime >= since);
  if (typeof args.project === 'string') rows = rows.filter((r) => r.project.toLowerCase().includes(args.project.toLowerCase()) || String(r.cwd || '').toLowerCase().includes(args.project.toLowerCase()));
  if (!args.sub) rows = rows.filter((r) => r.role === 'main');
  if (args.kind) rows = rows.filter((r) => r.kind === args.kind);
  const limit = Number(args.limit || 30);
  const shown = rows.slice(0, limit);

  if (args.json) {
    console.log(JSON.stringify({ indexFetchedAt: inv.fetchedAt, total: rows.length, nodes: inv.nodes.map((n) => ({ host: n.host, ok: n.ok, error: n.error || null, sessions: (n.sessions || []).length })), sessions: shown }, null, 2));
    return 0;
  }
  console.log(`# ${rows.length} session(s) matched${args.sub ? ' (including subagents)' : ' (GUI chats only; add --sub for subagents)'} — index ${ageStr(inv.fetchedAt)}${inv.cached ? ' (cached)' : ''}, ${ms(Date.now() - t0)}`);
  for (const n of inv.nodes) if (!n.ok) console.log(`# UNREACHABLE ${n.host}: ${n.error}`);
  if (shown.length === 0) { console.log('# nothing matched — that is a refusal, not evidence the session does not exist: widen --since, drop --project, or add --sub'); return 0; }
  console.log('when              host        kind     role  project                    turns  size      id');
  for (const r of shown) {
    console.log(`${tsStr(r.mtime)}  ${r.host.padEnd(11)} ${r.kind.padEnd(8)} ${r.role.padEnd(5)} ${String(r.project).slice(0, 26).padEnd(26)} ${String(r.turns || '').padStart(5)}  ${kb(r.bytes).padStart(8)}  ${r.id}`);
    if (r.title || r.preset) console.log(`${' '.repeat(18)}${r.title ? `“${clip(r.title, 70)}”` : ''}${r.preset ? `  preset=${r.preset}` : ''}`);
  }
  if (rows.length > shown.length) console.log(`# … ${rows.length - shown.length} more (raise --limit)`);
  return 0;
}

/**
 * Resolve an id, cheapest first: an inventory we already have, then one real
 * inventory if that did not know the id. `latest` must not be answered from a
 * six-hour-old mapping, so it always takes the short TTL.
 */
async function resolveWithCache(args, idArg) {
  const hosts = targetHosts(args);
  const ttl = /latest/.test(idArg) ? INDEX_TTL_MS : RESOLVE_TTL_MS;
  let inv = await gather({ refresh: !!args.refresh, hosts, maxAgeMs: ttl, log: (m) => console.error(m) });
  let res = await resolveOne(idArg, inv.nodes, { log: (m) => console.error(m) });
  if (res.error && inv.cached) {
    inv = await gather({ refresh: true, hosts, log: (m) => console.error(m) });
    res = await resolveOne(idArg, inv.nodes, { log: (m) => console.error(m) });
  }
  return { inv, res };
}

async function cmdShow(args) {
  const t0 = Date.now();
  const idArg = typeof args._[1] === 'string' ? args._[1] : (args.id || 'latest');
  const { inv, res } = await resolveWithCache(args, idArg);
  if (res.error) {
    console.error(`show: ${res.error}`);
    for (const n of inv.nodes) if (!n.ok) console.error(`  unreachable ${n.host}: ${n.error}`);
    return 1;
  }
  const rec = res.rec;
  let info;
  try { info = await readSession(rec); }
  catch (error) { console.error(`show: ${error.message}`); return 1; }
  const h = headerOf(info.events);

  const opts = {
    tools: !!args.tools,
    reasoning: !!args.reasoning,
    allUser: !!args['all-user'],
    maxChars: Number(args['max-chars'] || 3000),
    toolChars: Number(args['tool-chars'] || 400),
    reasoningChars: Number(args['reasoning-chars'] || 300),
  };
  let rows = renderRows(info.events, opts);
  if (args.user) rows = rows.filter((r) => r.type === 'user' && r.turn > 0);
  if (args.turn) {
    const want = Number(args.turn);
    const allTurns = [...new Set(rows.filter((r) => r.turn > 0).map((r) => r.turn))];
    const sel = rows.filter((r) => r.turn === want);
    if (sel.length === 0) {
      console.error(`show: no turn ${want} — this session has ${allTurns.length} human turn(s), numbered ${allTurns.slice(0, 8).join(', ')}${allTurns.length > 8 ? ', …' : ''}`);
      return 1;
    }
    rows = sel;
  }
  if (args.tail) rows = rows.slice(-Number(args.tail));
  const header = provenance(rec, { ...info, ...h }, inv.nodes, { indexFetchedAt: inv.fetchedAt });

  if (args.json) {
    console.log(JSON.stringify({
      provenance: {
        host: rec.host, hostname: rec.hostname, project: rec.project, dir: rec.dir, id: rec.id,
        file: rec.file, mtime: new Date(rec.mtime).toISOString(), bytes: rec.bytes, kind: rec.kind,
        role: rec.role, title: h.title || rec.title || null, preset: h.header.preset || rec.preset || null,
        cwd: h.header.cwd || rec.cwd || null, origin: h.header.origin || 'main',
        parentSession: h.header.parentSession || null, events: info.events.length, frames: info.frames,
        failedFrames: info.failedFrames, unparseableLines: info.bad, truncated: info.truncated,
        indexFetchedAt: inv.fetchedAt,
      },
      turns: [...new Set(rows.filter((r) => r.turn > 0).map((r) => r.turn))].length,
      rows: rows.map((r) => ({ turn: r.turn, type: r.type, time: r.time ? new Date(r.time).toISOString() : null, text: r.full || r.text })),
    }, null, 2));
    return 0;
  }

  const body = `--- SESSION TRANSCRIPT ---\n${header}\n${'-'.repeat(78)}\n${renderTranscript(rec, { turnCount: rows.reduce((a, r) => Math.max(a, r.turn || 0), 0) }, rows, opts)}\n${'-'.repeat(78)}\n${rows.length} rendered row(s) from ${info.events.length} event(s) — ${ms(Date.now() - t0)}`;
  if (typeof args.out === 'string') {
    fs.writeFileSync(args.out, body + '\n');
    console.log(`${header}\n\nwrote ${rows.length} row(s) to ${args.out}`);
    return 0;
  }
  console.log(body);
  return 0;
}

async function cmdFind(args) {
  const words = args._.slice(1).join(' ').trim();
  if (!words) { console.error('find: give me words to look for, e.g. `find LPT growth revenue`'); return 2; }
  const terms = words.toLowerCase().split(/\s+/).filter(Boolean);
  const inv = await gather({ refresh: !!args.refresh, hosts: targetHosts(args), log: (m) => console.error(m) });
  let rows = flatten(inv.nodes);
  const since = parseSince(typeof args.since === 'string' ? args.since : '30d');
  if (since) rows = rows.filter((r) => r.mtime >= since);
  if (!args.sub) rows = rows.filter((r) => r.role === 'main');

  // The session you are standing in always contains the words you are asking
  // about, and it is the newest — so a search for a topic under discussion
  // returns ITSELF at the top and buries the session you meant. Excluded by
  // default, and the exclusion is printed rather than silent.
  const selfId = String(process.env.DSH_SESSION_ID || '').replace(/^session-/, '');
  let selfNote = '';
  if (selfId && !args['include-self']) {
    const before = rows.length;
    rows = rows.filter((r) => r.id !== selfId);
    if (rows.length !== before) selfNote = `this session (${selfId}) excluded — --include-self to see it`;
  }

  // Pass 1 — the inventory already carries titles and project slugs, which is
  // free because the inventory is one ssh call. A title is a strong hint and a
  // weak filter: a session whose title says nothing about the topic can still be
  // the one, so the newest sessions in the window are scanned as well.
  const titleHits = rows.filter((r) => {
    const blob = `${r.title || ''} ${r.project || ''} ${r.cwd || ''}`.toLowerCase();
    return terms.some((t) => blob.includes(t));
  });

  // Pass 2 — decode the head of each candidate and count term hits in the real
  // transcript. Only the head by default: a full-fleet full-content scan is a
  // multi-hundred-megabyte transfer and is not what a question costs.
  const headBytes = Number(args['head-bytes'] || (args.full ? 0 : 262144));
  const scanN = Number(args.scan || (args['scan-all'] ? rows.length : 200));
  const recent = args['scan-all'] ? rows : rows.slice(0, scanN);
  const pool = [];
  const seen = new Set();
  for (const r of [...titleHits, ...recent]) {
    const k = `${r.host}/${r.id}`;
    if (seen.has(k)) continue;
    seen.add(k);
    pool.push(r);
  }
  const unscanned = rows.length - pool.length;
  const mode = `${pool.length} read: ${titleHits.length} title/project match(es) + newest ${recent.length}${unscanned > 0 ? `; ${unscanned} older session(s) in the window were NOT scanned (--scan N, or --scan-all)` : '; the whole window was covered'}${selfNote ? `; ${selfNote}` : ''}`;
  const scored = [];
  const scanned = [];
  const failed = [];
  const t0 = Date.now();
  const perBatch = Number(args['per-batch'] || 150);

  const scoreOne = (rec, buf, fileBytes, truncated) => {
    const dec = decodeFrames(buf);
    const text = dec.text.toLowerCase();
    let score = 0;
    const which = [];
    for (const t of terms) { const n = text.split(t).length - 1; if (n) { score += n; which.push(`${t}:${n}`); } }
    const h = headerOf(parseEvents(dec.text).events);
    return {
      rec, score, which, frames: dec.frames, failed: dec.failed, fileBytes,
      covered: truncated ? buf.length : fileBytes,
      title: h.title || rec.title, header: h.header, partial: !!truncated,
    };
  };

  // ONE ssh per host, not one per session (see fetchBatch). Hosts run in
  // parallel; within a host the batches are sequential, which is what keeps a
  // large search from turning into a connection storm against one sshd.
  const byHost = new Map();
  for (const rec of pool) {
    if (!byHost.has(rec.host)) byHost.set(rec.host, []);
    byHost.get(rec.host).push(rec);
  }
  await Promise.all([...byHost.entries()].map(async ([host, list]) => {
    if (isLocalHost(host)) {
      for (const rec of list) {
        try {
          const { buf, fileBytes, truncated } = await fetchBytes(rec, headBytes || null);
          const g = scoreOne(rec, buf, fileBytes, truncated);
          scanned.push(g);
          if (g.score > 0) scored.push(g);
        } catch (error) { failed.push({ rec, error: error.message }); }
      }
      return;
    }
    for (let i = 0; i < list.length; i += perBatch) {
      const chunk = list.slice(i, i + perBatch);
      let res;
      try {
        res = await fetchBatch(host, chunk, headBytes || null);
      } catch (error) {
        for (const rec of chunk) failed.push({ rec, error: error.message });
        continue;
      }
      for (const rec of chunk) {
        const got = res.get(rec.id);
        if (!got) { failed.push({ rec, error: 'the batch read returned no frame for this file' }); continue; }
        if (got.error) { failed.push({ rec, error: got.error }); continue; }
        try {
          const g = scoreOne(rec, got.buf, got.fileBytes, got.truncated);
          scanned.push(g);
          if (g.score > 0) scored.push(g);
        } catch (error) { failed.push({ rec, error: error.message }); }
      }
    }
  }));
  scored.sort((a, b) => b.score - a.score || b.rec.mtime - a.rec.mtime);

  const coverage = `${mode}; ${scanned.length} read (${pool.length} candidates of ${rows.length} in window), head ${headBytes ? kb(headBytes) : 'full file'}, ${ms(Date.now() - t0)}`;
  if (args.json) {
    console.log(JSON.stringify({ terms, indexFetchedAt: inv.fetchedAt, coverage, failed, results: scored.slice(0, Number(args.limit || 10)) }, null, 2));
    return 0;
  }
  console.log(`# find ${JSON.stringify(words)}  —  ${coverage}`);
  console.log(`# inventory ${ageStr(inv.fetchedAt)}; window since ${typeof args.since === 'string' ? args.since : '30d'}`);
  for (const n of inv.nodes) if (!n.ok) console.log(`# UNREACHABLE ${n.host}: ${n.error}`);
  if (failed.length) console.log(`# ${failed.length} session(s) could not be read: ${failed.slice(0, 3).map((f) => `${f.rec.id}: ${f.error}`).join('; ')}`);
  if (scored.length === 0) {
    console.log('# no match. This is a refusal: coverage above is what was actually read.');
    console.log('#   widen: --since 90d, --sub, --full, --scan 2000, or --host <node>');
    return 0;
  }
  for (const s of scored.slice(0, Number(args.limit || 10))) {
    console.log(`\nscore ${String(s.score).padStart(6)}  (${s.which.join(' ')})  ${tsStr(s.rec.mtime)}  ${s.rec.host}/${s.rec.kind}  ${s.rec.id}`);
    console.log(`      ${s.title ? `“${clip(s.title, 74)}”  ` : ''}preset=${s.header.preset || s.rec.preset || '?'}  project=${s.rec.project}`);
    console.log(`      ${s.partial ? `read first ${kb(s.covered)} of ${kb(s.fileBytes)} — mentions later in the file are NOT visible` : `read all ${kb(s.fileBytes)}`}`);
    console.log(`      show: node scripts/sessions.mjs show ${s.rec.id} --host ${s.rec.host}`);
  }
  return 0;
}

async function cmdGrep(args) {
  const re = args._[1];
  const idArg = args._[2] || 'latest';
  if (!re) { console.error('grep: give me a regex and a session id'); return 2; }
  const inv0 = await resolveWithCache(args, idArg);
  const res = inv0.res;
  if (res.error) { console.error(`grep: ${res.error}`); return 1; }
  const info = await readSession(res.rec);
  const rx = new RegExp(re, 'i');
  let n = 0;
  for (const e of info.events) {
    const line = JSON.stringify(e);
    if (rx.test(line)) { console.log(clip(line, 700)); n++; if (n > 200) { console.log('… 200 hits is the ceiling; narrow the regex'); break; } }
  }
  console.error(`${n} matching event(s) of ${info.events.length} in ${res.rec.id}@${res.rec.host}`);
  return 0;
}

async function cmdResolve(args) {
  const idArg = typeof args._[1] === 'string' ? args._[1] : 'latest';
  const { res } = await resolveWithCache(args, idArg);
  if (res.error) { console.error(`resolve: ${res.error}`); return 1; }
  const rec = res.rec;
  if (args.json) { console.log(JSON.stringify(rec, null, 2)); return 0; }
  console.log(`${rec.id}\thost=${rec.host}\tkind=${rec.kind}\trole=${rec.role}\tmtime=${tsStr(rec.mtime)}\tbytes=${rec.bytes}`);
  console.log(`${rec.file}`);
  if (res.ambiguous) {
    console.log(`(${res.ambiguous.length} candidates; the newest was used. Others:`);
    for (const a of res.ambiguous.slice(1)) console.log(`  ${a.id}  ${tsStr(a.mtime)}  ${a.host}/${a.project}`);
    console.log(')');
  }
  return 0;
}

// ---------------------------------------------------------------------------

const COMMANDS = {
  doctor: cmdDoctor, nodes: cmdNodes, list: cmdList, show: cmdShow,
  find: cmdFind, grep: cmdGrep, resolve: cmdResolve,
};

function usage() {
  console.log(`sessions — read any DSH session on any machine

  sessions doctor                                prove the reader works
  sessions nodes                                 the fleet and what answered
  sessions list  [--since 7d] [--limit 30] [--sub] [--project SUB]
  sessions find  <words...> [--since 30d] [--full] [--scan N]
  sessions show  <id|latest> [--user] [--turn N] [--tools] [--reasoning]
  sessions grep  <regex> <id>
  sessions resolve <id>

common: [--host NODE|all] [--all] [--refresh] [--json]
docs:   harness-config/docs/session-reading.md`);
  return 0;
}

async function main() {
  const argv = process.argv.slice(2);
  const args = parseArgs(argv);
  const cmd = args._[0];
  if (!cmd || cmd === 'help' || args.help) return usage();
  const fn = COMMANDS[cmd];
  if (!fn) { console.error(`sessions: unknown command ${JSON.stringify(cmd)}\n`); usage(); return 2; }
  if (args.all && typeof args.host !== 'string') args.host = 'all';
  return fn(args);
}

main().then(
  (code) => process.exit(Number.isInteger(code) ? code : 0),
  (error) => { console.error(`sessions: ${error && error.message ? error.message : error}`); process.exit(1); },
);
